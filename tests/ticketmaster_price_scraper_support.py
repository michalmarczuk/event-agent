from unittest.mock import MagicMock

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

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
