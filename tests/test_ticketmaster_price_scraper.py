import logging
from unittest.mock import MagicMock

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.models import Admission
from src.tools import ticketmaster_price_scraper as scraper_module
from src.tools.ticketmaster_price_scraper import TicketmasterPriceScraper

_EVENT_URL = "https://example.test/event"


class FakeLocator:
    def __init__(
        self,
        text="",
        click=None,
        count=1,
        parent=None,
        attributes=None,
    ):
        self.text = text
        self.click_callback = click
        self.item_count = count
        self.parent = parent
        self.attributes = attributes or {}
        self.click_count = 0

    @property
    def first(self):
        return self

    def click(self, **kwargs):
        self.click_count += 1
        if self.click_callback:
            self.click_callback()

    def count(self):
        return self.item_count

    def inner_text(self, **kwargs):
        return self.text

    def is_visible(self):
        return True

    def wait_for(self, **kwargs):
        if not self.item_count:
            raise PlaywrightTimeoutError("locator is not visible")

    def locator(self, *args, **kwargs):
        return self.parent or self

    def get_attribute(self, name):
        return self.attributes.get(name)


def scraper_for(
    body_text,
    after_click=None,
    *,
    section_marker="Search For Tickets",
    section_marker_role="heading",
    best_control_text=None,
    consent_text=None,
    after_consent=None,
    consent_click_error=None,
    page_language=None,
):
    page = MagicMock()
    body = FakeLocator(body_text)

    def click_best_available():
        if after_click is not None:
            body.text = after_click

    def click_consent():
        if consent_click_error is not None:
            raise consent_click_error
        if after_consent is not None:
            body.text = after_consent
        consent_control.item_count = 0

    heading = FakeLocator(
        text=section_marker or "",
        count=int(section_marker is not None),
        parent=body,
    )
    best_control = FakeLocator(
        text=best_control_text or "",
        click=click_best_available,
        count=int(best_control_text is not None),
    )
    consent_control = FakeLocator(
        text=consent_text or "",
        click=click_consent,
        count=int(consent_text is not None),
    )
    missing = FakeLocator(count=0)

    def matches(pattern, text):
        return bool(text and pattern.search(text))

    def get_by_role(role, name):
        if role == "button" and matches(name, consent_text):
            return consent_control
        if role == section_marker_role and matches(name, section_marker):
            return heading
        if role in ("button", "tab") and matches(name, best_control_text):
            return best_control
        return missing

    def get_by_text(name):
        if matches(name, section_marker):
            return heading
        if matches(name, best_control_text):
            return best_control
        return missing

    def locator(selector):
        if selector == "body":
            return body
        if selector == "html":
            return FakeLocator(attributes={"lang": page_language})
        return missing

    page.get_by_role.side_effect = get_by_role
    page.get_by_text.side_effect = get_by_text
    page.locator.side_effect = locator
    page.consent_control = consent_control
    browser = MagicMock()
    browser.new_context.return_value.new_page.return_value = page
    return TicketmasterPriceScraper(browser=browser), page, best_control


@pytest.mark.parametrize(
    ("proxy_url", "proxy_options"),
    [
        (None, {}),
        (
            "socks5://127.0.0.1:1055",
            {"proxy": {"server": "socks5://127.0.0.1:1055"}},
        ),
    ],
)
def test_camoufox_browser_uses_optional_proxy_and_is_reused_and_closed(
    monkeypatch,
    proxy_url,
    proxy_options,
):
    pages = [
        scraper_for("Search For Tickets\nNormal ticket PLN 49")[1]
        for _ in range(2)
    ]
    local_browser = MagicMock()
    local_context = MagicMock()
    local_context.new_page.side_effect = pages
    local_browser.new_context.return_value = local_context
    playwright = MagicMock()
    playwright_manager = MagicMock()
    playwright_manager.start.return_value = playwright
    sync_playwright = MagicMock(return_value=playwright_manager)
    new_browser = MagicMock(return_value=local_browser)
    monkeypatch.setattr(
        scraper_module,
        "sync_playwright",
        sync_playwright,
    )
    monkeypatch.setattr(
        scraper_module,
        "NewBrowser",
        new_browser,
    )
    monkeypatch.setattr(
        scraper_module,
        "load_scraper_proxy_url",
        lambda: proxy_url,
    )
    with TicketmasterPriceScraper() as scraper:
        for suffix in ("1", "2"):
            assert scraper.scrape(f"{_EVENT_URL}-{suffix}") == Admission(
                False, 49, 49, "PLN"
            )

    new_browser.assert_called_once_with(
        playwright,
        headless=False,
        locale="pl-PL",
        os="macos",
        **proxy_options,
    )
    sync_playwright.assert_called_once_with()
    playwright_manager.start.assert_called_once_with()
    local_browser.new_context.assert_called_once_with(
        locale="pl-PL",
        timezone_id="Europe/Warsaw",
        viewport={"width": 1440, "height": 900},
    )
    assert local_context.new_page.call_count == len(pages)
    for page in pages:
        page.goto.assert_called_once()
        page.wait_for_timeout.assert_called_once_with(5_000)
        call_names = [record[0] for record in page.mock_calls]
        assert (
            call_names.index("goto")
            < call_names.index("wait_for_timeout")
            < call_names.index("locator")
        )
        page.close.assert_called_once_with()
    local_browser.close.assert_called_once_with()
    playwright.stop.assert_called_once_with()


def test_scrape_extracts_two_prices_as_range():
    scraper, _, _ = scraper_for(
        "Search For Tickets\nNormal ticket PLN 63.60 each\n"
        "Discount ticket PLN 37.10 each"
    )

    assert scraper.scrape(_EVENT_URL) == Admission(False, 37.10, 63.60, "PLN")


@pytest.mark.parametrize(
    "consent_text",
    ["Accept Cookies", "Accept", "Akceptuję"],
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
    page.wait_for_timeout.assert_called_once_with(1_000)
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


def test_scrape_ignores_malformed_price_text():
    scraper, _, _ = scraper_for(
        "Search For Tickets\nNormal ticket PLN unavailable\n"
        "Discount ticket PLN 37.10 each"
    )

    assert scraper.scrape(_EVENT_URL) == Admission(
        False, 37.10, 37.10, "PLN"
    )


def test_scrape_returns_none_and_logs_when_navigation_fails(caplog):
    scraper, page, _ = scraper_for("Search For Tickets")
    page.goto.side_effect = RuntimeError("navigation failed")

    with caplog.at_level(logging.WARNING):
        assert scraper.scrape(_EVENT_URL) is None

    assert "Ticketmaster navigation failed" in caplog.text


def test_scrape_extracts_prices_without_known_ticket_section_marker():
    scraper, _, _ = scraper_for(
        "Cennik\nBilet normalny PLN 63.60\nBilet ulgowy 37,10 zł",
        section_marker=None,
    )

    assert scraper.scrape(_EVENT_URL) == Admission(
        False, 37.10, 63.60, "PLN"
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
    scraper, _, _ = scraper_for(
        "Search For Tickets\nNo prices yet",
    )

    with caplog.at_level(logging.WARNING):
        assert scraper.scrape(_EVENT_URL) is None

    assert "no price found and no best-available control" in caplog.text


def test_scrape_returns_none_when_best_available_click_fails():
    scraper, _, best_control = scraper_for(
        "Search For Tickets\nNo prices yet",
        best_control_text="See best available",
    )
    best_control.click_callback = MagicMock(side_effect=RuntimeError("click failed"))

    assert scraper.scrape(_EVENT_URL) is None


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


def test_scrape_logs_start_and_found_price_without_body_text(caplog):
    body_only_text = "body-only-value"
    scraper, _, _ = scraper_for(
        f"Search For Tickets\nNormal ticket PLN 49\n{body_only_text}",
    )

    with caplog.at_level(logging.INFO):
        scraper.scrape(_EVENT_URL)

    assert "Starting Ticketmaster price scrape" in caplog.text
    assert "price extraction phase=direct count=1" in caplog.text
    assert "final admission=" in caplog.text
    assert body_only_text not in caplog.text
