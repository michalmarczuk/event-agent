import traceback
from unittest.mock import patch

import pytest
from qase.pytest import qase
import requests

from src.config import SearchLocation
from src.tools.ticketmaster import TicketmasterClient


def _discovery_event(event_id, status="onsale"):
    return {
        "id": event_id,
        "name": f"Concert {event_id}",
        "dates": {"status": {"code": status}},
    }


def _discovery_page(number, total_pages, events):
    return {
        "page": {"number": number, "totalPages": total_pages},
        "_embedded": {"events": events},
    }


@qase.id(1)
@pytest.mark.qase
def test_search_events_drops_canceled_event_with_structured_log(caplog):
    data = {
        "_embedded": {
            "events": [
                {
                    "id": "canceled-event",
                    "name": "Canceled concert",
                    "dates": {"status": {"code": "canceled"}},
                }
            ]
        }
    }

    with (
        patch("src.tools.ticketmaster._get_ticketmaster_data", return_value=data),
        caplog.at_level("INFO", logger="src.tools.ticketmaster"),
    ):
        events = TicketmasterClient(
            "ticketmaster-test-key",
            SearchLocation("Tychy", "u2y0test", 50),
        ).search_events(30)

    assert events == []
    dropped_records = [
        record
        for record in caplog.records
        if record.__dict__.get("event.action") == "ticketmaster_event_filter"
    ]
    assert len(dropped_records) == 1
    assert dropped_records[0].__dict__["event.outcome"] == "dropped"
    assert dropped_records[0].__dict__["event.reason"] == "canceled"
    assert dropped_records[0].__dict__["ticketmaster.event_id"] == "canceled-event"


@pytest.mark.parametrize(
    "status",
    [
        pytest.param(
            "onsale",
            marks=(qase.id(10), pytest.mark.qase),
        ),
        "offsale",
        "postponed",
        "rescheduled",
    ],
)
def test_search_events_keeps_non_canceled_statuses(status):
    event_id = f"{status}-event"
    data = {
        "_embedded": {
            "events": [
                {
                    "id": event_id,
                    "name": "Concert",
                    "dates": {"status": {"code": status}},
                }
            ]
        }
    }

    with patch("src.tools.ticketmaster._get_ticketmaster_data", return_value=data):
        events = TicketmasterClient(
            "ticketmaster-test-key",
            SearchLocation("Tychy", "u2y0test", 50),
        ).search_events(30)

    assert [event.id for event in events] == [event_id]


@qase.id(11)
@pytest.mark.qase
def test_search_events_fetches_later_page_after_first_page_is_seen(caplog):
    responses = [
        _discovery_page(0, 2, [_discovery_event(f"seen-{index}") for index in range(10)]),
        _discovery_page(1, 2, [_discovery_event("new-1"), _discovery_event("new-2")]),
    ]
    client = TicketmasterClient(
        "ticketmaster-test-key", SearchLocation("Tychy", "u2y0test", 50)
    )

    with (
        patch("src.tools.ticketmaster._get_ticketmaster_data", side_effect=responses) as get,
        caplog.at_level("INFO", logger="src.tools.ticketmaster"),
    ):
        events = client.search_events(
            30, seen_event_ids={f"seen-{index}" for index in range(10)}
        )

    assert [event.id for event in events] == ["new-1", "new-2"]
    assert [call.args[1]["page"] for call in get.call_args_list] == [0, 1]
    summaries = [
        record for record in caplog.records
        if record.__dict__.get("event.action") == "ticketmaster_event_search"
    ]
    assert len(summaries) == 1
    assert summaries[0].__dict__["events.api_pages_fetched"] == 2
    assert summaries[0].__dict__["events.api_returned"] == 12
    assert summaries[0].__dict__["events.unseen_eligible"] == 2


def test_search_events_stops_after_ten_unseen_on_first_page():
    data = _discovery_page(
        0, 3, [_discovery_event(f"new-{index}") for index in range(10)]
    )
    client = TicketmasterClient(
        "ticketmaster-test-key", SearchLocation("Tychy", "u2y0test", 50)
    )

    with patch("src.tools.ticketmaster._get_ticketmaster_data", return_value=data) as get:
        events = client.search_events(30, seen_event_ids=set())

    assert len(events) == 10
    get.assert_called_once()


def test_search_events_does_not_count_canceled_toward_ten_event_target():
    first_page = [
        _discovery_event(f"new-{index}") for index in range(9)
    ] + [_discovery_event("canceled", "canceled")]
    responses = [
        _discovery_page(0, 2, first_page),
        _discovery_page(1, 2, [_discovery_event("new-9")]),
    ]
    client = TicketmasterClient(
        "ticketmaster-test-key", SearchLocation("Tychy", "u2y0test", 50)
    )

    with patch("src.tools.ticketmaster._get_ticketmaster_data", side_effect=responses) as get:
        events = client.search_events(30, seen_event_ids=set())

    assert [event.id for event in events] == [f"new-{index}" for index in range(10)]
    assert get.call_count == 2


def test_search_events_stops_when_ticketmaster_pages_are_exhausted():
    data = _discovery_page(0, 1, [_discovery_event("seen")])
    client = TicketmasterClient(
        "ticketmaster-test-key", SearchLocation("Tychy", "u2y0test", 50)
    )

    with patch("src.tools.ticketmaster._get_ticketmaster_data", return_value=data) as get:
        events = client.search_events(30, seen_event_ids={"seen"})

    assert events == []
    get.assert_called_once()


def test_search_events_stops_at_five_page_safety_limit():
    responses = [
        _discovery_page(page, 100, [_discovery_event(f"new-{page}")])
        for page in range(5)
    ]
    client = TicketmasterClient(
        "ticketmaster-test-key", SearchLocation("Tychy", "u2y0test", 50)
    )

    with patch("src.tools.ticketmaster._get_ticketmaster_data", side_effect=responses) as get:
        events = client.search_events(30, seen_event_ids=set())

    assert [event.id for event in events] == [f"new-{page}" for page in range(5)]
    assert [call.args[1]["page"] for call in get.call_args_list] == list(range(5))


def test_search_events_sanitizes_http_failure_and_exception_chain():
    api_key = "ticketmaster-secret-key"
    response = requests.Response()
    response.status_code = 503
    response.url = (
        "https://app.ticketmaster.com/discovery/v2/events.json"
        f"?apikey={api_key}"
    )

    with (
        patch("src.tools.ticketmaster.requests.get", return_value=response),
        pytest.raises(
            RuntimeError,
            match=r"Ticketmaster request failed \(HTTP 503\)",
        ) as error,
    ):
        TicketmasterClient(
            api_key,
            SearchLocation("Tychy", "u2y0test", 50),
        ).search_events(30)

    formatted_exception = "".join(traceback.format_exception(error.value))
    assert api_key not in formatted_exception
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
