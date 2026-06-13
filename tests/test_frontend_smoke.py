import importlib
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_app(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DEMO_MODE", "true")
    monkeypatch.setenv("ENABLE_LIVE_CRAWLERS", "false")

    import app as flask_app

    return importlib.reload(flask_app)


def test_portfolio_system_status_does_not_require_external_services(monkeypatch):
    flask_app = load_app(monkeypatch)

    with flask_app.app.test_client() as client:
        response = client.get("/api/system/status")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["portfolio_demo_mode"] is True
    assert payload["live_crawlers_enabled"] is False
    assert payload["database"]["dialect"]


def test_main_page_and_status_endpoints_render_without_startup(monkeypatch):
    flask_app = load_app(monkeypatch)

    with flask_app.app.test_client() as client:
        index_response = client.get("/")
        app_status_response = client.get("/api/status")
        forum_response = client.get("/api/forum/log")
        report_response = client.get("/api/report/status")

    assert index_response.status_code == 200
    assert b"BettaFish" in index_response.data or b"Agent" in index_response.data
    assert b"forumOpenReportButton" in index_response.data
    assert b"openReportFromForum" in index_response.data

    assert app_status_response.status_code == 200
    app_status = app_status_response.get_json()
    assert set(["insight", "media", "query", "forum"]).issubset(app_status)

    assert forum_response.status_code == 200
    forum_payload = forum_response.get_json()
    assert forum_payload["success"] is True
    assert "log_lines" in forum_payload
    assert "parsed_messages" in forum_payload

    assert report_response.status_code in (200, 500)
    assert report_response.is_json


def test_query_streamlit_exposes_checkpoint_resume_entrypoint():
    source = (PROJECT_ROOT / "SingleEngineApp" / "query_engine_langgraph_streamlit_app.py").read_text()

    assert "resume_thread_id" in source
    assert "从 checkpoint 手动恢复" in source
    assert "从 checkpoint 继续" in source
    assert "resume_requested = st.button" in source
    assert source.index("if not resume_requested") < source.index("resume_research(resume_query.strip()")


def test_system_start_uses_optional_crawler_demo_path(monkeypatch):
    flask_app = load_app(monkeypatch)

    def fake_initialize_system_components():
        return True, ["ENABLE_LIVE_CRAWLERS=false，跳过 MindSpider/MediaCrawler 初始化"], []

    monkeypatch.setattr(flask_app, "initialize_system_components", fake_initialize_system_components)
    flask_app._set_system_state(started=False, starting=False)

    with flask_app.app.test_client() as client:
        response = client.post("/api/system/start")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert any("ENABLE_LIVE_CRAWLERS=false" in line for line in payload["logs"])

    flask_app._set_system_state(started=False, starting=False)
