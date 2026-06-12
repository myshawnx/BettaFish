import importlib
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


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


def test_langgraph_agent_factories_are_exposed():
    from InsightEngine.langgraph_agent import create_langgraph_agent as create_insight_agent
    from MediaEngine.langgraph_agent import create_langgraph_agent as create_media_agent
    from QueryEngine.langgraph_agent import create_langgraph_agent as create_query_agent

    assert callable(create_insight_agent)
    assert callable(create_media_agent)
    assert callable(create_query_agent)
