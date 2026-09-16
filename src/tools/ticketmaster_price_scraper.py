import logging
import re
import time
from typing import Any

from camoufox.sync_api import NewBrowser
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

try:
    from ..config import load_scraper_proxy_url
    from ..models import Admission
except ImportError:  # pragma: no cover - supports script execution
    from config import load_scraper_proxy_url
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
_TICKET_SECTION_PATTERN = _label_pattern(
    _ENGLISH_TICKET_SECTION_LABELS + _POLISH_TICKET_SECTION_LABELS,
    whole_word_labels=_POLISH_TICKET_SECTION_LABELS[-1:],
)
_BEST_AVAILABLE_PATTERN = _label_pattern(
    _ENGLISH_BEST_AVAILABLE_LABELS + _POLISH_BEST_AVAILABLE_LABELS
)
_POLISH_UI_PATTERN = _label_pattern(
    _POLISH_TICKET_SECTION_LABELS + _POLISH_BEST_AVAILABLE_LABELS,
    whole_word_labels=_POLISH_TICKET_SECTION_LABELS[-1:],
)
_ENGLISH_UI_PATTERN = _label_pattern(
    _ENGLISH_TICKET_SECTION_LABELS + _ENGLISH_BEST_AVAILABLE_LABELS
)
_POLISH_CURRENCY_PATTERN = re.compile(r"\bzł\b", re.IGNORECASE)
_CONSENT_ACCEPT_PATTERN = re.compile(
    r"^\s*(?:Accept\s+Cookies|Accept|Akceptuję)\s*$",
    re.IGNORECASE,
)
_BLOCKED_PAGE_PATTERN = re.compile(
    r"identity\s+verified|not\s+a\s+bot|captcha|waiting\s+room|"
    r"access\s+denied|verify\s+you\s+are\s+human",
    re.IGNORECASE,
)
_ACCESSIBILITY_SKIP_TICKET_PATTERN = re.compile(
    r"^\s*(?:pomiń|skip)\b.*?\b(?:bilet\w*|tickets?)\b",
    re.IGNORECASE,
)
_READINESS_TIMEOUT_MS = 20_000
_READINESS_POLL_INTERVAL_MS = 500
_MIN_READY_BODY_TEXT_LENGTH = 20


class TicketmasterPriceScraper:
    """Extract visible Ticketmaster ticket prices from public event pages."""

    def __init__(self, browser: Any | None = None, timeout_ms: int = 15_000) -> None:
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
        """Return visible PLN admission pricing or ``None`` when unavailable."""
        started_at = time.monotonic()
        diagnostics: dict[str, object] = {
            "event.action": "ticketmaster_price_scrape",
        }

        def outcome_fields(
            outcome: str,
            reason: str | None = None,
        ) -> dict[str, object]:
            fields = {
                **diagnostics,
                "event.outcome": outcome,
                "scraper.elapsed_ms": int(
                    (time.monotonic() - started_at) * 1_000
                ),
            }
            if reason is not None:
                fields["event.reason"] = reason
            return fields

        if not event_url:
            logger.warning(
                "Ticketmaster price scrape skipped: missing event URL",
                extra=outcome_fields("failure", "extraction_failed"),
            )
            return None

        diagnostics["url.original"] = event_url
        logger.info(
            "Starting Ticketmaster price scrape url=%s",
            event_url,
            extra=diagnostics,
        )
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
                    logger.warning(
                        "Ticketmaster navigation timed out url=%s",
                        event_url,
                        extra=outcome_fields("failure", "navigation_failed"),
                    )
                    return None
                except Exception:
                    logger.warning(
                        "Ticketmaster navigation failed url=%s",
                        event_url,
                        exc_info=True,
                        extra=outcome_fields("failure", "navigation_failed"),
                    )
                    return None

                logger.info(
                    "Ticketmaster page loaded url=%s",
                    event_url,
                    extra=diagnostics,
                )
                page_ready = self._wait_for_ticketmaster_content(page)
                self._accept_cookies(page)
                body = page.locator("body")
                body_text = body.inner_text(timeout=self._timeout_ms)
                page_variant = self._detect_page_variant(page, body_text)
                diagnostics["scraper.page_language"] = page_variant
                logger.info(
                    "Ticketmaster page language/variant=%s url=%s",
                    page_variant,
                    event_url,
                    extra=diagnostics,
                )
                if _BLOCKED_PAGE_PATTERN.search(body_text):
                    logger.warning(
                        "Ticketmaster blocked/security page detected url=%s",
                        event_url,
                        extra=outcome_fields("failure", "extraction_failed"),
                    )
                    return None

                ticket_section, marker_text = self._find_ticket_section(page)
                if marker_text is not None:
                    diagnostics["scraper.ticket_marker"] = marker_text
                    logger.info(
                        "Ticketmaster ticket section marker matched text=%r url=%s",
                        marker_text,
                        event_url,
                        extra=diagnostics,
                    )
                prices = self._prices_from_visible_area(
                    ticket_section,
                    body_text,
                )
                diagnostics["scraper.direct_price_count"] = len(prices)
                diagnostics["scraper.best_available_found"] = False
                logger.info(
                    "Ticketmaster price extraction phase=direct count=%d url=%s",
                    len(prices),
                    event_url,
                    extra=diagnostics,
                )
                if not prices:
                    control, control_text = self._find_best_available_control(page)
                    if control is None:
                        failure_reason = (
                            "no_price_or_best_available"
                            if page_ready or (
                                marker_text is not None
                                and not _ACCESSIBILITY_SKIP_TICKET_PATTERN.search(
                                    marker_text
                                )
                            )
                            else "page_not_ready"
                        )
                        logger.warning(
                            "Ticketmaster no price found and no best-available control url=%s",
                            event_url,
                            extra=outcome_fields("failure", failure_reason),
                        )
                    else:
                        diagnostics["scraper.best_available_found"] = True
                        logger.info(
                            "Ticketmaster best-available control matched text=%r url=%s",
                            control_text,
                            event_url,
                            extra=diagnostics,
                        )
                        try:
                            control.click(timeout=self._timeout_ms)
                        except Exception:
                            logger.warning(
                                "Ticketmaster best-available control click failed url=%s",
                                event_url,
                                exc_info=True,
                                extra=outcome_fields(
                                    "failure", "extraction_failed"
                                ),
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
                                extra=diagnostics,
                            )
                            if not prices:
                                logger.warning(
                                    "Ticketmaster no price found after best-available click url=%s",
                                    event_url,
                                    extra=outcome_fields(
                                        "failure", "extraction_failed"
                                    ),
                                )

                if not prices:
                    return None

                admission = Admission(
                    is_free=False,
                    price_min=min(prices),
                    price_max=max(prices),
                    currency="PLN",
                )
                diagnostics.update(
                    {
                        "scraper.price_min": admission.price_min,
                        "scraper.price_max": admission.price_max,
                        "scraper.currency": admission.currency,
                    }
                )
                logger.info(
                    "Ticketmaster final admission=%s url=%s",
                    admission,
                    event_url,
                    extra=outcome_fields("success"),
                )
                return admission
            finally:
                page.close()
        except PlaywrightTimeoutError:
            logger.warning(
                "Ticketmaster price scrape timed out: %s",
                event_url,
                extra=outcome_fields("failure", "extraction_failed"),
            )
        except Exception:
            logger.warning(
                "Ticketmaster price scrape failed: %s",
                event_url,
                exc_info=True,
                extra=outcome_fields("failure", "extraction_failed"),
            )
        return None

    def _ensure_browser(self):
        if self._browser is None:
            self._playwright = sync_playwright().start()
            proxy_url = load_scraper_proxy_url()
            proxy_options = (
                {"proxy": {"server": proxy_url}}
                if proxy_url
                else {}
            )
            self._browser = NewBrowser(
                self._playwright,
                headless=False,
                locale="pl-PL",
                os="macos",
                **proxy_options,
            )
        return self._browser

    def _ensure_context(self):
        if self._context is None:
            self._context = self._ensure_browser().new_context(
                locale="pl-PL",
                timezone_id="Europe/Warsaw",
                viewport={"width": 1440, "height": 900},
            )
        return self._context

    def _wait_for_ticketmaster_content(self, page: Any) -> bool:
        body = page.locator("body")
        poll_count = _READINESS_TIMEOUT_MS // _READINESS_POLL_INTERVAL_MS

        for attempt in range(poll_count + 1):
            try:
                body_text = body.inner_text(timeout=_READINESS_POLL_INTERVAL_MS)
                has_ticket_signal = (
                    bool(_prices_from_text(body_text))
                    or self._find_best_available_control(page)[0] is not None
                )
            except PlaywrightTimeoutError:
                body_text = ""
                has_ticket_signal = False

            if (
                len(body_text.strip()) >= _MIN_READY_BODY_TEXT_LENGTH
                and has_ticket_signal
            ):
                return True
            if attempt < poll_count:
                page.wait_for_timeout(_READINESS_POLL_INTERVAL_MS)
        return False

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
        marker = _first_match_if_visible(
            page.get_by_role("heading", name=_TICKET_SECTION_PATTERN)
        )
        if marker is None:
            marker = _first_match_if_visible(
                page.get_by_text(_TICKET_SECTION_PATTERN)
            )
        if marker is None:
            return None, None

        ticket_section = marker.locator("xpath=../..").locator("xpath=..")
        return ticket_section, _locator_text(marker)

    @staticmethod
    def _find_best_available_control(page: Any) -> tuple[Any | None, str | None]:
        for role in ("button", "tab"):
            control = _first_match_if_visible(
                page.get_by_role(role, name=_BEST_AVAILABLE_PATTERN)
            )
            if control is not None:
                return control, _locator_text(control)

        control = _first_match_if_visible(
            page.get_by_text(_BEST_AVAILABLE_PATTERN)
        )
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
            control = page.get_by_role(
                "button", name=_CONSENT_ACCEPT_PATTERN
            ).first
            control.wait_for(state="visible", timeout=2_000)
        except PlaywrightTimeoutError:
            return

        matched_text = _locator_text(control)
        logger.info(
            "Ticketmaster consent control found matched text=%r",
            matched_text,
        )

        try:
            control.click(timeout=2_000)
        except Exception:
            logger.warning(
                "Ticketmaster consent control click failed matched text=%r",
                matched_text,
                exc_info=True,
            )
            return

        logger.info("Ticketmaster consent clicked matched text=%r", matched_text)
        try:
            page.wait_for_timeout(1_000)
        except Exception:
            logger.warning(
                "Ticketmaster post-consent wait failed",
                exc_info=True,
            )


def _prices_from_text(text: str) -> list[float]:
    return [
        float((match.group(1) or match.group(2)).replace(",", "."))
        for match in _PRICE_PATTERN.finditer(text)
    ]


def _first_match_if_visible(locator: Any) -> Any | None:
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
