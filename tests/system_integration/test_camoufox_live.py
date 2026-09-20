"""Opt-in browser connectivity check for Camoufox and Ticketmaster."""

import os
from urllib.parse import urlparse

from dotenv import load_dotenv
import pytest
from qase.pytest import qase


_TICKETMASTER_URL = "https://www.ticketmaster.pl/"


def _open_ticketmaster(proxy_url: str | None) -> tuple[int | None, str, str]:
    from camoufox.sync_api import NewBrowser
    from playwright.sync_api import sync_playwright

    proxy_options = (
        {"proxy": {"server": proxy_url}}
        if proxy_url
        else {}
    )
    with sync_playwright() as playwright:
        browser = NewBrowser(
            playwright,
            headless=False,
            locale="pl-PL",
            os="macos",
            **proxy_options,
        )
        try:
            context = browser.new_context(
                locale="pl-PL",
                timezone_id="Europe/Warsaw",
                viewport={"width": 1440, "height": 900},
            )
            try:
                page = context.new_page()
                try:
                    response = page.goto(
                        _TICKETMASTER_URL,
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )
                    page.wait_for_function(
                        "() => document.body && document.body.innerText.trim().length > 0",
                        timeout=20_000,
                    )
                    body_text = page.locator("body").inner_text(
                        timeout=5_000
                    ).strip()
                    status = response.status if response is not None else None
                    return status, page.url, body_text
                finally:
                    page.close()
            finally:
                context.close()
        finally:
            browser.close()


@qase.id(26)
@pytest.mark.smoke
@pytest.mark.live
def test_camoufox_reaches_ticketmaster() -> None:
    """Verify headed Camoufox connectivity without requiring event pricing."""
    load_dotenv()
    proxy_url = os.getenv("SCRAPER_PROXY_URL") or None

    try:
        status, page_url, body_text = _open_ticketmaster(proxy_url)
    except Exception as error:
        raise AssertionError(
            f"Camoufox Ticketmaster smoke failed ({type(error).__name__})"
        ) from None

    hostname = (urlparse(page_url).hostname or "").lower()
    assert status is not None, "Ticketmaster navigation returned no response"
    assert 200 <= status < 400, f"Ticketmaster navigation failed (HTTP {status})"
    assert hostname == "ticketmaster.pl" or hostname.endswith(".ticketmaster.pl")
    assert body_text, "Ticketmaster page body is empty"
    assert "ticketmaster" in body_text.casefold(), (
        "Ticketmaster page body contains no Ticketmaster identity"
    )
