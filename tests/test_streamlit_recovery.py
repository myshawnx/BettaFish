def test_recoverable_api_error_detection_excludes_graph_recursion():
    from SingleEngineApp.langgraph_recovery import is_recoverable_api_error

    assert is_recoverable_api_error("AuthenticationError: invalid API key")
    assert is_recoverable_api_error("insufficient_quota: quota exhausted")
    assert is_recoverable_api_error("APIConnectionError: failed to connect")
    assert not is_recoverable_api_error("GraphRecursionError: recursion limit reached")


def test_persist_env_updates_preserves_existing_lines(tmp_path):
    from SingleEngineApp.langgraph_recovery import persist_env_updates

    env_path = tmp_path / ".env"
    env_path.write_text("# comment\nQUERY_ENGINE_API_KEY=old\nOTHER=value\n", encoding="utf-8")

    result = persist_env_updates(
        {
            "QUERY_ENGINE_API_KEY": "new-key",
            "QUERY_ENGINE_BASE_URL": "https://example.com/v1",
            "EMPTY_VALUE": "",
        },
        env_path=env_path,
    )

    assert result == env_path
    text = env_path.read_text(encoding="utf-8")
    assert "# comment" in text
    assert "QUERY_ENGINE_API_KEY=new-key" in text
    assert "OTHER=value" in text
    assert "QUERY_ENGINE_BASE_URL=https://example.com/v1" in text
    assert "EMPTY_VALUE" not in text


def test_form_value_merge_allows_blank_secret_to_keep_current_value():
    from SingleEngineApp.langgraph_recovery import merge_form_values, missing_required_fields

    fields = [
        {"key": "QUERY_ENGINE_API_KEY", "label": "LLM Key", "value": "existing", "required": True},
        {"key": "TAVILY_API_KEY", "label": "Tavily", "value": None, "required": True},
    ]
    merged = merge_form_values(fields, {"QUERY_ENGINE_API_KEY": "", "TAVILY_API_KEY": "new"})

    assert merged["QUERY_ENGINE_API_KEY"] == "existing"
    assert merged["TAVILY_API_KEY"] == "new"
    assert missing_required_fields(fields, merged) == []
