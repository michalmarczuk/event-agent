from types import SimpleNamespace

import pytest

from src.tools.registry import (
    create_tool_handlers,
    execute_tool,
    get_tool_definitions,
)


def test_every_tool_definition_has_a_matching_handler():
    client = SimpleNamespace(
        search_events=lambda days_ahead: [],
        get_event_details=lambda event_id: None,
    )

    handlers = create_tool_handlers(client)

    assert {definition["name"] for definition in get_tool_definitions()} == set(handlers)


def test_search_events_schema_uses_only_days_ahead():
    search_definition = next(
        definition
        for definition in get_tool_definitions()
        if definition["name"] == "search_events"
    )

    assert search_definition["parameters"]["required"] == ["days_ahead"]
    assert search_definition["parameters"]["properties"] == {
        "days_ahead": {
            "type": "integer",
            "description": "Liczba dni do przodu od bieżącego czasu.",
        }
    }


def test_execute_tool_rejects_unknown_tool_name():
    with pytest.raises(ValueError, match="Unknown tool: missing_tool"):
        execute_tool({}, "missing_tool", {})


def test_execute_tool_forwards_arguments_to_handler():
    captured = {}

    def fake_tool(days_ahead):
        captured.update(days_ahead=days_ahead)
        return "result"

    result = execute_tool(
        {"search_events": fake_tool},
        "search_events",
        {"days_ahead": 30},
    )

    assert captured == {"days_ahead": 30}
    assert result == "result"
