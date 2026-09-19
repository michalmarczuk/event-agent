"""Opt-in connectivity check for the live Ticketmaster Discovery API."""

import os

from dotenv import load_dotenv
import pytest
from qase.pytest import qase

from src.config import SearchLocation
from src.models import Event
from src.tools.ticketmaster import TicketmasterClient


@qase.id(24)
@pytest.mark.qase
def test_ticketmaster_discovery_api_is_reachable() -> None:
    """Verify that authenticated Ticketmaster discovery returns domain data."""
    load_dotenv()
    api_key = os.getenv("TICKETMASTER_API_KEY")
    if not api_key:
        pytest.skip("TICKETMASTER_API_KEY is not configured")

    client = TicketmasterClient(
        api_key,
        SearchLocation("Warsaw", "u3qcnh", 50),
    )

    try:
        events = client.search_events(days_ahead=1)
    except Exception as error:
        raise AssertionError(
            f"Ticketmaster discovery smoke failed ({type(error).__name__})"
        ) from None

    assert isinstance(events, list)
    assert all(isinstance(event, Event) for event in events)
