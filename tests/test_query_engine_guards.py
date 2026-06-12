import sys
import importlib
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


LANGGRAPH_ENGINES = [
    ("InsightEngine.langgraph_agent", "InsightEngine.langgraph_state", "LangGraphInsightAgent"),
    ("MediaEngine.langgraph_agent", "MediaEngine.langgraph_state", "LangGraphMediaAgent"),
    ("QueryEngine.langgraph_agent", "QueryEngine.langgraph_state", "LangGraphQueryAgent"),
]

FORMATTING_NODES = [
    "InsightEngine.nodes.formatting_node",
    "MediaEngine.nodes.formatting_node",
    "QueryEngine.nodes.formatting_node",
]


class DummyStructureNode:
    query = ""

    def run(self):
        return [
            {"title": "First section", "content": "First section scope"},
            {"title": "Second section", "content": "Second section scope"},
        ]


class DummyFormattingLLM:
    def __init__(self):
        self.kwargs = None

    def stream_invoke_to_string(self, system_prompt, user_prompt, **kwargs):
        self.kwargs = kwargs
        return "# OK\n\nFormatted report."


def test_query_search_results_prompt_uses_compact_evidence():
    from QueryEngine.utils.text_processing import format_search_results_for_prompt

    formatted = format_search_results_for_prompt(
        [
            {
                "title": "Policy update",
                "url": "https://example.com/policy",
                "published_date": "2026-06-12",
                "content": "A" * 2000,
                "raw_content": "B" * 10000,
            }
        ],
        max_length=5000,
    )

    assert len(formatted) == 1
    assert "Title: Policy update" in formatted[0]
    assert "URL: https://example.com/policy" in formatted[0]
    assert "Published: 2026-06-12" in formatted[0]
    assert "B" * 100 not in formatted[0]
    assert len(formatted[0]) < 1200


def test_query_add_error_builds_extractive_summary_after_search():
    from QueryEngine.langgraph_state import create_initial_state, add_error

    state = create_initial_state("topic", max_reflections=0, max_paragraphs=1)
    state["paragraphs"] = [{"title": "Evidence section", "content": "brief"}]
    state["current_search_query"] = "policy query"
    state["current_search_results"] = [
        {
            "title": "Result title",
            "url": "https://example.com/result",
            "content": "Useful evidence snippet.",
            "published_date": "2026-06-12",
        }
    ]

    update = add_error(state, "data_inspection_failed")

    assert "current_summary" in update
    assert "extractive evidence fallback" in update["current_summary"]
    assert update["paragraphs"][0]["latest_summary"] == update["current_summary"]


def test_query_add_error_does_not_build_fallback_for_search_errors():
    from QueryEngine.langgraph_state import create_initial_state, add_error

    state = create_initial_state("topic", max_reflections=0, max_paragraphs=1)
    state["paragraphs"] = [{"title": "Evidence section", "content": "brief"}]
    state["current_search_query"] = "policy query"
    state["current_search_results"] = [
        {
            "title": "Stale result",
            "url": "https://example.com/stale",
            "content": "This should not be reused for a search failure.",
        }
    ]

    update = add_error(state, "search paragraph 1 failed: timeout")

    assert "current_summary" not in update
    assert "paragraphs" not in update


def test_data_inspection_error_is_not_retryable():
    from utils.retry_helper import _is_non_retryable_exception

    assert _is_non_retryable_exception(Exception("DataInspectionFailed: content rejected"))


@pytest.mark.parametrize(("agent_module_name", "state_module_name", "agent_class_name"), LANGGRAPH_ENGINES)
def test_langgraph_structure_respects_max_paragraphs(agent_module_name, state_module_name, agent_class_name):
    agent_module = importlib.import_module(agent_module_name)
    state_module = importlib.import_module(state_module_name)
    agent = object.__new__(getattr(agent_module, agent_class_name))
    agent.structure_node_impl = DummyStructureNode()

    state = state_module.create_initial_state("topic", max_reflections=0, max_paragraphs=1)
    update = agent._generate_structure_node(state)

    assert len(update["paragraphs"]) == 1
    assert update["paragraphs"][0]["title"] == "First section"


@pytest.mark.parametrize(("agent_module_name", "state_module_name", "agent_class_name"), LANGGRAPH_ENGINES)
def test_langgraph_router_finishes_at_max_paragraphs(agent_module_name, state_module_name, agent_class_name):
    agent_module = importlib.import_module(agent_module_name)
    state_module = importlib.import_module(state_module_name)
    agent = object.__new__(getattr(agent_module, agent_class_name))

    state = state_module.create_initial_state("topic", max_reflections=0, max_paragraphs=1)
    state["paragraphs"] = [
        {"title": "First section", "content": "First section scope", "latest_summary": "done"},
        {"title": "Second section", "content": "Second section scope", "latest_summary": ""},
    ]
    state["current_paragraph_index"] = 0
    state["current_reflection_count"] = 0

    decision = agent._should_continue_reflection(state)

    assert decision == "finish"


@pytest.mark.parametrize("formatting_module_name", FORMATTING_NODES)
def test_report_formatting_passes_max_tokens(monkeypatch, formatting_module_name):
    monkeypatch.setenv("REPORT_FORMATTING_MAX_TOKENS", "123")
    formatting_module = importlib.import_module(formatting_module_name)
    llm = DummyFormattingLLM()
    node = formatting_module.ReportFormattingNode(llm)

    report = node.run([{"title": "Section", "paragraph_latest_state": "Evidence"}])

    assert report.startswith("# OK")
    assert llm.kwargs["max_tokens"] == 123
