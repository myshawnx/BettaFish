import shutil
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


TEST_LOG_DIR = PROJECT_ROOT / "tests" / "test_logs" / "agent_runtime"


def _reset_log_dir(path: Path = TEST_LOG_DIR):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def test_agent_runtime_records_runs_and_events():
    _reset_log_dir()

    from AgentRuntime import (
        finish_run,
        get_runtime_status,
        list_events,
        list_runs,
        record_event,
        start_run,
    )

    run = start_run(
        engine="insight",
        query="low altitude logistics",
        thread_id="thread-1",
        checkpoint_path=".checkpoints/insight.db",
        log_dir=TEST_LOG_DIR,
    )
    event = record_event(
        engine="insight",
        run_id=run["run_id"],
        thread_id="thread-1",
        event_type="node_completed",
        node="summarize_paragraph",
        payload={"current_summary": "summary", "search_results_count": 3},
        log_dir=TEST_LOG_DIR,
    )
    finished = finish_run(
        run["run_id"],
        "completed",
        final_report_path="reports/final.md",
        log_dir=TEST_LOG_DIR,
    )

    runs = list_runs(log_dir=TEST_LOG_DIR)
    events = list_events(run_id=run["run_id"], log_dir=TEST_LOG_DIR)
    status = get_runtime_status(log_dir=TEST_LOG_DIR)

    assert finished["status"] == "completed"
    assert runs[0]["run_id"] == run["run_id"]
    assert runs[0]["final_report_path"] == "reports/final.md"
    assert event["event_id"]
    assert {item["event_type"] for item in events} >= {
        "run_started",
        "node_completed",
        "run_completed",
    }
    assert status["success"] is True
    assert status["run_count"] == 1
    assert status["latest_by_engine"]["insight"]["status"] == "completed"


def test_langgraph_payload_is_compact_and_structured():
    from AgentRuntime import build_langgraph_payload

    payload = build_langgraph_payload(
        "summarize_paragraph",
        {
            "query": "topic",
            "current_paragraph_index": 0,
            "paragraphs": [{"title": "Market signal", "order": 0}],
        },
        {
            "current_summary": "x" * 2100,
            "current_search_results": [
                {"title": "A", "url": "https://example.com/a", "platform": "web"},
                {"title_or_content": "B", "url": "https://example.com/b"},
            ],
            "messages": ["done"],
        },
    )

    assert payload["query"] == "topic"
    assert payload["paragraph_title"] == "Market signal"
    assert payload["search_results_count"] == 2
    assert payload["search_result_samples"][0]["title"] == "A"
    assert payload["current_summary"].endswith("[truncated]")


def test_forum_monitor_consumes_structured_runtime_events():
    log_dir = TEST_LOG_DIR / "forum"
    _reset_log_dir(log_dir)

    from AgentRuntime import record_event, start_run
    from ForumEngine.monitor import LogMonitor

    run = start_run(
        engine="query",
        query="battery swapping policy",
        thread_id="thread-forum",
        log_dir=log_dir,
    )
    record_event(
        engine="query",
        run_id=run["run_id"],
        thread_id="thread-forum",
        event_type="node_completed",
        node="summarize_paragraph",
        payload={
            "paragraph_title": "Policy risk",
            "current_summary": "Policy gap and compliance risk are rising.",
            "search_results_count": 4,
        },
        log_dir=log_dir,
    )

    monitor = LogMonitor(log_dir=str(log_dir))
    captured = monitor._poll_agent_runtime_events()

    assert captured is True
    assert any("summary=" in line for line in monitor.get_forum_log_content())
    assert any("[QUERY]" in line for line in monitor.agent_speeches_buffer)
