"""Opt-in connectivity check for the live Ticketmaster Discovery API."""

import os

from dotenv import load_dotenv
import pytest
from qase.pytest import qase
import requests


_TICKETMASTER_EVENTS_URL = (
    "https://app.ticketmaster.com/discovery/v2/events.json"
)


@qase.id(24)
@pytest.mark.qase
def test_ticketmaster_discovery_api_is_reachable() -> None:
    """Verify authenticated Ticketmaster Discovery API connectivity."""
    load_dotenv()
    api_key = os.getenv("TICKETMASTER_API_KEY")
    if not api_key:
        pytest.skip("TICKETMASTER_API_KEY is not configured")

    try:
        response = requests.get(
            _TICKETMASTER_EVENTS_URL,
            params={
                "apikey": api_key,
                "countryCode": "PL",
                "size": 1,
            },
            timeout=15,
        )
    except requests.RequestException as error:
        raise AssertionError(
            f"Ticketmaster discovery smoke failed ({type(error).__name__})"
        ) from None

    if not response.ok:
        raise AssertionError(
            "Ticketmaster discovery smoke failed "
            f"(HTTP {response.status_code})"
        )

    try:
        payload = response.json()
    except ValueError:
        raise AssertionError(
            "Ticketmaster discovery smoke returned invalid JSON"
        ) from None

    assert isinstance(payload, dict), (
        "Ticketmaster discovery response is not a JSON object"
    )
    page = payload.get("page")
    assert isinstance(page, dict), (
        "Ticketmaster discovery response has no pagination metadata"
    )
    assert isinstance(page.get("number"), int), (
        "Ticketmaster discovery response has invalid page metadata"
    )

    embedded = payload.get("_embedded")
    if embedded is not None:
        assert isinstance(embedded, dict)
        assert isinstance(embedded.get("events", []), list)
