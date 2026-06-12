"""Portfolio MCP server package.

导出可直接调用、可单测的工具函数。MCP SDK 为可选增强项，缺失时工具函数依然可用。
"""

from .tools import (
    TOOL_REGISTRY,
    portfolio_agent_events,
    portfolio_agent_runs,
    portfolio_agent_runtime_status,
    portfolio_demo_topics,
    portfolio_forum_status,
    portfolio_search_insights,
    portfolio_system_status,
)

__all__ = [
    "TOOL_REGISTRY",
    "portfolio_agent_events",
    "portfolio_agent_runs",
    "portfolio_agent_runtime_status",
    "portfolio_demo_topics",
    "portfolio_forum_status",
    "portfolio_search_insights",
    "portfolio_system_status",
]
