import importlib
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OPTIONAL_MEDIA_KEY_FIELDS = [
    "INSIGHT_ENGINE_API_KEY",
    "MEDIA_ENGINE_API_KEY",
    "QUERY_ENGINE_API_KEY",
    "REPORT_ENGINE_API_KEY",
    "FORUM_HOST_API_KEY",
    "KEYWORD_OPTIMIZER_API_KEY",
    "TAVILY_API_KEY",
]


def test_langgraph_engine_modules_import():
    modules = [
        "InsightEngine.langgraph_state",
        "InsightEngine.langgraph_agent",
        "MediaEngine.langgraph_state",
        "MediaEngine.langgraph_agent",
        "QueryEngine.langgraph_state",
        "QueryEngine.langgraph_agent",
    ]

    imported = [importlib.import_module(module_name) for module_name in modules]

    assert imported


@pytest.mark.parametrize("field_name", OPTIONAL_MEDIA_KEY_FIELDS)
def test_media_settings_allows_no_key_defaults(monkeypatch, field_name):
    monkeypatch.delenv(field_name, raising=False)
    from MediaEngine.utils.config import Settings

    config = Settings(_env_file=None)

    assert getattr(config, field_name) is None


def test_langgraph_agent_factories_are_exposed():
    from InsightEngine.langgraph_agent import create_langgraph_agent as create_insight_agent
    from MediaEngine.langgraph_agent import create_langgraph_agent as create_media_agent
    from QueryEngine.langgraph_agent import create_langgraph_agent as create_query_agent

    assert callable(create_insight_agent)
    assert callable(create_media_agent)
    assert callable(create_query_agent)
