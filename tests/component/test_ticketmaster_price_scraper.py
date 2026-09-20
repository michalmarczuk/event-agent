import logging
from unittest.mock import MagicMock, call

import pytest

from src.models import Admission
from tests.support.ticketmaster_price_scraper_support import _EVENT_URL, scraper_for


def test_scrape_extracts_two_prices_as_range():
    scraper, _, _ = scraper_for(
        "Search For Tickets\nNormal ticket PLN 63.60 each\n"
        "Discount ticket PLN 37.10 each"
    )

    assert scraper.scrape(_EVENT_URL) == Admission(False, 37.10, 63.60, "PLN")


def test_readiness_ignores_skip_link_until_best_available_is_visible():
    skip_link = "Pomiń, aby wyszukać bilety"
    control_text = "Wybierz najlepsze dostępne miejsca"
    scraper, page, best_control = scraper_for(
        f"{skip_link}\nŁadowanie strony wydarzenia",
        after_click="Bilety\nBilet normalny 63,60 zł",
        section_marker=skip_link,
        section_marker_role="link",
        best_control_text=control_text,
    )
    body = page.locator("body")
    best_control.item_count = 0

    def reveal_ticket_controls(timeout):
        if page.wait_for_timeout.call_count == 2:
            body.text = (
                f"{skip_link}\nWybierz sposób wyszukiwania dostępnych biletów\n"
                f"{control_text}"
            )
            best_control.item_count = 1

    page.wait_for_timeout.side_effect = reveal_ticket_controls

    assert scraper.scrape(_EVENT_URL) == Admission(False, 63.60, 63.60, "PLN")
    assert page.wait_for_timeout.call_args_list == [
        call(500),
        call(500),
        call(1_000),
    ]
    assert best_control.click_count == 1


@pytest.mark.parametrize(
    "consent_text",
    [
        "Accept Cookies",
        "Accept",
        "Akceptuję",
    ],
)
def test_scrape_accepts_localized_consent(consent_text, caplog):
    scraper, page, _ = scraper_for(
        "Privacy choices",
        consent_text=consent_text,
        after_consent="Search For Tickets\nNormal ticket PLN 49",
    )

    with caplog.at_level(logging.INFO):
        result = scraper.scrape(_EVENT_URL)

    assert result == Admission(False, 49, 49, "PLN")
    assert page.consent_control.click_count == 1
    assert call(1_000) in page.wait_for_timeout.call_args_list
    assert f"consent control found matched text='{consent_text}'" in caplog.text
    assert f"consent clicked matched text='{consent_text}'" in caplog.text


def test_scrape_continues_without_consent_dialog():
    scraper, page, _ = scraper_for("Search For Tickets\nNormal ticket PLN 49")

    result = scraper.scrape(_EVENT_URL)

    assert result == Admission(False, 49, 49, "PLN")
    assert page.consent_control.click_count == 0
    page.wait_for_timeout.assert_not_called()


def test_scrape_continues_when_consent_click_fails(caplog):
    scraper, page, _ = scraper_for(
        "Privacy modal\nSearch For Tickets\nNormal ticket PLN 49",
        consent_text="Accept Cookies",
        consent_click_error=RuntimeError("consent click failed"),
    )

    with caplog.at_level(logging.WARNING):
        result = scraper.scrape(_EVENT_URL)

    assert result == Admission(False, 49, 49, "PLN")
    assert page.consent_control.click_count == 1
    page.wait_for_timeout.assert_not_called()
    assert "consent control click failed" in caplog.text


def test_scrape_does_not_click_reject_all_control():
    scraper, page, _ = scraper_for(
        "Odrzucenie wszystkich\nSearch For Tickets\nNormal ticket PLN 49",
        consent_text="Odrzucenie wszystkich",
    )

    assert scraper.scrape(_EVENT_URL) == Admission(False, 49, 49, "PLN")
    assert page.consent_control.click_count == 0


@pytest.mark.parametrize(
    ("section_marker", "section_marker_role"),
    [
        ("WYSZUKAJ BILETY", "heading"),
        ("Bilety", None),
    ],
)
def test_scrape_extracts_prices_from_polish_ticket_section(
    section_marker,
    section_marker_role,
):
    scraper, _, _ = scraper_for(
        f"{section_marker}\nBilet normalny 63,60 zł\nBilet ulgowy 37,10 zł",
        section_marker=section_marker,
        section_marker_role=section_marker_role,
        page_language="pl-PL",
    )

    assert scraper.scrape(_EVENT_URL) == Admission(
        False, 37.10, 63.60, "PLN"
    )


def test_scrape_returns_none_for_verification_page():
    scraper, _, _ = scraper_for("Let's Get Your Identity Verified - not a bot")

    assert scraper.scrape(_EVENT_URL) is None


def test_scrape_returns_none_and_logs_when_navigation_fails(caplog):
    scraper, page, _ = scraper_for("Search For Tickets")
    page.goto.side_effect = RuntimeError("navigation failed")

    with caplog.at_level(logging.WARNING):
        assert scraper.scrape(_EVENT_URL) is None

    assert "Ticketmaster navigation failed" in caplog.text
    failure_record = next(
        record
        for record in caplog.records
        if record.__dict__.get("event.outcome") == "failure"
    )
    assert failure_record.__dict__["event.reason"] == "navigation_failed"


def test_scrape_extracts_prices_without_known_ticket_section_marker():
    scraper, _, _ = scraper_for(
        "Cennik\nBilet normalny PLN 63.60\nBilet ulgowy 37,10 zł",
        section_marker=None,
    )

    assert scraper.scrape(_EVENT_URL) == Admission(
        False, 37.10, 63.60, "PLN"
    )


@pytest.mark.parametrize(
    ("section_marker", "control_text", "page_language", "expected_variant"),
    [
        ("Search For Tickets", "See best available", None, "en"),
        (
            "Bilety",
            "Wybierz najlepsze dostępne miejsca",
            "pl-PL",
            "pl-PL",
        ),
    ],
)
def test_scrape_clicks_localized_best_available_control(
    section_marker,
    control_text,
    page_language,
    expected_variant,
    caplog,
):
    scraper, page, best_control = scraper_for(
        f"{section_marker}\n{control_text}",
        after_click=f"{section_marker}\nBest available 63,60 zł",
        section_marker=section_marker,
        best_control_text=control_text,
        page_language=page_language,
    )

    with caplog.at_level(logging.INFO):
        result = scraper.scrape(_EVENT_URL)

    assert result == Admission(False, 63.60, 63.60, "PLN")
    assert best_control.click_count == 1
    page.wait_for_timeout.assert_called_once_with(1_000)
    assert f"page language/variant={expected_variant}" in caplog.text
    assert f"ticket section marker matched text='{section_marker}'" in caplog.text
    assert f"best-available control matched text='{control_text}'" in caplog.text


def test_scrape_logs_when_best_available_control_is_absent(caplog):
    scraper, page, _ = scraper_for(
        "Search For Tickets\nNo prices yet",
    )

    with caplog.at_level(logging.WARNING):
        assert scraper.scrape(_EVENT_URL) is None

    assert "no price found and no best-available control" in caplog.text
    assert page.wait_for_timeout.call_args_list == [call(500)] * 40
    failure_record = next(
        record
        for record in caplog.records
        if record.__dict__.get("event.outcome") == "failure"
    )
    fields = failure_record.__dict__
    assert fields["event.action"] == "ticketmaster_price_scrape"
    assert fields["event.reason"] == "no_price_or_best_available"
    assert fields["url.original"] == _EVENT_URL
    assert fields["scraper.page_language"] == "en"
    assert fields["scraper.direct_price_count"] == 0
    assert fields["scraper.best_available_found"] is False
    assert fields["scraper.ticket_marker"] == "Search For Tickets"
    assert fields["scraper.elapsed_ms"] >= 0


def test_scrape_returns_none_when_best_available_click_fails(caplog):
    scraper, _, best_control = scraper_for(
        "Search For Tickets\nNo prices yet",
        best_control_text="See best available",
    )
    best_control.click_callback = MagicMock(side_effect=RuntimeError("click failed"))

    with caplog.at_level(logging.WARNING):
        assert scraper.scrape(_EVENT_URL) is None

    failure_record = next(
        record
        for record in caplog.records
        if record.__dict__.get("event.outcome") == "failure"
    )
    assert failure_record.__dict__["event.reason"] == "extraction_failed"


def test_scrape_returns_none_when_click_does_not_reveal_prices(caplog):
    scraper, page, _ = scraper_for(
        "Search For Tickets\nNo prices yet",
        after_click="Search For Tickets\nStill no prices",
        best_control_text="See best available",
    )

    with caplog.at_level(logging.INFO):
        assert scraper.scrape(_EVENT_URL) is None

    page.wait_for_timeout.assert_called_once_with(1_000)
    assert "no price found after best-available click" in caplog.text


def test_success_log_contains_structured_diagnostics_without_body_text(caplog):
    body_only_text = "body-only-value"
    scraper, _, _ = scraper_for(
        f"Search For Tickets\nNormal ticket PLN 49\n{body_only_text}",
    )

    with caplog.at_level(logging.INFO):
        result = scraper.scrape(_EVENT_URL)

    assert result == Admission(False, 49, 49, "PLN")
    assert "Starting Ticketmaster price scrape" in caplog.text
    assert "price extraction phase=direct count=1" in caplog.text
    assert "final admission=" in caplog.text
    assert body_only_text not in caplog.text
    success_record = next(
        record
        for record in caplog.records
        if record.__dict__.get("event.outcome") == "success"
    )
    fields = success_record.__dict__
    assert fields["event.action"] == "ticketmaster_price_scrape"
    assert fields["url.original"] == _EVENT_URL
    assert fields["scraper.page_language"] == "en"
    assert fields["scraper.direct_price_count"] == 1
    assert fields["scraper.best_available_found"] is False
    assert fields["scraper.ticket_marker"] == "Search For Tickets"
    assert fields["scraper.price_min"] == 49
    assert fields["scraper.price_max"] == 49
    assert fields["scraper.currency"] == "PLN"
    assert fields["scraper.elapsed_ms"] >= 0


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

    assert scraper.scrape(_EVENT_URL) == Admission(False, 37.10, 37.10, "PLN")


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
