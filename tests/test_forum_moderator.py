import importlib
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_forum_host_generates_structured_fallback_without_api_key():
    from ForumEngine.llm_host import ForumHost

    host = ForumHost(api_key="")
    logs = [
        "[10:00:00] [INSIGHT] 洛阳钼业出现舆情风险，需要关注市场下跌与投诉信号",
        "[10:00:01] [MEDIA] 媒体报道存在争议，传播范围正在扩大",
        "[10:00:02] [QUERY] 公开信息仍有不确定，需要进一步核验",
    ]

    verdict = host.generate_moderator_verdict(logs)

    assert verdict["risk_level"] in {"medium", "high"}
    assert verdict["action"] in {"investigate", "escalate"}
    assert verdict["source_count"] == 3
    assert verdict["llm_enabled"] is False
    assert verdict["suggested_host_message"]


def test_forum_host_speech_falls_back_without_api_key():
    from ForumEngine.llm_host import ForumHost

    host = ForumHost(api_key="")
    speech = host.generate_host_speech([
        "[10:00:00] [INSIGHT] 当前事件存在风险，需要补充证据",
        "[10:00:01] [MEDIA] 媒体侧出现负面扩散",
    ])

    assert speech is not None
    assert "主持人" in speech


def test_log_monitor_exposes_default_and_generated_moderator_status():
    from ForumEngine.monitor import LogMonitor

    test_log_dir = PROJECT_ROOT / "tests" / "test_logs" / "moderator"
    test_log_dir.mkdir(parents=True, exist_ok=True)
    monitor = LogMonitor(log_dir=str(test_log_dir))
    default_status = monitor.get_moderator_status()
    assert default_status["risk_level"] == "low"
    assert default_status["action"] == "wait"

    monitor.agent_speeches_buffer = [
        "[10:00:00] [INSIGHT] 该公司出现风险与投诉，需要关注",
        "[10:00:01] [MEDIA] 舆情争议正在扩散",
        "[10:00:02] [QUERY] 信息存在不确定，需要进一步核验",
        "[10:00:03] [INSIGHT] 下跌风险可能影响市场预期",
        "[10:00:04] [MEDIA] 负面内容传播速度较快",
    ]
    monitor._trigger_host_speech()

    status = monitor.get_moderator_status()
    assert status["risk_level"] in {"medium", "high"}
    assert status["source_count"] >= 1
    assert status["suggested_host_message"]


def test_forum_moderator_status_endpoint_without_external_services(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DEMO_MODE", "true")
    monkeypatch.setenv("ENABLE_LIVE_CRAWLERS", "false")
    monkeypatch.setenv("FORUM_HOST_API_KEY", "")

    import app as flask_app

    flask_app = importlib.reload(flask_app)
    with flask_app.app.test_client() as client:
        response = client.get("/api/forum/moderator/status")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["moderator"]["risk_level"]
    assert payload["moderator"]["action"]
