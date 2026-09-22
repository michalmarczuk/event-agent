"""Shared setup for agent tests across taxonomy levels."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import src.agent as agent
from src.config import SearchLocation, Settings

TEST_SETTINGS = Settings(
    openai_api_key="openai-test-key",
    ticketmaster_api_key="ticketmaster-test-key",
    telegram_bot_token="telegram-test-token",
    telegram_chat_id="telegram-test-chat",
    model="test-model",
    search_location=SearchLocation("Tychy", "u2y0test", 50),
)

_BASE_RECOMMENDATION = {
    "name": "Concert",
    "category": "music",
    "date": None,
    "time": None,
    "city": "Tychy",
    "venue": None,
    "reason": "A strong local pick.",
}


def _tool_response(response_id, tool_name, call_id, **arguments):
    return SimpleNamespace(
        id=response_id,
        output=[
            SimpleNamespace(
                type="function_call",
                name=tool_name,
                arguments=json.dumps(arguments),
                call_id=call_id,
            )
        ],
    )


def _final_response(*event_ids):
    return SimpleNamespace(
        id="response-final",
        output=[],
        output_text=json.dumps(
            {
                "recommendations": [
                    _BASE_RECOMMENDATION | {"event_id": event_id}
                    for event_id in event_ids
                ]
            }
        ),
    )


def _run_with_tool_results(
    responses,
    tool_results,
    *,
    seen_event_ids=None,
):
    with (
        patch.object(agent, "load_settings", return_value=TEST_SETTINGS),
        patch.object(agent, "OpenAI") as create_client,
        patch.object(
            agent,
            "execute_tool",
            side_effect=tool_results,
        ) as execute_tool_mock,
    ):
        create = create_client.return_value.responses.create
        create.side_effect = responses
        result = agent.run_agent("Find events", seen_event_ids)

    return result, create, execute_tool_mock
