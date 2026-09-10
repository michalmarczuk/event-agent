import logging
import re
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

try:
    from ..models import Admission
except ImportError:  # pragma: no cover - supports script execution
    from models import Admission

logger = logging.getLogger(__name__)

_ENGLISH_TICKET_SECTION_LABELS = ("Search For Tickets",)
_POLISH_TICKET_SECTION_LABELS = ("Wyszukaj bilety", "Bilety")
_ENGLISH_BEST_AVAILABLE_LABELS = ("See best available",)
_POLISH_BEST_AVAILABLE_LABELS = ("Wybierz najlepsze dostępne miejsca",)


def _label_pattern(
    labels: tuple[str, ...],
    whole_word_labels: tuple[str, ...] = (),
) -> re.Pattern[str]:
    alternatives = []
    for label in labels:
        expression = r"\s+".join(re.escape(word) for word in label.split())
        if label in whole_word_labels:
            expression = rf"\b{expression}\b"
        alternatives.append(expression)
    return re.compile(rf"(?:{'|'.join(alternatives)})", re.IGNORECASE)


_PRICE_PATTERN = re.compile(
    r"(?:PLN\s*(\d+(?:[.,]\d{1,2})?)|"
    r"(\d+(?:[.,]\d{1,2})?)\s*(?:PLN|zł))",
    re.IGNORECASE,
)
_TICKET_SECTION_NAME = _label_pattern(
    _ENGLISH_TICKET_SECTION_LABELS + _POLISH_TICKET_SECTION_LABELS,
    whole_word_labels=_POLISH_TICKET_SECTION_LABELS[-1:],
)
_BEST_AVAILABLE_NAME = _label_pattern(
    _ENGLISH_BEST_AVAILABLE_LABELS + _POLISH_BEST_AVAILABLE_LABELS
)
_POLISH_UI_LABELS = _POLISH_TICKET_SECTION_LABELS + _POLISH_BEST_AVAILABLE_LABELS
_ENGLISH_UI_LABELS = _ENGLISH_TICKET_SECTION_LABELS + _ENGLISH_BEST_AVAILABLE_LABELS
_POLISH_UI_PATTERN = _label_pattern(
    _POLISH_UI_LABELS,
    whole_word_labels=_POLISH_TICKET_SECTION_LABELS[-1:],
)
_ENGLISH_UI_PATTERN = _label_pattern(_ENGLISH_UI_LABELS)
_POLISH_CURRENCY_PATTERN = re.compile(r"\bzł\b", re.IGNORECASE)
_BLOCKED_PAGE_PATTERN = re.compile(
    r"identity\s+verified|not\s+a\s+bot|captcha|waiting\s+room|"
    r"access\s+denied|verify\s+you\s+are\s+human",
    re.IGNORECASE,
)


class TicketmasterPriceScraper:
    """Extract visible Ticketmaster ticket prices from public event pages."""

    def __init__(self, browser: Any | None = None, timeout_ms: int = 15_000):
        self._browser = browser
        self._context = None
        self._timeout_ms = timeout_ms
        self._playwright = None
        self._owns_browser = browser is None

    def __enter__(self) -> "TicketmasterPriceScraper":
        self._ensure_browser()
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        self.close()

    def close(self) -> None:
        """Close the browser created by this scraper, if any."""
        if self._owns_browser and self._browser is not None:
            self._browser.close()
            self._browser = None
        self._context = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def scrape(self, event_url: str | None) -> Admission | None:
        """Return visible PLN admission pricing or ``None`` on scrape failure."""
        if not event_url:
            logger.warning("Ticketmaster price scrape skipped: missing event URL")
            return None

        logger.info("Starting Ticketmaster price scrape url=%s", event_url)
        try:
            context = self._ensure_context()
            page = context.new_page()
            try:
                try:
                    page.goto(
                        event_url,
                        wait_until="domcontentloaded",
                        timeout=self._timeout_ms,
                    )
                except PlaywrightTimeoutError:
                    logger.warning("Ticketmaster navigation timed out url=%s", event_url)
                    return None
                except Exception:
                    logger.warning(
                        "Ticketmaster navigation failed url=%s",
                        event_url,
                        exc_info=True,
                    )
                    return None

                logger.info("Ticketmaster page loaded url=%s", event_url)
                self._accept_cookies(page)
                body = page.locator("body")
                body_text = body.inner_text(timeout=self._timeout_ms)
                page_variant = self._detect_page_variant(page, body_text)
                logger.info(
                    "Ticketmaster page language/variant=%s url=%s",
                    page_variant,
                    event_url,
                )
                if _BLOCKED_PAGE_PATTERN.search(body_text):
                    logger.warning("Ticketmaster blocked/security page detected url=%s", event_url)
                    return None

                ticket_section, marker_text = self._find_ticket_section(page)
                if marker_text is not None:
                    logger.info(
                        "Ticketmaster ticket section marker matched text=%r url=%s",
                        marker_text,
                        event_url,
                    )
                prices = self._prices_from_visible_area(
                    ticket_section,
                    body_text,
                )
                logger.info(
                    "Ticketmaster price extraction phase=direct count=%d url=%s",
                    len(prices),
                    event_url,
                )
                if not prices:
                    control, control_text = self._find_best_available_control(page)
                    if control is None:
                        logger.warning(
                            "Ticketmaster no price found and no best-available control url=%s",
                            event_url,
                        )
                    else:
                        logger.info(
                            "Ticketmaster best-available control matched text=%r url=%s",
                            control_text,
                            event_url,
                        )
                        try:
                            control.click(timeout=self._timeout_ms)
                        except Exception:
                            logger.warning(
                                "Ticketmaster best-available control click failed url=%s",
                                event_url,
                                exc_info=True,
                            )
                        else:
                            page.wait_for_timeout(1_000)
                            body_text = body.inner_text(timeout=self._timeout_ms)
                            prices = self._prices_from_visible_area(
                                ticket_section,
                                body_text,
                            )
                            logger.info(
                                "Ticketmaster price extraction phase=post-click count=%d url=%s",
                                len(prices),
                                event_url,
                            )
                            if not prices:
                                logger.warning(
                                    "Ticketmaster no price found after best-available click url=%s",
                                    event_url,
                                )

                admission = _admission_from_prices(prices) if prices else None
                if admission is not None:
                    logger.info(
                        "Ticketmaster final admission=%s url=%s",
                        admission,
                        event_url,
                    )
                return admission
            finally:
                page.close()
        except PlaywrightTimeoutError:
            logger.warning("Ticketmaster price scrape timed out: %s", event_url)
        except Exception:
            logger.warning(
                "Ticketmaster price scrape failed: %s",
                event_url,
                exc_info=True,
            )
        return None

    def _ensure_browser(self):
        if self._browser is None:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=False)
        return self._browser

    def _ensure_context(self):
        if self._context is None:
            self._context = self._ensure_browser().new_context(
                locale="pl-PL",
                timezone_id="Europe/Warsaw",
                viewport={"width": 1440, "height": 900},
            )
        return self._context

    @staticmethod
    def _detect_page_variant(page: Any, body_text: str) -> str:
        try:
            language = page.locator("html").get_attribute("lang")
        except Exception:
            language = None

        if language:
            return language.strip()
        if _POLISH_UI_PATTERN.search(body_text) or _POLISH_CURRENCY_PATTERN.search(
            body_text
        ):
            return "pl"
        if _ENGLISH_UI_PATTERN.search(body_text):
            return "en"
        return "unknown"

    @staticmethod
    def _find_ticket_section(page: Any) -> tuple[Any | None, str | None]:
        marker = _first_visible(
            page.get_by_role("heading", name=_TICKET_SECTION_NAME)
        )
        if marker is None:
            marker = _first_visible(page.get_by_text(_TICKET_SECTION_NAME))
        if marker is None:
            return None, None

        ticket_section = marker.locator("xpath=../..").locator("xpath=..")
        return ticket_section, _locator_text(marker)

    @staticmethod
    def _find_best_available_control(page: Any) -> tuple[Any | None, str | None]:
        for role in ("button", "tab"):
            control = _first_visible(
                page.get_by_role(role, name=_BEST_AVAILABLE_NAME)
            )
            if control is not None:
                return control, _locator_text(control)

        control = _first_visible(page.get_by_text(_BEST_AVAILABLE_NAME))
        if control is not None:
            return control, _locator_text(control)
        return None, None

    def _prices_from_visible_area(
        self,
        ticket_section: Any | None,
        body_text: str,
    ) -> list[float]:
        if ticket_section is not None:
            try:
                section_prices = _prices_from_text(
                    ticket_section.inner_text(timeout=self._timeout_ms)
                )
            except PlaywrightTimeoutError:
                section_prices = []
            if section_prices:
                return section_prices
        return _prices_from_text(body_text)

    @staticmethod
    def _accept_cookies(page) -> None:
        try:
            page.get_by_role(
                "button",
                name=re.compile(r"accept\s+cookies", re.IGNORECASE),
            ).click(timeout=2_000)
        except PlaywrightTimeoutError:
            pass


def _prices_from_text(text: str) -> list[float]:
    prices = []
    for match in _PRICE_PATTERN.finditer(text):
        value = match.group(1) or match.group(2)
        prices.append(float(value.replace(",", ".")))
    return prices


def _first_visible(locator: Any) -> Any | None:
    if not locator.count():
        return None

    candidate = locator.first
    return candidate if candidate.is_visible() else None


def _locator_text(locator: Any) -> str:
    try:
        text = locator.inner_text().strip()
    except Exception:
        text = ""
    if text:
        return text

    for attribute in ("aria-label", "title"):
        try:
            value = locator.get_attribute(attribute)
        except Exception:
            continue
        if value:
            return value.strip()
    return ""


def _admission_from_prices(prices: list[float]) -> Admission:
    if not prices:
        raise ValueError("Admission requires at least one price")

    return Admission(
        is_free=False,
        price_min=min(prices),
        price_max=max(prices),
        currency="PLN",
    )
