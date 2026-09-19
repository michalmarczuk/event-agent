import logging
from unittest.mock import call

import pytest

from src.models import Admission
from tests.ticketmaster_price_scraper_support import _EVENT_URL, scraper_for


def test_readiness_returns_immediately_when_price_is_visible():
    scraper, page, _ = scraper_for(
        "Ticketmaster event details\nNormal ticket PLN 49",
        section_marker=None,
    )

    assert scraper.scrape(_EVENT_URL) == Admission(False, 49, 49, "PLN")
    page.wait_for_timeout.assert_not_called()


def test_readiness_polls_until_ticket_content_is_available():
    scraper, page, _ = scraper_for("Loading", section_marker=None)
    body = page.locator("body")
    rendered_text = "Ticketmaster event details\nNormal ticket PLN 49"

    def render_after_two_poll_intervals(timeout):
        if page.wait_for_timeout.call_count == 2:
            body.text = rendered_text

    page.wait_for_timeout.side_effect = render_after_two_poll_intervals

    assert scraper.scrape(_EVENT_URL) == Admission(False, 49, 49, "PLN")
    assert page.wait_for_timeout.call_args_list == [call(500), call(500)]


@pytest.mark.parametrize(
    ("body_text", "section_marker", "section_marker_role"),
    [
        (
            "Ticketmaster page is still loading without ticket information",
            None,
            "heading",
        ),
        (
            "Pomiń, aby wyszukać bilety\nŁadowanie strony wydarzenia",
            "Pomiń, aby wyszukać bilety",
            "link",
        ),
        (
            "Skip to Search For Tickets\nEvent page still loading",
            "Skip to Search For Tickets",
            "link",
        ),
    ],
)
def test_readiness_timeout_falls_through_without_raising(
    body_text,
    section_marker,
    section_marker_role,
    caplog,
):
    scraper, page, _ = scraper_for(
        body_text,
        section_marker=section_marker,
        section_marker_role=section_marker_role,
    )

    with caplog.at_level(logging.WARNING):
        assert scraper.scrape(_EVENT_URL) is None

    assert page.wait_for_timeout.call_args_list == [call(500)] * 40
    failure_record = next(
        record
        for record in caplog.records
        if record.__dict__.get("event.outcome") == "failure"
    )
    assert failure_record.__dict__["event.reason"] == "page_not_ready"


def test_scrape_ignores_malformed_price_text():
    scraper, _, _ = scraper_for(
        "Search For Tickets\nNormal ticket PLN unavailable\n"
        "Discount ticket PLN 37.10 each"
    )

    assert scraper.scrape(_EVENT_URL) == Admission(
        False, 37.10, 37.10, "PLN"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("PLN 63.60", 63.60),
        ("63,60 zł", 63.60),
        ("63 zł", 63.0),
    ],
)
def test_scrape_accepts_common_polish_price_formats(text, expected):
    scraper, _, _ = scraper_for(f"Search For Tickets\n{text}")

    assert scraper.scrape(_EVENT_URL) == Admission(
        False, expected, expected, "PLN"
    )
