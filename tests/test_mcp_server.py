import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_portfolio_system_status_reports_demo_mode(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DEMO_MODE", "true")
    monkeypatch.setenv("ENABLE_LIVE_CRAWLERS", "false")

    from MCPServer.tools import portfolio_system_status

    status = portfolio_system_status()

    assert status["success"] is True
    assert status["portfolio_demo_mode"] is True
    assert status["live_crawlers_enabled"] is False
    assert status["database"]["dialect"]
    assert "/api/forum/moderator/status" in status["endpoints"]


def test_portfolio_demo_topics_lists_seed_topics():
    from MCPServer.tools import portfolio_demo_topics

    result = portfolio_demo_topics()

    assert result["success"] is True
    assert result["topics_count"] >= 1
    assert all(topic["topic_id"] for topic in result["topics"])


def test_portfolio_search_insights_handles_unavailable_db_gracefully(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DEMO_MODE", "true")
    monkeypatch.setenv("ENABLE_LIVE_CRAWLERS", "false")
    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    monkeypatch.setenv("DB_PORT", "1")  # 不可达端口，确保不会真正连库

    from MCPServer.tools import portfolio_search_insights

    result = portfolio_search_insights(topic="低空物流", limit=5)

    # 数据库不可用时必须返回结构化结果，而不是抛异常
    assert "results" in result
    assert isinstance(result["results"], list)
    assert "success" in result


def test_portfolio_search_insights_rejects_empty_topic():
    from MCPServer.tools import portfolio_search_insights

    result = portfolio_search_insights(topic="  ", limit=5)

    assert result["success"] is False
    assert result["results"] == []


def test_portfolio_forum_status_returns_moderator_block():
    from MCPServer.tools import portfolio_forum_status

    result = portfolio_forum_status()

    assert result["success"] is True
    assert "moderator" in result
    assert "log_line_count" in result
    assert isinstance(result["recent_log_lines"], list)


def test_tool_registry_exposes_all_tools():
    from MCPServer.tools import TOOL_REGISTRY

    expected = {
        "portfolio_system_status",
        "portfolio_forum_status",
        "portfolio_search_insights",
        "portfolio_demo_topics",
    }
    assert expected.issubset(set(TOOL_REGISTRY))
    for name, (func, description) in TOOL_REGISTRY.items():
        assert callable(func)
        assert description


def test_server_list_and_call_paths_do_not_require_mcp(capsys):
    from MCPServer import server

    assert server.list_tools() == 0
    listed = capsys.readouterr().out
    assert "portfolio_system_status" in listed

    rc = server.call_tool("portfolio_demo_topics", {})
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True

    assert server.call_tool("does_not_exist", {}) == 2


def test_server_main_list_flag(capsys):
    from MCPServer import server

    assert server.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "portfolio_forum_status" in out
