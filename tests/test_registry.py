from types import SimpleNamespace

import pytest

from src.tools.registry import (
    create_tool_handlers,
    execute_tool,
    get_tool_definitions,
)


def test_every_tool_definition_has_a_matching_handler():
    client = SimpleNamespace(
        search_events=lambda city, days_ahead: [],
        get_event_details=lambda event_id: None,
    )

    handlers = create_tool_handlers(client)

    assert {definition["name"] for definition in get_tool_definitions()} == set(handlers)


def test_execute_tool_rejects_unknown_tool_name():
    with pytest.raises(ValueError, match="Unknown tool: missing_tool"):
        execute_tool({}, "missing_tool", {})


def test_execute_tool_forwards_arguments_to_handler():
    captured = {}

    def fake_tool(city, days_ahead):
        captured.update(city=city, days_ahead=days_ahead)
        return "result"

    result = execute_tool(
        {"search_events": fake_tool},
        "search_events",
        {"city": "Tychy", "days_ahead": 30},
    )

    assert captured == {"city": "Tychy", "days_ahead": 30}
    assert result == "result"
