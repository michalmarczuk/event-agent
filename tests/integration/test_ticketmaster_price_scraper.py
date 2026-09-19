from unittest.mock import MagicMock

import pytest
from qase.pytest import qase

from src.models import Admission
from src.tools import ticketmaster_price_scraper as scraper_module
from src.tools.ticketmaster_price_scraper import TicketmasterPriceScraper
from tests.support.ticketmaster_price_scraper_support import _EVENT_URL, scraper_for


@pytest.mark.parametrize(
    ("proxy_url", "proxy_options"),
    [
        (None, {}),
        pytest.param(
            "socks5://127.0.0.1:1055",
            {"proxy": {"server": "socks5://127.0.0.1:1055"}},
            marks=(qase.id(23), pytest.mark.qase),
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
        page.wait_for_timeout.assert_not_called()
        call_names = [record[0] for record in page.mock_calls]
        assert call_names.index("goto") < call_names.index("locator")
        page.close.assert_called_once_with()
    local_browser.close.assert_called_once_with()
    playwright.stop.assert_called_once_with()
