import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import src.agent as agent
from src.config import SearchLocation, Settings
from src.models import Admission, Event, EventDetails
from src.telegram_formatter import format_telegram_message

from src.tools.registry import execute_tool


TEST_SETTINGS = Settings(
    openai_api_key="openai-test-key",
    ticketmaster_api_key="ticketmaster-test-key",
    telegram_bot_token="telegram-test-token",
    telegram_chat_id="telegram-test-chat",
    model="test-model",
    search_location=SearchLocation("Tychy", "u2y0test", 50),
)


def _recommendation_payload(event_id):
    return {
        "event_id": event_id,
        "name": "Concert",
        "category": "music",
        "date": None,
        "time": None,
        "city": "Tychy",
        "venue": None,
        "reason": "A strong local pick.",
        "url": None,
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
                    _recommendation_payload(event_id) for event_id in event_ids
                ]
            }
        ),
    )


def _run_with_tool_results(responses, tool_results):
    with (
        patch.object(agent, "load_settings", return_value=TEST_SETTINGS),
        patch.object(agent, "OpenAI") as create_client,
        patch.object(agent, "execute_tool", side_effect=tool_results),
    ):
        create = create_client.return_value.responses.create
        create.side_effect = responses
        result = agent.run_agent("Find events")

    return result, create


def test_parse_recommendations_returns_dataclasses():
    recommendations = agent._parse_recommendations(
        json.dumps(
            {
                "recommendations": [
                    {
                        "event_id": "event-1",
                        "name": "Concert",
                        "category": "music",
                        "date": "2026-09-10",
                        "time": "19:00",
                        "city": "Tychy",
                        "venue": "Town Hall",
                        "reason": "A local concert.",
                        "url": "https://example.test/concert",
                    }
                ]
            }
        ),
        {"event-1": None},
    )

    assert recommendations[0].name == "Concert"
    assert recommendations[0].category == "music"


@pytest.mark.parametrize(
    ("admission", "expected"),
    [
        (Admission(False, 40, 40, "PLN"), Admission(False, 40, 40, "PLN")),
        (Admission(False, 40, 60, "PLN"), Admission(False, 40, 60, "PLN")),
        (None, None),
    ],
)
def test_parse_recommendations_uses_source_admission(admission, expected):
    recommendations = agent._parse_recommendations(
        json.dumps(
            {
                "recommendations": [
                    {
                        "event_id": "event-1",
                        "name": "Concert",
                        "category": "music",
                        "date": None,
                        "time": None,
                        "city": None,
                        "venue": None,
                        "reason": "A local concert.",
                        "url": None,
                    }
                ]
            }
        ),
        {"event-1": admission},
    )

    assert recommendations[0].admission == expected


def test_parse_recommendations_formats_source_admission():
    recommendations = agent._parse_recommendations(
        json.dumps(
            {
                "recommendations": [
                    {
                        "event_id": "event-1",
                        "name": "Concert",
                        "category": "music",
                        "date": None,
                        "time": None,
                        "city": None,
                        "venue": None,
                        "reason": "A local concert.",
                        "url": None,
                    }
                ]
            }
        ),
        {"event-1": Admission(False, 40, 40, "PLN")},
    )

    message = format_telegram_message(recommendations, "Tychy", 50, 30)

    assert "🎟 40 zł" in message


def test_parse_recommendations_rejects_more_than_seven():
    recommendation = {
        "event_id": "event-1",
        "name": "Concert",
        "category": "music",
        "date": None,
        "time": None,
        "city": None,
        "venue": None,
        "reason": "A local concert.",
        "url": None,
    }

    with pytest.raises(ValueError, match="more than 7"):
        agent._parse_recommendations(
            json.dumps({"recommendations": [recommendation] * 8}),
            {"event-1": None},
        )


def test_execute_tool_dispatches_to_registered_tool():
    captured = {}

    def fake_tool(name: str, count: int):
        captured["name"] = name
        captured["count"] = count
        return {"status": "ok", "name": name, "count": count}

    result = execute_tool(
        {"fake_tool": fake_tool},
        "fake_tool",
        {"name": "demo", "count": 3},
    )

    assert captured == {"name": "demo", "count": 3}
    assert result == {"status": "ok", "name": "demo", "count": 3}


def test_run_agent_handles_tool_call_without_real_openai_api():
    first_response = SimpleNamespace(
        id="response-1",
        output=[
            SimpleNamespace(
                type="function_call",
                name="search_events",
                arguments=json.dumps({"days_ahead": 30}),
                call_id="call-1",
            )
        ],
    )
    second_response = SimpleNamespace(
        id="response-2",
        output=[],
        output_text=json.dumps({"recommendations": []}),
    )

    with (
        patch.object(agent, "load_settings", return_value=TEST_SETTINGS),
        patch.object(
            agent,
            "OpenAI",
        ) as create_client,
        patch.object(
            agent,
            "execute_tool",
            return_value=[Event("event-1", "Concert", None, None, None, None, "test")],
        ) as execute_tool_mock,
    ):
        create = create_client.return_value.responses.create
        create.side_effect = [first_response, second_response]
        result = agent.run_agent("Find events in Tychy")

    execute_tool_mock.assert_called_once()
    assert execute_tool_mock.call_args.args[1:] == (
        "search_events",
        {"days_ahead": 30},
    )
    assert create.call_count == 2
    assert create.call_args_list[0].kwargs["text"] == agent.RESPONSE_FORMAT
    continuation_call = create.call_args_list[1]
    assert continuation_call.kwargs["instructions"] == agent.AGENT_INSTRUCTIONS
    assert continuation_call.kwargs["tools"] == agent.get_tool_definitions()
    assert continuation_call.kwargs["text"] == agent.RESPONSE_FORMAT
    assert continuation_call.kwargs["previous_response_id"] == first_response.id
    assert result.recommendations == []
    assert result.recommended_event_ids == set()


def test_run_agent_returns_tool_error_to_model_and_continues():
    first_response = SimpleNamespace(
        id="response-1",
        output=[
            SimpleNamespace(
                type="function_call",
                name="search_events",
                arguments=json.dumps({"days_ahead": 30}),
                call_id="call-1",
            )
        ],
    )
    second_response = SimpleNamespace(
        id="response-2",
        output=[],
        output_text=json.dumps({"recommendations": []}),
    )

    with (
        patch.object(agent, "load_settings", return_value=TEST_SETTINGS),
        patch.object(
            agent,
            "OpenAI",
        ) as create_client,
        patch.object(
            agent,
            "execute_tool",
            side_effect=RuntimeError("Ticketmaster unavailable"),
        ),
    ):
        create = create_client.return_value.responses.create
        create.side_effect = [first_response, second_response]
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
    assert result.recommendations == []
    assert result.recommended_event_ids == set()


def test_run_agent_rejects_unknown_recommendation_id():
    with pytest.raises(ValueError, match="unknown event ID"):
        _run_with_tool_results([_final_response("unknown")], [])


def test_run_agent_preserves_admission_from_search_result():
    admission = Admission(False, 40, 60, "PLN")
    event = Event(
        "event-1",
        "Concert",
        None,
        "Tychy",
        None,
        None,
        "test",
        admission,
    )

    result, create = _run_with_tool_results(
        [
            _tool_response("response-1", "search_events", "call-1", days_ahead=30),
            _final_response("event-1"),
        ],
        [[event]],
    )

    tool_output = json.loads(create.call_args_list[1].kwargs["input"][0]["output"])
    assert tool_output[0]["admission"] == {
        "is_free": False,
        "price_min": 40,
        "price_max": 60,
        "currency": "PLN",
        "note": None,
    }
    assert result.recommendations[0].admission == admission


def test_run_agent_allows_event_returned_by_get_event_details():
    result, _ = _run_with_tool_results(
        [
            _tool_response(
                "response-1",
                "get_event_details",
                "call-1",
                event_id="event-1",
            ),
            _final_response("event-1"),
        ],
        [EventDetails("Concert", None, None, None, "Tychy", None)],
    )

    assert result.recommended_event_ids == {"event-1"}
    assert result.recommendations[0].admission is None


def test_run_agent_get_event_details_preserves_search_admission():
    admission = Admission(False, 40, 60, "PLN")
    event = Event(
        "event-1",
        "Concert",
        None,
        "Tychy",
        None,
        None,
        "test",
        admission,
    )
    details = EventDetails("Concert", None, None, None, "Tychy", None)

    result, _ = _run_with_tool_results(
        [
            _tool_response("response-1", "search_events", "call-1", days_ahead=30),
            _tool_response(
                "response-2",
                "get_event_details",
                "call-2",
                event_id="event-1",
            ),
            _final_response("event-1"),
        ],
        [[event], details],
    )

    assert result.recommendations[0].admission == admission


def test_run_agent_failed_tool_call_does_not_ground_event_id():
    with pytest.raises(ValueError, match="unknown event ID"):
        _run_with_tool_results(
            [
                _tool_response(
                    "response-1",
                    "get_event_details",
                    "call-1",
                    event_id="event-1",
                ),
                _final_response("event-1"),
            ],
            [RuntimeError("Ticketmaster unavailable")],
        )


def test_run_agent_filters_seen_events_and_returns_new_ids():
    first_response = SimpleNamespace(
        id="response-1",
        output=[
            SimpleNamespace(
                type="function_call",
                name="search_events",
                arguments=json.dumps({"days_ahead": 30}),
                call_id="call-1",
            )
        ],
    )
    second_response = SimpleNamespace(
        id="response-2",
        output=[
            SimpleNamespace(
                type="function_call",
                name="search_events",
                arguments=json.dumps({"days_ahead": 30}),
                call_id="call-2",
            )
        ],
    )
    third_response = SimpleNamespace(
        id="response-3",
        output=[],
        output_text=json.dumps({"recommendations": []}),
    )
    seen_event = Event("seen", "Already seen", None, None, None, None, "test")
    new_event = Event("new", "New event", None, None, None, None, "test")
    latest_event = Event("latest", "Latest event", None, None, None, None, "test")

    with (
        patch.object(agent, "load_settings", return_value=TEST_SETTINGS),
        patch.object(
            agent,
            "OpenAI",
        ) as create_client,
        patch.object(
            agent,
            "execute_tool",
            side_effect=[
                [seen_event, new_event],
                [new_event, latest_event],
            ],
        ),
    ):
        create = create_client.return_value.responses.create
        create.side_effect = [first_response, second_response, third_response]
        result = agent.run_agent("Find events in Tychy", {"seen"})

    first_tool_outputs = create.call_args_list[1].kwargs["input"]
    assert json.loads(first_tool_outputs[0]["output"]) == [
        {
            "id": "new",
            "name": "New event",
            "date": None,
            "city": None,
            "venue": None,
            "url": None,
            "source": "test",
            "admission": None,
        }
    ]
    assert "seen" not in first_tool_outputs[0]["output"]

    second_tool_outputs = create.call_args_list[2].kwargs["input"]
    assert json.loads(second_tool_outputs[0]["output"]) == [
        {
            "id": "latest",
            "name": "Latest event",
            "date": None,
            "city": None,
            "venue": None,
            "url": None,
            "source": "test",
            "admission": None,
        }
    ]
    assert "new" not in second_tool_outputs[0]["output"]
    assert result.recommendations == []
    assert result.recommended_event_ids == set()


def test_run_agent_returns_only_recommended_event_ids():
    first_response = SimpleNamespace(
        id="response-1",
        output=[
            SimpleNamespace(
                type="function_call",
                name="search_events",
                arguments=json.dumps({"days_ahead": 30}),
                call_id="call-1",
            )
        ],
    )
    second_response = SimpleNamespace(
        id="response-2",
        output=[],
        output_text=json.dumps(
            {
                "recommendations": [
                    {
                        "event_id": "event-1",
                        "name": "First event",
                        "category": "music",
                        "date": None,
                        "time": None,
                        "city": "Tychy",
                        "venue": None,
                        "reason": "A strong local pick.",
                        "url": None,
                    },
                    {
                        "event_id": "event-2",
                        "name": "Second event",
                        "category": "culture",
                        "date": None,
                        "time": None,
                        "city": "Tychy",
                        "venue": None,
                        "reason": "A distinctive cultural event.",
                        "url": None,
                    },
                ]
            }
        ),
    )
    events = [
        Event("event-1", "First event", None, "Tychy", None, None, "test"),
        Event("event-2", "Second event", None, "Tychy", None, None, "test"),
        Event("event-3", "Third event", None, "Tychy", None, None, "test"),
    ]

    with (
        patch.object(agent, "load_settings", return_value=TEST_SETTINGS),
        patch.object(agent, "OpenAI") as create_client,
        patch.object(agent, "execute_tool", return_value=events),
    ):
        create = create_client.return_value.responses.create
        create.side_effect = [first_response, second_response]
        result = agent.run_agent("Find events", set())

    assert result.recommended_event_ids == {"event-1", "event-2"}
    assert not hasattr(result, "discovered_event_ids")
