import traceback
from unittest.mock import patch

import pytest
import requests

from src.config import SearchLocation
from src.models import Admission, Event, EventDetails
from src.tools.ticketmaster import TicketmasterClient


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
                                    {"city": {"name": "Katowice"}},
                                ]
                            },
                        }
                    ]
                }
            },
            "raise_for_status": lambda self: None,
        },
    )()

    with patch("src.tools.ticketmaster.requests.get", return_value=response) as get:
        events = TicketmasterClient(
            "ticketmaster-test-key",
            SearchLocation("Tychy", "u2y0test", 50),
        ).search_events(30)

    get.assert_called_once()
    assert get.call_args.kwargs["params"]["apikey"] == "ticketmaster-test-key"
    assert get.call_args.kwargs["params"]["geoPoint"] == "u2y0test"
    assert get.call_args.kwargs["params"]["radius"] == 50
    assert get.call_args.kwargs["params"]["unit"] == "km"
    assert get.call_args.kwargs["params"]["classificationName"] == "-sports"
    assert events == [
        Event(
            id="event-1",
            name="Concert",
            date="2026-09-10",
            city="Katowice",
            venue=None,
            url="https://example.test/event-1",
            source="ticketmaster",
        )
    ]


def test_search_events_parses_fixed_ticketmaster_price():
    event = {
        "id": "event-1",
        "name": "Concert",
        "priceRanges": [{"type": "standard", "currency": "PLN", "min": 40, "max": 40}],
    }

    parsed = TicketmasterClient(
        "ticketmaster-test-key",
        SearchLocation("Tychy", "u2y0test", 50),
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
        "ticketmaster-test-key",
        SearchLocation("Tychy", "u2y0test", 50),
    )._event_from_response(event)

    assert parsed.admission == Admission(False, 40, 60, "PLN")


def test_search_events_leaves_admission_unknown_without_price_ranges():
    event = {
        "id": "event-1",
        "name": "Concert",
    }

    parsed = TicketmasterClient(
        "ticketmaster-test-key",
        SearchLocation("Tychy", "u2y0test", 50),
    )._event_from_response(event)

    assert parsed.admission is None


def test_get_event_details_uses_api_key_and_parses_event():
    response = type(
        "Response",
        (),
        {
            "json": lambda self: {
                "name": "Concert",
                "dates": {"start": {"localDate": "2026-09-10", "localTime": "19:00:00"}},
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

    with patch("src.tools.ticketmaster.requests.get", return_value=response) as get:
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
