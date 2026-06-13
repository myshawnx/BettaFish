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


class FailedTavilyAgency:
    def basic_search_news(self, query, max_results=7):
        from QueryEngine.tools import TavilyResponse

        return TavilyResponse(query="搜索失败")


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


def test_query_search_failure_placeholder_raises_for_recovery():
    from QueryEngine.langgraph_agent import LangGraphQueryAgent

    agent = object.__new__(LangGraphQueryAgent)
    agent.search_agency = FailedTavilyAgency()

    with pytest.raises(RuntimeError, match="Tavily API"):
        agent._execute_search_tool("basic_search_news", "topic", {})


def test_data_inspection_error_is_not_retryable():
    from utils.retry_helper import _is_non_retryable_exception, is_recoverable_api_error

    assert _is_non_retryable_exception(Exception("DataInspectionFailed: content rejected"))
    assert _is_non_retryable_exception(Exception("insufficient_quota: quota exhausted"))
    assert is_recoverable_api_error(Exception("AuthenticationError: invalid API key"))
    assert not is_recoverable_api_error(Exception("GraphRecursionError: recursion limit reached"))


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


@pytest.mark.parametrize(("agent_module_name", "state_module_name", "agent_class_name"), LANGGRAPH_ENGINES)
def test_langgraph_error_update_forces_current_paragraph_to_converge(
    agent_module_name,
    state_module_name,
    agent_class_name,
):
    agent_module = importlib.import_module(agent_module_name)
    state_module = importlib.import_module(state_module_name)
    agent = object.__new__(getattr(agent_module, agent_class_name))

    state = state_module.create_initial_state("topic", max_reflections=2, max_paragraphs=2)
    state["paragraphs"] = [
        {"title": "First section", "content": "First section scope", "latest_summary": ""},
        {"title": "Second section", "content": "Second section scope", "latest_summary": ""},
    ]
    state["current_paragraph_index"] = 0
    state["current_reflection_count"] = 0

    update = agent._terminal_error_update(state, "反思段落1失败: timeout")

    assert update["current_reflection_count"] == state["max_reflections"]
    assert "current_summary" in update
    assert update["paragraphs"][0]["latest_summary"] == update["current_summary"]

    state_after_error = {
        **state,
        **{key: value for key, value in update.items() if key not in {"errors", "messages"}},
    }
    state_after_error["errors"] = state["errors"] + update.get("errors", [])
    state_after_error["messages"] = state["messages"] + update.get("messages", [])

    assert agent._should_continue_reflection(state_after_error) == "next_paragraph"


@pytest.mark.parametrize(("agent_module_name", "_state_module_name", "agent_class_name"), LANGGRAPH_ENGINES)
def test_langgraph_recursion_limit_scales_with_configured_paragraphs(
    agent_module_name,
    _state_module_name,
    agent_class_name,
):
    agent_module = importlib.import_module(agent_module_name)
    agent_class = getattr(agent_module, agent_class_name)

    assert agent_class._calculate_recursion_limit(max_reflections=2, max_paragraphs=20) > 130
    assert agent_class._calculate_recursion_limit(max_reflections=2, max_paragraphs=5) >= 200


@pytest.mark.parametrize("formatting_module_name", FORMATTING_NODES)
def test_report_formatting_passes_max_tokens(monkeypatch, formatting_module_name):
    monkeypatch.setenv("REPORT_FORMATTING_MAX_TOKENS", "123")
    formatting_module = importlib.import_module(formatting_module_name)
    llm = DummyFormattingLLM()
    node = formatting_module.ReportFormattingNode(llm)

    report = node.run([{"title": "Section", "paragraph_latest_state": "Evidence"}])

    assert report.startswith("# OK")
    assert llm.kwargs["max_tokens"] == 123
