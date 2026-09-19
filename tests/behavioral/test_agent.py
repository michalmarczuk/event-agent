import json
from dataclasses import asdict
from unittest.mock import patch

import pytest

import src.agent as agent
from src.models import Admission, Event, EventDetails, Recommendation
from tests.support.agent_support import (
    TEST_SETTINGS,
    _final_response,
    _run_with_tool_results,
    _tool_response,
)


def test_run_agent_hides_prices_from_model_and_preserves_source_admission():
    admission = Admission(
        False,
        40.25,
        60.75,
        "TEST-CURRENCY",
        "provider-price-note",
    )
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
        {"days_ahead": 30, "seen_event_ids": set()},
    )
    assert create.call_count == 2
    for response_call in create.call_args_list:
        assert response_call.kwargs["instructions"] == agent.AGENT_INSTRUCTIONS
        assert response_call.kwargs["tools"] == agent.get_tool_definitions()
        assert response_call.kwargs["text"] == agent.RESPONSE_FORMAT

    continuation_call = create.call_args_list[1]
    assert continuation_call.kwargs["model"] == TEST_SETTINGS.model
    assert continuation_call.kwargs["previous_response_id"] == first_response.id
    model_visible_output = continuation_call.kwargs["input"][0]["output"]
    tool_output = json.loads(model_visible_output)
    expected_event = asdict(event)
    del expected_event["admission"]
    assert tool_output == [expected_event]
    for hidden_value in (
        "admission",
        "is_free",
        "price_min",
        "price_max",
        "currency",
        "note",
        "40.25",
        "60.75",
        "TEST-CURRENCY",
        "provider-price-note",
    ):
        assert hidden_value not in model_visible_output

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


def test_model_visible_search_caps_oversized_tool_result_after_filtering():
    tool_call = _tool_response(
        "response-1", "search_events", "call-1", days_ahead=30
    ).output[0]
    events = [
        Event(event_id, event_id, None, None, None, None, "ticketmaster")
        for event_id in ["seen", *(f"new-{index}" for index in range(12))]
    ]
    known_event_admissions = {}

    with patch.object(agent, "execute_tool", return_value=events):
        result = agent._execute_tool_call(
            {},
            tool_call,
            seen_event_ids={"seen"},
            known_event_admissions=known_event_admissions,
        )

    assert [event["id"] for event in result] == [
        f"new-{index}" for index in range(10)
    ]
    assert set(known_event_admissions) == {
        f"new-{index}" for index in range(10)
    }


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

    result, create, execute_tool_mock = _run_with_tool_results(
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
    expected_new_event = asdict(new_event)
    expected_latest_event = asdict(latest_event)
    del expected_new_event["admission"]
    del expected_latest_event["admission"]
    assert first_output == [expected_new_event]
    assert second_output == [expected_latest_event]
    assert execute_tool_mock.call_args_list[0].args[2]["seen_event_ids"] == {
        "seen"
    }
    assert execute_tool_mock.call_args_list[1].args[2]["seen_event_ids"] == {
        "seen", "new"
    }
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
