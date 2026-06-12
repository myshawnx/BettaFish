import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TEST_LOG_DIR = PROJECT_ROOT / "tests" / "test_logs" / "mcp_runtime"


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


def test_portfolio_search_insights_preserves_limit_order_and_fields(monkeypatch):
    import InsightEngine.tools.search as search_module

    class FakeDB:
        def search_topic_globally(self, topic, limit_per_table):
            assert topic == "低空物流"
            assert limit_per_table == 2
            return SimpleNamespace(
                error_message=None,
                results=[
                    SimpleNamespace(
                        platform="xhs",
                        content_type="note",
                        title_or_content="first result",
                        author_nickname="alice",
                        url="https://example.com/1",
                        publish_time=datetime(2026, 5, 20, 8, 0, 0),
                        source_table="xhs_note",
                    ),
                    SimpleNamespace(
                        platform="douyin",
                        content_type="comment",
                        title_or_content="second result",
                        author_nickname="bob",
                        url="https://example.com/2",
                        publish_time=None,
                        source_table="douyin_comment",
                    ),
                    SimpleNamespace(
                        platform="weibo",
                        content_type="post",
                        title_or_content="third result",
                        author_nickname="carol",
                        url="https://example.com/3",
                        publish_time=None,
                        source_table="weibo_note",
                    ),
                ],
            )

    monkeypatch.setattr(search_module, "MediaCrawlerDB", FakeDB)

    from MCPServer.tools import portfolio_search_insights

    result = portfolio_search_insights(topic=" 低空物流 ", limit=2)

    assert result["success"] is True
    assert result["results_count"] == 2
    assert [item["platform"] for item in result["results"]] == ["xhs", "douyin"]
    assert result["results"][0]["publish_time"] == "2026-05-20T08:00:00"


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
        "portfolio_agent_runtime_status",
        "portfolio_agent_runs",
        "portfolio_agent_events",
        "portfolio_system_status",
        "portfolio_forum_status",
        "portfolio_search_insights",
        "portfolio_demo_topics",
    }
    assert expected.issubset(set(TOOL_REGISTRY))
    for name, (func, description) in TOOL_REGISTRY.items():
        assert callable(func)
        assert description


def test_portfolio_agent_runtime_tools_return_json(monkeypatch):
    if TEST_LOG_DIR.exists():
        shutil.rmtree(TEST_LOG_DIR)
    TEST_LOG_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AGENT_RUNTIME_LOG_DIR", str(TEST_LOG_DIR))

    from AgentRuntime import finish_run, record_event, start_run
    from MCPServer.tools import (
        portfolio_agent_events,
        portfolio_agent_runs,
        portfolio_agent_runtime_status,
    )

    run = start_run("media", "camera policy", "thread-mcp")
    record_event(
        "media",
        run["run_id"],
        "thread-mcp",
        "node_completed",
        node="search_paragraph",
        payload={"current_search_query": "camera policy", "search_results_count": 2},
    )
    finish_run(run["run_id"], "completed", final_report_path="reports/media.md")

    status = portfolio_agent_runtime_status()
    runs = portfolio_agent_runs(limit=5)
    events = portfolio_agent_events(engine="media", limit=10)

    assert status["success"] is True
    assert status["latest_by_engine"]["media"]["status"] == "completed"
    assert runs["runs_count"] == 1
    assert events["events_count"] >= 3
    assert any(event["node"] == "search_paragraph" for event in events["events"])


def test_server_builds_mcp_server_with_default_dependency():
    from MCPServer import server

    mcp_server = server._build_mcp_server()

    assert mcp_server is not None
    assert hasattr(mcp_server, "run")


def test_server_list_and_call_paths(capsys):
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
