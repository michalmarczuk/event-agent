import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import src.agent as agent
from src.config import SearchLocation, Settings
from src.models import Admission, Event, EventDetails, Recommendation


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


def test_parse_recommendations_returns_recommendation_model():
    payload = _BASE_RECOMMENDATION | {
        "event_id": "event-1",
        "category": "culture",
        "date": "2026-09-10",
        "time": "19:00",
        "venue": "Town Hall",
        "reason": "A local concert.",
        "url": "https://example.test/concert",
    }

    recommendations = agent._parse_recommendations(
        json.dumps({"recommendations": [payload]}),
        {"event-1": None},
    )

    assert isinstance(recommendations[0], Recommendation)
    assert recommendations[0].name == "Concert"
    assert recommendations[0].category == "culture"
    assert recommendations[0].date == "2026-09-10"


@pytest.mark.parametrize(
    "admission",
    [Admission(False, 40, 60, "PLN"), None],
)
def test_parse_recommendations_uses_source_admission(admission):
    recommendations = agent._parse_recommendations(
        json.dumps(
            {
                "recommendations": [
                    _BASE_RECOMMENDATION | {"event_id": "event-1"}
                ]
            }
        ),
        {"event-1": admission},
    )

    assert recommendations[0].admission == admission


def test_parse_recommendations_rejects_more_than_seven():
    recommendation = _BASE_RECOMMENDATION | {"event_id": "event-1"}

    with pytest.raises(ValueError, match="more than 7"):
        agent._parse_recommendations(
            json.dumps({"recommendations": [recommendation] * 8}),
            {"event-1": None},
        )


def test_run_agent_dispatches_search_and_preserves_source_admission():
    admission = Admission(False, 40, 60, "PLN")
    event = Event(
        "event-1", "Concert", None, "Tychy", None, None, "test", admission
    )
    first_response = _tool_response(
        "response-1",
        "search_events",
        "call-1",
        days_ahead=30,
    )

    result, create, execute_tool_mock = _run_with_tool_results(
        [first_response, _final_response("event-1")],
        [[event]],
    )

    execute_tool_mock.assert_called_once()
    assert execute_tool_mock.call_args.args[1:] == (
        "search_events",
        {"days_ahead": 30},
    )
    assert create.call_count == 2
    for response_call in create.call_args_list:
        assert response_call.kwargs["instructions"] == agent.AGENT_INSTRUCTIONS
        assert response_call.kwargs["tools"] == agent.get_tool_definitions()
        assert response_call.kwargs["text"] == agent.RESPONSE_FORMAT

    continuation_call = create.call_args_list[1]
    assert continuation_call.kwargs["model"] == TEST_SETTINGS.model
    assert continuation_call.kwargs["previous_response_id"] == first_response.id
    tool_output = json.loads(continuation_call.kwargs["input"][0]["output"])
    assert tool_output == [asdict(event)]

    recommendation = result.recommendations[0]
    assert isinstance(recommendation, Recommendation)
    assert recommendation.event_id == "event-1"
    assert recommendation.admission == admission


def test_run_agent_returns_tool_error_to_model_and_continues():
    result, create, _ = _run_with_tool_results(
        [
            _tool_response("response-1", "search_events", "call-1", days_ahead=30),
            _final_response(),
        ],
        [RuntimeError("Ticketmaster unavailable")],
    )

    assert create.call_count == 2
    assert create.call_args_list[1].kwargs["input"] == [
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


def test_run_agent_allows_event_returned_by_get_event_details():
    result, _, _ = _run_with_tool_results(
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
        "event-1", "Concert", None, "Tychy", None, None, "test", admission
    )

    result, _, _ = _run_with_tool_results(
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
        [
            [event],
            EventDetails("Concert", None, None, None, "Tychy", None),
        ],
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


def test_run_agent_filters_seen_and_same_run_events():
    seen_event = Event("seen", "Already seen", None, None, None, None, "test")
    new_event = Event("new", "New event", None, None, None, None, "test")
    latest_event = Event("latest", "Latest event", None, None, None, None, "test")

    result, create, _ = _run_with_tool_results(
        [
            _tool_response("response-1", "search_events", "call-1", days_ahead=30),
            _tool_response("response-2", "search_events", "call-2", days_ahead=30),
            _final_response(),
        ],
        [
            [seen_event, new_event],
            [new_event, latest_event],
        ],
        seen_event_ids={"seen"},
    )

    first_output = json.loads(create.call_args_list[1].kwargs["input"][0]["output"])
    second_output = json.loads(create.call_args_list[2].kwargs["input"][0]["output"])
    assert first_output == [asdict(new_event)]
    assert second_output == [asdict(latest_event)]
    assert result.recommendations == []
    assert result.recommended_event_ids == set()


def test_run_agent_returns_only_recommended_event_ids():
    events = [
        Event("event-1", "First event", None, "Tychy", None, None, "test"),
        Event("event-2", "Second event", None, "Tychy", None, None, "test"),
        Event("event-3", "Third event", None, "Tychy", None, None, "test"),
    ]

    result, _, _ = _run_with_tool_results(
        [
            _tool_response("response-1", "search_events", "call-1", days_ahead=30),
            _final_response("event-1", "event-2"),
        ],
        [events],
    )

    assert result.recommended_event_ids == {"event-1", "event-2"}
    assert not hasattr(result, "discovered_event_ids")
