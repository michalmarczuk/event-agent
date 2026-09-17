import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

import src.agent as agent
from src.config import SearchLocation, Settings
from src.models import Admission, Event, EventDetails, Recommendation
from src.tools.ticketmaster import TicketmasterClient


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


def test_ticketmaster_http_failure_does_not_expose_api_key_to_model_or_logs(
    caplog,
):
    api_key = "ticketmaster-secret-key"
    response = requests.Response()
    response.status_code = 503
    response.url = (
        "https://app.ticketmaster.com/discovery/v2/events.json"
        f"?apikey={api_key}"
    )
    tool_call = _tool_response(
        "response-1",
        "search_events",
        "call-1",
        days_ahead=30,
    ).output[0]
    tool_handlers = {
        "search_events": TicketmasterClient(
            api_key,
            SearchLocation("Tychy", "u2y0test", 50),
        ).search_events,
    }

    caplog.set_level("INFO")
    with patch("src.tools.ticketmaster.requests.get", return_value=response):
        result = agent._execute_tool_call(
            tool_handlers,
            tool_call,
            seen_event_ids=set(),
            known_event_admissions={},
        )

    model_output = agent._build_function_call_output(tool_call, result)
    assert json.loads(model_output["output"]) == {
        "error": True,
        "message": "Ticketmaster request failed (HTTP 503)",
    }
    assert api_key not in model_output["output"]
    assert "Tool execution failed tool=search_events" in caplog.text
    assert api_key not in caplog.text


def test_canceled_search_event_is_not_model_visible_or_grounded():
    tool_call = _tool_response(
        "response-1", "search_events", "call-1", days_ahead=30
    ).output[0]
    ticketmaster_client = TicketmasterClient(
        "ticketmaster-test-key",
        SearchLocation("Tychy", "u2y0test", 50),
    )
    data = {
        "_embedded": {
            "events": [
                {
                    "id": "canceled-event",
                    "name": "Canceled concert",
                    "dates": {"status": {"code": "canceled"}},
                },
                {
                    "id": "active-event",
                    "name": "Active concert",
                    "dates": {"status": {"code": "onsale"}},
                },
            ]
        }
    }
    known_event_admissions = {}

    with patch("src.tools.ticketmaster._get_ticketmaster_data", return_value=data):
        result = agent._execute_tool_call(
            {"search_events": ticketmaster_client.search_events},
            tool_call,
            seen_event_ids=set(),
            known_event_admissions=known_event_admissions,
        )

    model_output = agent._build_function_call_output(tool_call, result)
    assert [event["id"] for event in json.loads(model_output["output"])] == [
        "active-event"
    ]
    assert set(known_event_admissions) == {"active-event"}
    with pytest.raises(ValueError, match="unknown event ID"):
        agent._parse_recommendations(
            json.dumps(
                {
                    "recommendations": [
                        _BASE_RECOMMENDATION | {"event_id": "canceled-event"}
                    ]
                }
            ),
            known_event_admissions,
        )


def test_model_visible_search_is_capped_after_skipping_seen_first_page():
    tool_call = _tool_response(
        "response-1", "search_events", "call-1", days_ahead=30
    ).output[0]
    client = TicketmasterClient(
        "ticketmaster-test-key", SearchLocation("Tychy", "u2y0test", 50)
    )
    seen_ids = {f"seen-{index}" for index in range(10)}
    data = [
        {
            "page": {"number": page_number, "totalPages": 3},
            "_embedded": {
                "events": [
                    {"id": event_id, "name": f"Concert {event_id}"}
                    for event_id in event_ids
                ]
            },
        }
        for page_number, event_ids in enumerate(
            (sorted(seen_ids), [f"new-{index}" for index in range(10)])
        )
    ]
    known_event_admissions = {}

    with patch(
        "src.tools.ticketmaster._get_ticketmaster_data", side_effect=data
    ) as get:
        result = agent._execute_tool_call(
            {"search_events": client.search_events},
            tool_call,
            seen_event_ids=seen_ids,
            known_event_admissions=known_event_admissions,
        )

    model_visible = json.loads(
        agent._build_function_call_output(tool_call, result)["output"]
    )
    assert get.call_count == 2
    assert len(model_visible) == 10
    assert [event["id"] for event in model_visible] == [
        f"new-{index}" for index in range(10)
    ]
    assert set(known_event_admissions) == {
        f"new-{index}" for index in range(10)
    }


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


def test_canceled_event_details_do_not_ground_event_id():
    tool_call = _tool_response(
        "response-1", "get_event_details", "call-1", event_id="canceled-event"
    ).output[0]
    ticketmaster_client = TicketmasterClient(
        "ticketmaster-test-key",
        SearchLocation("Tychy", "u2y0test", 50),
    )
    data = {
        "id": "canceled-event",
        "name": "Canceled concert",
        "dates": {"status": {"code": "canceled"}},
    }
    known_event_admissions = {}

    with patch("src.tools.ticketmaster._get_ticketmaster_data", return_value=data):
        result = agent._execute_tool_call(
            {"get_event_details": ticketmaster_client.get_event_details},
            tool_call,
            seen_event_ids=set(),
            known_event_admissions=known_event_admissions,
        )

    assert result["error"] is True
    assert known_event_admissions == {}
    with pytest.raises(ValueError, match="unknown event ID"):
        agent._parse_recommendations(
            json.dumps(
                {
                    "recommendations": [
                        _BASE_RECOMMENDATION | {"event_id": "canceled-event"}
                    ]
                }
            ),
            known_event_admissions,
        )


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
