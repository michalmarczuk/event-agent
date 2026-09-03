import json
from types import SimpleNamespace
from unittest.mock import patch

import src.agent as agent

from src.agent import available_tools, execute_tool


def test_execute_tool_dispatches_to_registered_tool():
    captured = {}

    def fake_tool(name: str, count: int):
        captured["name"] = name
        captured["count"] = count
        return {"status": "ok", "name": name, "count": count}

    available_tools["fake_tool"] = fake_tool

    try:
        result = execute_tool("fake_tool", {"name": "demo", "count": 3})
    finally:
        del available_tools["fake_tool"]

    assert captured == {"name": "demo", "count": 3}
    assert result == {"status": "ok", "name": "demo", "count": 3}


def test_run_agent_handles_tool_call_without_real_openai_api():
    first_response = SimpleNamespace(
        id="response-1",
        output=[
            SimpleNamespace(
                type="function_call",
                name="search_events",
                arguments=json.dumps({"city": "Tychy", "days_ahead": 30}),
                call_id="call-1",
            )
        ],
    )
    second_response = SimpleNamespace(
        id="response-2",
        output=[],
        output_text="Found events in Tychy",
    )

    with (
        patch.object(
            agent.client.responses,
            "create",
            side_effect=[first_response, second_response],
        ) as create,
        patch.object(agent, "execute_tool", return_value=[{"name": "Concert"}]) as execute_tool_mock,
    ):
        result = agent.run_agent("Find events in Tychy")

    execute_tool_mock.assert_called_once_with(
        "search_events", {"city": "Tychy", "days_ahead": 30}
    )
    assert create.call_count == 2
    assert result == "Found events in Tychy"


def test_run_agent_returns_tool_error_to_model_and_continues():
    first_response = SimpleNamespace(
        id="response-1",
        output=[
            SimpleNamespace(
                type="function_call",
                name="search_events",
                arguments=json.dumps({"city": "Tychy", "days_ahead": 30}),
                call_id="call-1",
            )
        ],
    )
    second_response = SimpleNamespace(
        id="response-2",
        output=[],
        output_text="I could not find events right now",
    )

    with (
        patch.object(
            agent.client.responses,
            "create",
            side_effect=[first_response, second_response],
        ) as create,
        patch.object(
            agent,
            "execute_tool",
            side_effect=RuntimeError("Ticketmaster unavailable"),
        ),
    ):
        result = agent.run_agent("Find events in Tychy")

    assert create.call_count == 2
    error_output = create.call_args_list[1].kwargs["input"]
    assert error_output == [
        {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": json.dumps(
                {"error": True, "message": "Ticketmaster unavailable"}
            ),
        }
    ]
    assert result == "I could not find events right now"
