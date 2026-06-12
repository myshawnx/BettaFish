"""轻量级 Portfolio 工具函数集合。

这些函数刻意不依赖 `mcp` SDK，保证在无 key、无 live crawler、无 MCP 依赖的环境下也能
被单元测试直接导入和调用。`MCPServer/server.py` 只是在其上做一层可选的 MCP 包装。

设计原则:
- 所有工具返回 JSON 可序列化的 dict。
- 数据库 / 论坛 / 配置不可用时，返回结构化的 error 字段，而不是抛异常。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = PROJECT_ROOT / "sample_data" / "portfolio_insight_seed.json"

PLACEHOLDER_VALUES = {
    "",
    "your_db_host",
    "your_db_user",
    "your_db_password",
    "your_db_name",
}


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _load_settings():
    """加载最新配置（reload 以反映环境变量改动）。"""
    from config import reload_settings, settings

    try:
        reload_settings()
    except Exception:  # pragma: no cover - reload 失败时退回已加载实例
        pass
    return settings


def portfolio_system_status() -> Dict[str, Any]:
    """返回作品集运行时状态：demo 模式、爬虫开关、数据库配置摘要。"""
    try:
        settings = _load_settings()
    except Exception as exc:  # pragma: no cover - 配置导入失败
        return {
            "success": False,
            "error": f"无法加载配置: {exc}",
        }

    db_required = {
        "host": getattr(settings, "DB_HOST", None),
        "user": getattr(settings, "DB_USER", None),
        "password": getattr(settings, "DB_PASSWORD", None),
        "name": getattr(settings, "DB_NAME", None),
    }
    db_configured = all(
        str(value or "").strip() not in PLACEHOLDER_VALUES for value in db_required.values()
    )

    return {
        "success": True,
        "portfolio_demo_mode": _as_bool(getattr(settings, "PORTFOLIO_DEMO_MODE", True), True),
        "live_crawlers_enabled": _as_bool(getattr(settings, "ENABLE_LIVE_CRAWLERS", False)),
        "database": {
            "dialect": getattr(settings, "DB_DIALECT", "") or "postgresql",
            "host": getattr(settings, "DB_HOST", ""),
            "port": getattr(settings, "DB_PORT", ""),
            "database": getattr(settings, "DB_NAME", ""),
            "configured": db_configured,
        },
        "forum_host_llm_enabled": bool(str(getattr(settings, "FORUM_HOST_API_KEY", "") or "").strip()),
        "endpoints": [
            "/api/system/status",
            "/api/forum/log",
            "/api/forum/moderator/status",
            "/api/report/status",
        ],
    }


def portfolio_forum_status() -> Dict[str, Any]:
    """返回论坛日志摘要与主持人最新结构化状态。"""
    moderator: Dict[str, Any]
    try:
        from ForumEngine.monitor import get_moderator_status

        moderator = get_moderator_status()
    except Exception as exc:
        moderator = {
            "risk_level": "medium",
            "action": "investigate",
            "error": f"无法读取主持人状态: {exc}",
        }

    log_lines: List[str] = []
    log_error = None
    try:
        from ForumEngine.monitor import get_forum_log

        raw_lines = get_forum_log() or []
        log_lines = [line for line in raw_lines if line and line.strip()]
    except Exception as exc:
        log_error = f"无法读取论坛日志: {exc}"

    return {
        "success": True,
        "moderator": moderator,
        "log_line_count": len(log_lines),
        "recent_log_lines": log_lines[-10:],
        "log_error": log_error,
    }


def portfolio_search_insights(topic: str, limit: int = 10) -> Dict[str, Any]:
    """包装 InsightEngine 的确定性话题搜索路径，优先命中 Postgres seed 数据。

    数据库不可用时返回明确的 error 字段，而不是抛异常。
    """
    if not topic or not str(topic).strip():
        return {"success": False, "error": "topic 不能为空", "results": []}

    try:
        safe_limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        safe_limit = 10

    try:
        from InsightEngine.tools.search import MediaCrawlerDB

        db = MediaCrawlerDB()
        response = db.search_topic_globally(topic=str(topic).strip(), limit_per_table=safe_limit)
    except Exception as exc:
        return {
            "success": False,
            "topic": topic,
            "error": f"InsightEngine 搜索不可用: {exc}",
            "results": [],
        }

    results = []
    for item in (response.results or [])[:safe_limit]:
        results.append(
            {
                "platform": item.platform,
                "content_type": item.content_type,
                "title_or_content": (item.title_or_content or "")[:300],
                "author": item.author_nickname,
                "url": item.url,
                "publish_time": item.publish_time.isoformat() if item.publish_time else None,
                "source_table": item.source_table,
            }
        )

    return {
        "success": response.error_message is None,
        "topic": topic,
        "results_count": len(results),
        "results": results,
        "error": response.error_message,
    }


def portfolio_demo_topics() -> Dict[str, Any]:
    """列出样例数据支持的面试演示主题。"""
    if not SEED_PATH.exists():
        return {
            "success": False,
            "error": f"未找到 seed 数据文件: {SEED_PATH}",
            "topics": [],
        }

    try:
        data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"success": False, "error": f"seed 数据解析失败: {exc}", "topics": []}

    topics = []
    for row in data.get("tables", {}).get("daily_topics", []):
        topics.append(
            {
                "topic_id": row.get("topic_id"),
                "topic_name": row.get("topic_name"),
                "description": row.get("topic_description"),
                "keywords": row.get("keywords"),
                "extract_date": row.get("extract_date"),
            }
        )

    return {
        "success": True,
        "topics_count": len(topics),
        "topics": topics,
    }


# 工具注册表：name -> (callable, description)
TOOL_REGISTRY = {
    "portfolio_system_status": (
        portfolio_system_status,
        "返回作品集运行时状态：demo 模式、爬虫开关、数据库配置摘要。",
    ),
    "portfolio_forum_status": (
        portfolio_forum_status,
        "返回论坛日志摘要与主持人最新结构化状态。",
    ),
    "portfolio_search_insights": (
        portfolio_search_insights,
        "在 InsightEngine 舆情库中按话题搜索（优先 seed 数据）。",
    ),
    "portfolio_demo_topics": (
        portfolio_demo_topics,
        "列出样例数据支持的面试演示主题。",
    ),
}
