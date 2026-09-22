import traceback
from unittest.mock import patch

import pytest
import requests

from src.config import SearchLocation
from src.events.models import Admission, Event, EventDetails
from src.integrations.ticketmaster.client import TicketmasterClient


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
        patch("src.integrations.ticketmaster.client._get_ticketmaster_data", return_value=data),
        caplog.at_level("INFO", logger="src.integrations.ticketmaster.client"),
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
        "onsale",
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

    with patch("src.integrations.ticketmaster.client._get_ticketmaster_data", return_value=data):
        events = TicketmasterClient(
            "ticketmaster-test-key",
            SearchLocation("Tychy", "u2y0test", 50),
        ).search_events(30)

    assert [event.id for event in events] == [f"ticketmaster:{event_id}"]
    assert [event.source_event_id for event in events] == [event_id]


def test_search_events_fetches_later_page_after_first_page_is_seen(caplog):
    responses = [
        _discovery_page(0, 2, [_discovery_event(f"seen-{index}") for index in range(10)]),
        _discovery_page(1, 2, [_discovery_event("new-1"), _discovery_event("new-2")]),
    ]
    client = TicketmasterClient(
        "ticketmaster-test-key", SearchLocation("Tychy", "u2y0test", 50)
    )

    with (
        patch("src.integrations.ticketmaster.client._get_ticketmaster_data", side_effect=responses) as get,
        caplog.at_level("INFO", logger="src.integrations.ticketmaster.client"),
    ):
        events = client.search_events(
            30, seen_event_ids={f"seen-{index}" for index in range(10)}
        )

    assert [event.id for event in events] == [
        "ticketmaster:new-1", "ticketmaster:new-2"
    ]
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

    with patch("src.integrations.ticketmaster.client._get_ticketmaster_data", return_value=data) as get:
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

    with patch("src.integrations.ticketmaster.client._get_ticketmaster_data", side_effect=responses) as get:
        events = client.search_events(30, seen_event_ids=set())

    assert [event.id for event in events] == [
        f"ticketmaster:new-{index}" for index in range(10)
    ]
    assert get.call_count == 2


@pytest.mark.parametrize("seen_event_id", ["seen", "ticketmaster:seen"])
def test_search_events_stops_when_ticketmaster_pages_are_exhausted(seen_event_id):
    data = _discovery_page(0, 1, [_discovery_event("seen")])
    client = TicketmasterClient(
        "ticketmaster-test-key", SearchLocation("Tychy", "u2y0test", 50)
    )

    with patch("src.integrations.ticketmaster.client._get_ticketmaster_data", return_value=data) as get:
        events = client.search_events(30, seen_event_ids={seen_event_id})

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

    with patch("src.integrations.ticketmaster.client._get_ticketmaster_data", side_effect=responses) as get:
        events = client.search_events(30, seen_event_ids=set())

    assert [event.id for event in events] == [
        f"ticketmaster:new-{page}" for page in range(5)
    ]
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
        patch("src.integrations.ticketmaster.client.requests.get", return_value=response),
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


def test_search_events_uses_api_key_and_parses_events():
    response = type(
        "Response",
        (),
        {
            "json": lambda self: {
                "_embedded": {
                    "events": [
                        {
                            "id": "event-1",
                            "name": "Concert",
                            "dates": {"start": {"localDate": "2026-09-10"}},
                            "url": "https://example.test/event-1",
                            "_embedded": {
                                "venues": [
                                    {
                                        "name": "Arena",
                                        "city": {"name": "Katowice"},
                                    }
                                ],
                            },
                        }
                    ]
                }
            },
            "raise_for_status": lambda self: None,
        },
    )()

    with patch("src.integrations.ticketmaster.client.requests.get", return_value=response) as get:
        events = TicketmasterClient(
            "ticketmaster-test-key",
            SearchLocation("Tychy", "u2y0test", 50),
        ).search_events(30)

    get.assert_called_once()
    assert (
        get.call_args.args[0]
        == "https://app.ticketmaster.com/discovery/v2/events.json"
    )
    assert get.call_args.kwargs["params"]["apikey"] == "ticketmaster-test-key"
    assert get.call_args.kwargs["params"]["geoPoint"] == "u2y0test"
    assert get.call_args.kwargs["params"]["radius"] == 50
    assert get.call_args.kwargs["params"]["unit"] == "km"
    assert get.call_args.kwargs["params"]["classificationName"] == "-sports"
    assert events == [
        Event(
            id="ticketmaster:event-1",
            name="Concert",
            date="2026-09-10",
            city="Katowice",
            venue="Arena",
            url="https://example.test/event-1",
            source="ticketmaster",
            source_event_id="event-1",
        )
    ]


def test_search_events_parses_fixed_ticketmaster_price():
    event = {
        "id": "event-1",
        "name": "Concert",
        "priceRanges": [
            {"type": "standard", "currency": "PLN", "min": 40, "max": 40}
        ],
    }

    parsed = TicketmasterClient(
        "ticketmaster-test-key", SearchLocation("Tychy", "u2y0test", 50)
    )._event_from_response(event)

    assert parsed.admission == Admission(False, 40, 40, "PLN")


def test_search_events_parses_ticketmaster_price_range():
    event = {
        "id": "event-1",
        "name": "Concert",
        "priceRanges": [
            {"type": "standard", "currency": "PLN", "min": 40, "max": 60}
        ],
    }

    parsed = TicketmasterClient(
        "ticketmaster-test-key", SearchLocation("Tychy", "u2y0test", 50)
    )._event_from_response(event)

    assert parsed.admission == Admission(False, 40, 60, "PLN")


def test_search_events_leaves_admission_unknown_without_price_ranges():
    parsed = TicketmasterClient(
        "ticketmaster-test-key", SearchLocation("Tychy", "u2y0test", 50)
    )._event_from_response({"id": "event-1", "name": "Concert"})

    assert parsed.admission is None


def test_get_event_details_uses_api_key_and_parses_event():
    response = type(
        "Response",
        (),
        {
            "json": lambda self: {
                "name": "Concert",
                "dates": {
                    "start": {
                        "localDate": "2026-09-10",
                        "localTime": "19:00:00",
                    }
                },
                "url": "https://example.test/event-1",
                "_embedded": {
                    "venues": [
                        {"name": "Arena", "city": {"name": "Tychy"}},
                    ]
                },
            },
            "raise_for_status": lambda self: None,
        },
    )()

    with patch("src.integrations.ticketmaster.client.requests.get", return_value=response) as get:
        details = TicketmasterClient(
            "ticketmaster-test-key",
            SearchLocation("Tychy", "u2y0test", 50),
        ).get_event_details("event-1")

    get.assert_called_once_with(
        "https://app.ticketmaster.com/discovery/v2/events/event-1.json",
        params={"apikey": "ticketmaster-test-key"},
        timeout=10,
    )
    assert details == EventDetails(
        name="Concert",
        date="2026-09-10",
        time="19:00:00",
        venue="Arena",
        city="Tychy",
        url="https://example.test/event-1",
    )


def test_ticketmaster_client_builds_urls_from_configured_api_base_url():
    responses = [
        {"_embedded": {"events": []}},
        {"name": "Concert"},
    ]
    client = TicketmasterClient(
        "ticketmaster-test-key",
        SearchLocation("Tychy", "u2y0test", 50),
        api_base_url="http://fake-services:8080/ticketmaster/discovery/v2/",
    )

    with patch(
        "src.integrations.ticketmaster.client._get_ticketmaster_data",
        side_effect=responses,
    ) as get_data:
        client.search_events(30)
        client.get_event_details("event-1")

    assert [call.args[0] for call in get_data.call_args_list] == [
        "http://fake-services:8080/ticketmaster/discovery/v2/events.json",
        "http://fake-services:8080/ticketmaster/discovery/v2/events/event-1.json",
    ]
