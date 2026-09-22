import json
from unittest.mock import patch

import pytest
import requests

import src.agent as agent
from src.config import SearchLocation
from src.event_catalog import EventCatalog
from src.models import Admission, Event
from src.tools.ticketmaster import TicketmasterClient
from tests.support.agent_support import _BASE_RECOMMENDATION, _tool_response


class _EventSource:
    def __init__(self, source, events):
        self.source = source
        self._events = events

    def search_events(self, city, days_ahead, seen_event_ids=None):
        return self._events


def test_mixed_source_search_grounds_selected_provider_metadata():
    ticketmaster_event = Event(
        "ticketmaster:abc123",
        "Ticketmaster Concert",
        "2026-09-10",
        "Tychy",
        "Ticketmaster Arena",
        "https://www.ticketmaster.pl/event/abc123",
        "ticketmaster",
        "abc123",
        Admission(False, 40, 60, "PLN"),
    )
    duplicate_mosir_event = Event(
        "mosir_tychy:1836",
        "ticketmaster concert",
        "2026-09-10",
        "Tychy",
        "Ticketmaster Arena",
        "https://mosir.tychy.pl/1836-duplicate-concert",
        "mosir_tychy",
        "1836",
        None,
    )
    unique_mosir_event = Event(
        "mosir_tychy:1837",
        "MOSiR Concert",
        "2026-09-10",
        "Tychy",
        "Stadion Zimowy",
        "https://mosir.tychy.pl/1837-mosir-concert",
        "mosir_tychy",
        "1837",
        None,
    )
    catalog = EventCatalog(
        [
            _EventSource("ticketmaster", [ticketmaster_event]),
            _EventSource(
                "mosir_tychy",
                [duplicate_mosir_event, unique_mosir_event],
            ),
        ]
    )
    tool_call = _tool_response(
        "response-1", "search_events", "call-1", days_ahead=30
    ).output[0]
    known_events = {}

    result = agent._execute_tool_call(
        {"search_events": lambda days_ahead, seen_event_ids: catalog.search_events(
            "Tychy", days_ahead, seen_event_ids
        )},
        tool_call,
        seen_event_ids=set(),
        known_events=known_events,
    )
    recommendations = agent._parse_recommendations(
        json.dumps(
            {
                "recommendations": [
                    _BASE_RECOMMENDATION | {"event_id": "ticketmaster:abc123"},
                    _BASE_RECOMMENDATION | {"event_id": "mosir_tychy:1837"},
                ]
            }
        ),
        known_events,
    )

    assert [event["id"] for event in result] == [
        "ticketmaster:abc123",
        "mosir_tychy:1837",
    ]
    assert "admission" not in result[0]
    assert [recommendation.event_id for recommendation in recommendations] == [
        "ticketmaster:abc123",
        "mosir_tychy:1837",
    ]
    assert recommendations[0].source == "ticketmaster"
    assert recommendations[0].url == "https://www.ticketmaster.pl/event/abc123"
    assert recommendations[0].admission == Admission(False, 40, 60, "PLN")
    assert recommendations[1].source == "mosir_tychy"
    assert recommendations[1].url == "https://mosir.tychy.pl/1837-mosir-concert"
    assert recommendations[1].admission is None


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
            known_events={},
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
    known_events = {}

    with patch("src.tools.ticketmaster._get_ticketmaster_data", return_value=data):
        result = agent._execute_tool_call(
            {"search_events": ticketmaster_client.search_events},
            tool_call,
            seen_event_ids=set(),
            known_events=known_events,
        )

    model_output = agent._build_function_call_output(tool_call, result)
    assert [event["id"] for event in json.loads(model_output["output"])] == [
        "ticketmaster:active-event"
    ]
    assert set(known_events) == {"ticketmaster:active-event"}
    with pytest.raises(ValueError, match="unknown event ID"):
        agent._parse_recommendations(
            json.dumps(
                {
                    "recommendations": [
                        _BASE_RECOMMENDATION | {
                            "event_id": "ticketmaster:canceled-event"
                        }
                    ]
                }
            ),
            known_events,
        )


def test_model_visible_search_is_capped_after_skipping_seen_first_page():
    tool_call = _tool_response(
        "response-1", "search_events", "call-1", days_ahead=30
    ).output[0]
    client = TicketmasterClient(
        "ticketmaster-test-key", SearchLocation("Tychy", "u2y0test", 50)
    )
    seen_ids = {f"ticketmaster:seen-{index}" for index in range(10)}
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
            (
                [f"seen-{index}" for index in range(10)],
                [f"new-{index}" for index in range(10)],
            )
        )
    ]
    known_events = {}

    with patch(
        "src.tools.ticketmaster._get_ticketmaster_data", side_effect=data
    ) as get:
        result = agent._execute_tool_call(
            {"search_events": client.search_events},
            tool_call,
            seen_event_ids=seen_ids,
            known_events=known_events,
        )

    model_visible = json.loads(
        agent._build_function_call_output(tool_call, result)["output"]
    )
    assert get.call_count == 2
    assert len(model_visible) == 10
    assert [event["id"] for event in model_visible] == [
        f"ticketmaster:new-{index}" for index in range(10)
    ]
    assert set(known_events) == {
        f"ticketmaster:new-{index}" for index in range(10)
    }


def test_canceled_event_details_do_not_ground_event_id():
    tool_call = _tool_response(
        "response-1", "get_event_details", "call-1",
        event_id="ticketmaster:canceled-event",
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
    known_events = {}

    with patch("src.tools.ticketmaster._get_ticketmaster_data", return_value=data):
        result = agent._execute_tool_call(
            {"get_event_details": ticketmaster_client.get_event_details},
            tool_call,
            seen_event_ids=set(),
            known_events=known_events,
        )

    assert result["error"] is True
    assert known_events == {}
    with pytest.raises(ValueError, match="unknown event ID"):
        agent._parse_recommendations(
            json.dumps(
                {
                    "recommendations": [
                        _BASE_RECOMMENDATION | {
                            "event_id": "ticketmaster:canceled-event"
                        }
                    ]
                }
            ),
            known_events,
        )
