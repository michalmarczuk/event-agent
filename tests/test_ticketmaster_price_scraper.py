import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.models import Admission
from src.tools.ticketmaster_price_scraper import TicketmasterPriceScraper


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
        if not self.item_count:
            raise PlaywrightTimeoutError("locator is not visible")
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
    consent_navigation_url=None,
    consent_triggers_load=False,
    page_language=None,
    page_title="Ticketmaster Event",
    user_agent="test-user-agent",
    viewport_size=None,
):
    page = MagicMock()
    page.url = "https://example.test/current-event"
    page.goto.return_value = SimpleNamespace(status=200, url=page.url)
    page.title.return_value = page_title
    page.viewport_size = viewport_size or {"width": 1440, "height": 900}
    body = FakeLocator(body_text)
    page.content.side_effect = lambda: f"<html><body>{body.text}</body></html>"

    main_frame = MagicMock()
    main_frame.url = page.url
    page.frames = [main_frame]
    page.main_frame = main_frame
    event_handlers = {}
    page.event_handlers = event_handlers
    page.main_document_state = {
        "bodyInnerHTMLLength": len(body.text),
        "bodyTextContentLength": len(body.text),
        "bodyInnerTextLength": len(body.text),
        "bodyChildElementCount": 1,
        "bodyChildren": [
            {
                "tagName": "DIV",
                "name": "",
                "id": "root",
                "classes": "app",
            }
        ],
        "documentOuterHTMLLength": len(page.content()),
        "bodyDisplay": "block",
        "bodyVisibility": "visible",
        "bodyOpacity": "1",
    }

    def register_event_handler(event_name, callback):
        event_handlers.setdefault(event_name, []).append(callback)

    page.on.side_effect = register_event_handler

    def evaluate(expression):
        if "bodyInnerHTMLLength" in expression:
            return page.main_document_state
        if "bodyTextLength" in expression:
            return {
                "readyState": "complete",
                "bodyTextLength": len(body.text),
            }
        return {
            "document.documentElement.lang": page_language or "",
            "navigator.userAgent": user_agent,
        }[expression]

    page.evaluate.side_effect = evaluate

    def click_best_available():
        if after_click is not None:
            body.text = after_click

    def click_consent():
        if consent_click_error is not None:
            raise consent_click_error
        if after_consent is not None:
            body.text = after_consent
        if consent_navigation_url is not None:
            page.url = consent_navigation_url
            main_frame.url = consent_navigation_url
            for callback in event_handlers.get("framenavigated", []):
                callback(main_frame)
        if consent_triggers_load:
            for callback in event_handlers.get("load", []):
                callback()
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
        if not text:
            return False
        if hasattr(pattern, "search"):
            return bool(pattern.search(text))
        return pattern == text

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


def test_scrape_extracts_two_prices_as_range():
    scraper, page, best_control = scraper_for(
        "Search For Tickets\nNormal ticket PLN 63.60 each\n"
        "Discount ticket PLN 37.10 each"
    )

    result = scraper.scrape("https://example.test/event")

    assert result == Admission(False, 37.10, 63.60, "PLN")
    page.goto.assert_called_once()
    page.close.assert_called_once()


@pytest.mark.parametrize("consent_text", ["Accept Cookies", "Accept"])
def test_scrape_accepts_english_consent(consent_text, caplog):
    scraper, page, _ = scraper_for(
        "Privacy choices",
        consent_text=consent_text,
        after_consent="Search For Tickets\nNormal ticket PLN 49",
    )

    with caplog.at_level(logging.INFO):
        result = scraper.scrape("https://example.test/event")

    assert result == Admission(False, 49, 49, "PLN")
    assert page.consent_control.click_count == 1
    assert page.wait_for_timeout.call_args_list == [
        call(1_000),
        call(2_000),
        call(2_000),
    ]
    assert f"consent control found matched text='{consent_text}'" in caplog.text
    assert f"consent clicked matched text='{consent_text}'" in caplog.text


def test_scrape_accepts_polish_consent(caplog):
    consent_text = "Akceptuję"
    privacy_text = "Dbamy o Twoją prywatność\nOdrzucenie wszystkich\nPokaż cele"
    scraper, page, _ = scraper_for(
        privacy_text,
        consent_text=consent_text,
        after_consent="Bilety\nBilet normalny 63,60 zł",
        consent_navigation_url="https://example.test/after-consent",
        consent_triggers_load=True,
        section_marker="Bilety",
        page_language="pl-PL",
    )

    with caplog.at_level(logging.INFO):
        result = scraper.scrape("https://example.test/event")

    assert result == Admission(False, 63.60, 63.60, "PLN")
    assert page.consent_control.click_count == 1
    assert page.wait_for_timeout.call_args_list == [
        call(1_000),
        call(2_000),
        call(2_000),
    ]
    assert "consent control found matched text='Akceptuję'" in caplog.text
    assert "consent clicked matched text='Akceptuję'" in caplog.text
    checkpoints = [
        record.getMessage()
        for record in caplog.records
        if "consent readiness checkpoint=" in record.getMessage()
    ]
    assert len(checkpoints) == 5
    assert "checkpoint=before-click" in checkpoints[0]
    assert "page_url='https://example.test/current-event'" in checkpoints[0]
    assert "ready_state='complete'" in checkpoints[0]
    assert "title='Ticketmaster Event'" in checkpoints[0]
    assert f"body_text_length={len(privacy_text)}" in checkpoints[0]
    assert "content_length=" in checkpoints[0]
    assert "frame_count=1" in checkpoints[0]
    assert "frame_urls=['https://example.test/current-event']" in checkpoints[0]
    checkpoint_names = [
        message.split("checkpoint=", 1)[1].split(" ", 1)[0]
        for message in checkpoints
    ]
    assert checkpoint_names == [
        "before-click",
        "immediately-after-click",
        "after-1s",
        "after-3s",
        "after-5s",
    ]
    assert all(
        "page_url='https://example.test/after-consent'" in message
        for message in checkpoints[1:]
    )
    assert all("navigation_observed=True" in message for message in checkpoints[1:])
    assert all(
        "main_frame_navigation_observed=True" in message
        for message in checkpoints[1:]
    )
    assert all("load_observed=True" in message for message in checkpoints[1:])
    assert "consent post-click events navigation_observed=True" in caplog.text
    assert "main_frame_navigation_observed=True" in caplog.text
    assert "load_observed=True" in caplog.text


def test_consent_readiness_diagnostics_run_only_for_first_scraped_event(caplog):
    scraper, page, _ = scraper_for(
        "Privacy choices",
        consent_text="Accept Cookies",
        after_consent="Search For Tickets\nNormal ticket PLN 49",
    )

    with caplog.at_level(logging.INFO):
        first_result = scraper.scrape("https://example.test/event-1")
        page.consent_control.item_count = 1
        second_result = scraper.scrape("https://example.test/event-2")

    assert first_result == Admission(False, 49, 49, "PLN")
    assert second_result == Admission(False, 49, 49, "PLN")
    assert caplog.text.count("consent readiness checkpoint=before-click") == 1
    assert caplog.text.count("consent readiness checkpoint=") == 5
    assert caplog.text.count("first-event main document response") == 1
    assert caplog.text.count("first-event main document diagnostic body_") == 1
    assert page.on.call_count == 6
    assert page.wait_for_timeout.call_args_list == [
        call(1_000),
        call(2_000),
        call(2_000),
        call(1_000),
    ]


def test_first_event_diagnostics_capture_dom_and_browser_failures(caplog):
    scraper, page, _ = scraper_for(
        "Privacy choices",
        consent_text="Accept Cookies",
        after_consent="",
        section_marker=None,
        page_title="",
    )
    page.main_document_state = {
        "bodyInnerHTMLLength": 249_000,
        "bodyTextContentLength": 0,
        "bodyInnerTextLength": 0,
        "bodyChildElementCount": 2,
        "bodyChildren": [
            {
                "tagName": "DIV",
                "name": "application",
                "id": "root",
                "classes": "hidden shell",
            },
            {
                "tagName": "IFRAME",
                "name": "analytics",
                "id": "",
                "classes": "",
            },
        ],
        "documentOuterHTMLLength": 250_000,
        "bodyDisplay": "none",
        "bodyVisibility": "hidden",
        "bodyOpacity": "0",
    }

    def goto(*args, **kwargs):
        handlers = page.event_handlers
        handlers["pageerror"][0](
            SimpleNamespace(message="bootstrap failed token=page-secret")
        )
        handlers["console"][0](
            SimpleNamespace(
                type="warning",
                text=(
                    "hydration warning https://www.ticketmaster.pl/app.js?token=url-secret "
                    "cookie=session-secret"
                ),
            )
        )
        handlers["console"][0](
            SimpleNamespace(type="info", text="ignored console info")
        )
        handlers["requestfailed"][0](
            SimpleNamespace(
                url="https://assets.example.test/app.js?token=request-secret",
                failure="net::ERR_FAILED api_key=reason-secret",
            )
        )
        handlers["response"][0](
            SimpleNamespace(
                url="https://www.ticketmaster.pl/api/bootstrap?token=response-secret",
                status=503,
            )
        )
        handlers["response"][0](
            SimpleNamespace(url="https://ads.example.test/blocked", status=500)
        )
        handlers["response"][0](
            SimpleNamespace(url="https://www.ticketmaster.pl/healthy", status=204)
        )
        return SimpleNamespace(
            url="https://www.ticketmaster.pl/event/123?token=main-secret",
            status=200,
        )

    page.goto.side_effect = goto

    with caplog.at_level(logging.INFO):
        assert scraper.scrape("https://example.test/event") is None

    assert (
        "first-event main document response status=200 "
        "url='https://www.ticketmaster.pl/event/123'"
    ) in caplog.text
    assert "captured failures browser_count=2 network_count=2" in caplog.text
    assert "kind': 'pageerror'" in caplog.text
    assert "bootstrap failed token=<redacted>" in caplog.text
    assert "kind': 'console'" in caplog.text
    assert "https://www.ticketmaster.pl/app.js" in caplog.text
    assert "cookie=<redacted>" in caplog.text
    assert "ignored console info" not in caplog.text
    assert "kind': 'requestfailed'" in caplog.text
    assert "https://assets.example.test/app.js" in caplog.text
    assert "api_key=<redacted>" in caplog.text
    assert "kind': 'non-2xx-response'" in caplog.text
    assert "https://www.ticketmaster.pl/api/bootstrap" in caplog.text
    assert "status': 503" in caplog.text
    assert "https://ads.example.test/blocked" not in caplog.text
    assert "https://www.ticketmaster.pl/healthy" not in caplog.text
    assert "body_inner_html_length=249000" in caplog.text
    assert "body_text_content_length=0" in caplog.text
    assert "body_inner_text_length=0" in caplog.text
    assert "body_child_element_count=2" in caplog.text
    assert "'id': 'root'" in caplog.text
    assert "'classes': 'hidden shell'" in caplog.text
    assert "document_outer_html_length=250000" in caplog.text
    assert "body_display='none'" in caplog.text
    assert "body_visibility='hidden'" in caplog.text
    assert "body_opacity='0'" in caplog.text
    assert "secret" not in caplog.text


def test_first_event_browser_diagnostics_are_bounded(caplog):
    scraper, page, _ = scraper_for(
        "Privacy choices",
        consent_text="Accept Cookies",
        after_consent="Search For Tickets\nNormal ticket PLN 49",
    )

    def goto(*args, **kwargs):
        handlers = page.event_handlers
        for index in range(25):
            handlers["pageerror"][0](
                SimpleNamespace(message=f"bounded page error {index}")
            )
            handlers["requestfailed"][0](
                SimpleNamespace(
                    url=f"https://assets.example.test/{index}",
                    failure=f"bounded request failure {index}",
                )
            )
        return SimpleNamespace(
            url="https://www.ticketmaster.pl/event/123",
            status=200,
        )

    page.goto.side_effect = goto

    with caplog.at_level(logging.INFO):
        assert scraper.scrape("https://example.test/event") == Admission(
            False, 49, 49, "PLN"
        )

    browser_failures = [
        record
        for record in caplog.records
        if "first-event browser failure" in record.getMessage()
    ]
    network_failures = [
        record
        for record in caplog.records
        if "first-event network failure" in record.getMessage()
    ]
    assert len(browser_failures) == 20
    assert len(network_failures) == 20
    assert "bounded page error 19" in caplog.text
    assert "bounded page error 20" not in caplog.text
    assert "bounded request failure 19" in caplog.text
    assert "bounded request failure 20" not in caplog.text


def test_scrape_continues_without_consent_dialog(caplog):
    scraper, page, _ = scraper_for("Search For Tickets\nNormal ticket PLN 49")

    with caplog.at_level(logging.INFO):
        result = scraper.scrape("https://example.test/event")

    assert result == Admission(False, 49, 49, "PLN")
    assert page.consent_control.click_count == 0
    page.wait_for_timeout.assert_not_called()
    assert "consent control found" not in caplog.text
    assert "consent clicked" not in caplog.text


def test_scrape_continues_when_consent_click_fails(caplog):
    scraper, page, _ = scraper_for(
        "Privacy modal\nSearch For Tickets\nNormal ticket PLN 49",
        consent_text="Accept Cookies",
        consent_click_error=RuntimeError("consent click failed"),
    )

    with caplog.at_level(logging.INFO):
        result = scraper.scrape("https://example.test/event")

    assert result == Admission(False, 49, 49, "PLN")
    assert page.consent_control.click_count == 1
    page.wait_for_timeout.assert_not_called()
    assert "consent control found matched text='Accept Cookies'" in caplog.text
    assert "consent control click failed" in caplog.text
    assert "consent clicked" not in caplog.text


def test_scrape_does_not_click_reject_all_control():
    scraper, page, _ = scraper_for(
        "Odrzucenie wszystkich\nSearch For Tickets\nNormal ticket PLN 49",
        consent_text="Odrzucenie wszystkich",
    )

    assert scraper.scrape("https://example.test/event") == Admission(
        False, 49, 49, "PLN"
    )
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

    assert scraper.scrape("https://example.test/event") == Admission(
        False, 37.10, 63.60, "PLN"
    )


def test_scrape_uses_local_ticketmaster_browser_settings():
    scraper, _, _ = scraper_for("Search For Tickets\nNormal ticket PLN 49")

    scraper.scrape("https://example.test/event")

    scraper._browser.new_context.assert_called_once_with(
        locale="pl-PL",
        timezone_id="Europe/Warsaw",
        viewport={"width": 1440, "height": 900},
    )


def test_scrape_extracts_one_price_as_fixed_price():
    scraper, _, _ = scraper_for("Search For Tickets\nNormal ticket PLN 49 zł")

    result = scraper.scrape("https://example.test/event")

    assert result == Admission(False, 49, 49, "PLN")


def test_scrape_returns_none_for_verification_page():
    scraper, _, _ = scraper_for("Let's Get Your Identity Verified - not a bot")

    assert scraper.scrape("https://example.test/event") is None


def test_scrape_ignores_malformed_price_text():
    scraper, _, _ = scraper_for(
        "Search For Tickets\nNormal ticket PLN unavailable\n"
        "Discount ticket PLN 37.10 each"
    )

    assert scraper.scrape("https://example.test/event") == Admission(
        False, 37.10, 37.10, "PLN"
    )


def test_scrape_returns_none_when_navigation_fails():
    scraper, page, _ = scraper_for("Search For Tickets")
    page.goto.side_effect = RuntimeError("navigation failed")

    assert scraper.scrape("https://example.test/event") is None


def test_scrape_extracts_prices_without_known_ticket_section_marker():
    scraper, _, _ = scraper_for(
        "Cennik\nBilet normalny PLN 63.60\nBilet ulgowy 37,10 zł",
        section_marker=None,
    )

    assert scraper.scrape("https://example.test/event") == Admission(
        False, 37.10, 63.60, "PLN"
    )


def test_scrape_logs_diagnostics_without_prices_control_or_ticket_marker(caplog):
    visible_prefix = "pArDoN " + "x" * 1_493
    body_text = visible_prefix + "not-in-visible-prefix"
    scraper, _, _ = scraper_for(
        body_text,
        section_marker=None,
        page_language="pl-PL",
        page_title="YOUR BROWSING ACTIVITY HAS BEEN PAUSED",
        user_agent="diagnostic-user-agent",
        viewport_size={"width": 1280, "height": 720},
    )

    with caplog.at_level(logging.WARNING):
        assert scraper.scrape("https://example.test/event") is None

    assert "page_url='https://example.test/current-event'" in caplog.text
    assert "title='YOUR BROWSING ACTIVITY HAS BEEN PAUSED'" in caplog.text
    assert "document_element_lang='pl-PL'" in caplog.text
    assert f"body_text_length={len(body_text)}" in caplog.text
    assert repr(visible_prefix) in caplog.text
    assert "not-in-visible-prefix" not in caplog.text
    assert "challenge_detected=True" in caplog.text
    assert "Your Browsing Activity Has Been Paused" in caplog.text
    assert "Pardon" in caplog.text
    assert "user_agent='diagnostic-user-agent'" in caplog.text
    assert "viewport_size={'width': 1280, 'height': 720}" in caplog.text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("PLN 63.60", 63.60),
        ("PLN 37.10", 37.10),
        ("63,60 zł", 63.60),
        ("63 zł", 63.0),
    ],
)
def test_scrape_accepts_common_polish_price_formats(text, expected):
    scraper, _, _ = scraper_for(f"Search For Tickets\n{text}")

    assert scraper.scrape("https://example.test/event") == Admission(
        False, expected, expected, "PLN"
    )


def test_scrape_clicks_best_available_when_direct_prices_are_missing():
    scraper, _, best_control = scraper_for(
        "Search For Tickets\nChoose a ticket",
        after_click="Search For Tickets\nBest available PLN 63,60 zł",
        best_control_text="See best available",
    )

    result = scraper.scrape("https://example.test/event")

    assert result == Admission(False, 63.60, 63.60, "PLN")
    assert best_control.click_count == 1


def test_scrape_clicks_polish_best_available_control(caplog):
    control_text = "Wybierz najlepsze dostępne miejsca"
    scraper, page, best_control = scraper_for(
        f"Bilety\n{control_text}",
        after_click="Bilety\nNajlepsze dostępne miejsce 63,60 zł",
        section_marker="Bilety",
        best_control_text=control_text,
        page_language="pl-PL",
    )

    with caplog.at_level(logging.INFO):
        result = scraper.scrape("https://example.test/event")

    assert result == Admission(False, 63.60, 63.60, "PLN")
    assert best_control.click_count == 1
    page.wait_for_timeout.assert_called_once_with(1_000)
    assert "page language/variant=pl-PL" in caplog.text
    assert "ticket section marker matched text='Bilety'" in caplog.text
    assert f"best-available control matched text='{control_text}'" in caplog.text


def test_scrape_returns_none_when_best_available_control_is_absent():
    scraper, _, _ = scraper_for(
        "Search For Tickets\nNo prices yet",
    )

    assert scraper.scrape("https://example.test/event") is None


def test_scrape_returns_none_when_best_available_click_fails():
    scraper, _, best_control = scraper_for(
        "Search For Tickets\nNo prices yet",
        best_control_text="See best available",
    )
    best_control.click_callback = lambda: (_ for _ in ()).throw(
        RuntimeError("click failed")
    )

    assert scraper.scrape("https://example.test/event") is None


def test_scrape_returns_none_when_click_does_not_reveal_prices(caplog):
    scraper, page, _ = scraper_for(
        "Search For Tickets\nNo prices yet",
        after_click="Search For Tickets\nStill no prices",
        best_control_text="See best available",
    )

    with caplog.at_level(logging.INFO):
        assert scraper.scrape("https://example.test/event") is None

    assert "pricing unavailable diagnostics" not in caplog.text
    page.title.assert_not_called()
    page.evaluate.assert_not_called()


def test_scrape_logs_diagnostics_without_secrets(caplog):
    secret = "secret-token-value"
    scraper, page, _ = scraper_for(
        f"Search For Tickets\nNormal ticket PLN 49\n{secret}",
    )

    with caplog.at_level(logging.INFO):
        scraper.scrape("https://example.test/event")

    assert "price extraction phase=direct count=1" in caplog.text
    assert "final admission=" in caplog.text
    assert "found=false" not in caplog.text
    assert "clicked=false" not in caplog.text
    assert "pricing unavailable diagnostics" not in caplog.text
    assert secret not in caplog.text
    page.title.assert_not_called()
    page.evaluate.assert_not_called()
