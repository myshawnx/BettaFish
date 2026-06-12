"""Portfolio MCP server entrypoint.

The tool functions live in ``MCPServer.tools`` so they remain directly
testable. This module only adapts them to the MCP SDK and keeps the CLI paths
for quick local verification.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from typing import Any, Callable

from .tools import TOOL_REGISTRY

MCP_INSTALL_HINT = (
    "未检测到 `mcp` 依赖。MCP server 是默认能力，请先安装项目依赖:\n"
    "    uv pip install -r requirements.txt\n"
    "工具函数仍可通过 `python -m MCPServer.server --list` 或直接导入使用。"
)


def list_tools() -> int:
    """Print registered tools."""
    print("Portfolio MCP tools:")
    for name, (_, description) in TOOL_REGISTRY.items():
        print(f"  - {name}: {description}")
    return 0


def call_tool(name: str, payload: dict) -> int:
    """Call one tool directly and print its JSON result."""
    if name not in TOOL_REGISTRY:
        print(f"未知工具: {name}", file=sys.stderr)
        return 2
    func, _ = TOOL_REGISTRY[name]
    result = func(**(payload or {}))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _annotation_to_json_type(annotation: Any) -> str:
    if annotation in (inspect.Signature.empty, Any):
        return "string"
    name = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", "")
    return {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "dict": "object",
        "list": "array",
    }.get(name, "string")


def _tool_input_schema(func: Callable) -> dict:
    properties = {}
    required = []
    for name, param in inspect.signature(func).parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        properties[name] = {"type": _annotation_to_json_type(param.annotation)}
        if param.default is inspect.Parameter.empty:
            required.append(name)

    schema = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _build_legacy_mcp_server():
    """Build an MCP server for mcp 0.9.x, which does not ship FastMCP."""
    from mcp import types
    from mcp.server import Server

    server = Server("bettafish-portfolio")

    @server.list_tools()
    async def _list_tools():
        return [
            types.Tool(
                name=name,
                description=description,
                inputSchema=_tool_input_schema(func),
            )
            for name, (func, description) in TOOL_REGISTRY.items()
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict):
        if name not in TOOL_REGISTRY:
            payload = {"success": False, "error": f"未知工具: {name}"}
        else:
            func, _ = TOOL_REGISTRY[name]
            try:
                payload = func(**(arguments or {}))
            except Exception as exc:  # pragma: no cover - runtime guard
                payload = {"success": False, "error": str(exc)}

        return [
            types.TextContent(
                type="text",
                text=json.dumps(payload, ensure_ascii=False, indent=2),
            )
        ]

    return server


def _build_mcp_server():
    """Build an MCP server instance; return None only when the SDK is missing."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        try:
            return _build_legacy_mcp_server()
        except ImportError:
            return None

    server = FastMCP("bettafish-portfolio")
    for name, (func, description) in TOOL_REGISTRY.items():
        server.add_tool(func, name=name, description=description)
    return server


def _run_mcp_server(server) -> int:
    if server.__class__.__name__ == "FastMCP":
        server.run()
        return 0

    import anyio

    try:
        from mcp.server.stdio import stdio_server
    except ImportError:  # mcp 0.9.x
        from mcp.server import stdio_server

    async def _serve():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    anyio.run(_serve)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="MCPServer.server",
        description="BettaFish Portfolio MCP server（独立 stdio 启动）。",
    )
    parser.add_argument("--list", action="store_true", help="列出已注册工具后退出")
    parser.add_argument("--call", metavar="TOOL", help="直接调用指定工具并打印 JSON 结果")
    parser.add_argument(
        "--args",
        metavar="JSON",
        default="{}",
        help='配合 --call 使用的 JSON 参数，例如 \'{"topic": "低空物流"}\'',
    )
    args = parser.parse_args(argv)

    if args.list:
        return list_tools()

    if args.call:
        try:
            payload = json.loads(args.args)
        except json.JSONDecodeError as exc:
            print(f"--args 不是合法 JSON: {exc}", file=sys.stderr)
            return 2
        return call_tool(args.call, payload)

    server = _build_mcp_server()
    if server is None:
        print(MCP_INSTALL_HINT, file=sys.stderr)
        return 1

    return _run_mcp_server(server)


if __name__ == "__main__":
    raise SystemExit(main())
