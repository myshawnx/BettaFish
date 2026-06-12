"""Portfolio MCP server 入口（可选增强）。

设计目标:
- 不把 MCP server 接入 Flask 主进程，保持独立启动。
- `mcp` SDK 缺失时给出明确安装提示，而不是破坏主项目导入。
- 工具逻辑全部来自 `MCPServer.tools`，保证可被单测直接覆盖。

用法:
    uv run python -m MCPServer.server --help
    uv run python -m MCPServer.server --list
    uv run python -m MCPServer.server            # 启动 stdio MCP server（需安装 mcp）
"""

from __future__ import annotations

import argparse
import json
import sys

from .tools import TOOL_REGISTRY

MCP_INSTALL_HINT = (
    "未检测到 `mcp` 依赖。MCP server 是可选增强路径，安装后即可启动:\n"
    "    uv pip install mcp\n"
    "在此之前，工具函数仍可通过 `python -m MCPServer.server --list` 或直接导入使用。"
)


def list_tools() -> int:
    """打印已注册的工具清单。"""
    print("Portfolio MCP tools:")
    for name, (_, description) in TOOL_REGISTRY.items():
        print(f"  - {name}: {description}")
    return 0


def call_tool(name: str, payload: dict) -> int:
    """直接调用单个工具并打印 JSON 结果（便于无 MCP 环境下手动验证）。"""
    if name not in TOOL_REGISTRY:
        print(f"未知工具: {name}", file=sys.stderr)
        return 2
    func, _ = TOOL_REGISTRY[name]
    result = func(**(payload or {}))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _build_mcp_server():
    """构建 MCP server 实例。缺少 mcp 依赖时返回 None。"""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        return None

    server = FastMCP("bettafish-portfolio")
    for name, (func, description) in TOOL_REGISTRY.items():
        server.add_tool(func, name=name, description=description)
    return server


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="MCPServer.server",
        description="BettaFish Portfolio MCP server（独立启动，可选增强）。",
    )
    parser.add_argument("--list", action="store_true", help="列出已注册工具后退出")
    parser.add_argument("--call", metavar="TOOL", help="直接调用指定工具并打印 JSON 结果")
    parser.add_argument(
        "--args",
        metavar="JSON",
        default="{}",
        help="配合 --call 使用的 JSON 参数，例如 '{\"topic\": \"低空物流\"}'",
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

    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
