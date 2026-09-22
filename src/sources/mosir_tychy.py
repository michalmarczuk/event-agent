"""HTTP discovery source for the server-rendered MOSiR Tychy events site."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests

try:
    from ..event_identity import build_event_id
    from ..models import Event
except ImportError:  # pragma: no cover - supports script execution
    from event_identity import build_event_id
    from models import Event


logger = logging.getLogger(__name__)

_TIMEZONE = ZoneInfo("Europe/Warsaw")
_DEFAULT_BASE_URL = "https://mosir.tychy.pl"
_CARD_ID_PATTERN = re.compile(r"/(\d+)(?:-[^/?#]+)?$")


class MosirTychySource:
    """Discover MOSiR Tychy events through its public rendered pages."""

    source = "mosir_tychy"

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE_URL,
        *,
        today_provider: Callable[[], date] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._today_provider = today_provider or self._current_local_date

    def search_events(
        self,
        city: str,
        days_ahead: int,
        seen_event_ids: set[str] | None = None,
    ) -> list[Event]:
        """Return MOSiR Tychy events in the requested local date window."""
        del seen_event_ids
        if city.strip().casefold() != "tychy":
            return []

        start_date = self._today_provider()
        end_date = start_date + timedelta(days=days_ahead)
        events = []
        for year, month in _months_between(start_date, end_date):
            marked_dates = self._calendar_dates(year, month)
            for event_date in marked_dates:
                if start_date <= event_date <= end_date:
                    events.extend(self._events_for_date(event_date))
        return events

    @staticmethod
    def _current_local_date() -> date:
        return datetime.now(_TIMEZONE).date()

    def _calendar_dates(self, year: int, month: int) -> list[date]:
        payload = self._get_json(
            f"{self._base_url}/item/calendar",
            {"year": year, "month": month},
        )
        if not isinstance(payload, list):
            raise RuntimeError("MOSiR Tychy calendar returned an invalid payload")

        marked_dates = []
        for entry in payload:
            if not isinstance(entry, dict) or not isinstance(entry.get("date"), str):
                continue
            try:
                marked_dates.append(date.fromisoformat(entry["date"]))
            except ValueError:
                logger.warning("MOSiR Tychy skipped malformed calendar date")
        return sorted(set(marked_dates))

    def _events_for_date(self, event_date: date) -> list[Event]:
        html = self._get_text(
            f"{self._base_url}/wydarzenia",
            {"date": event_date.isoformat()},
        )
        cards, has_listing = _parse_event_cards(html)
        if not cards and not has_listing:
            raise RuntimeError("MOSiR Tychy events page layout was not recognized")

        events = []
        for card in cards:
            try:
                event = self._event_from_card(card, event_date)
            except ValueError:
                logger.warning("MOSiR Tychy skipped malformed event card")
            else:
                events.append(event)
        return events

    def _event_from_card(self, card: _EventCard, event_date: date) -> Event:
        detail_url = urljoin(f"{self._base_url}/", card.href)
        source_event_id = _source_event_id(detail_url)
        detail_html = self._get_text(detail_url)
        canonical_url, venue = _parse_event_details(detail_html, detail_url)
        return Event(
            id=build_event_id(self.source, source_event_id),
            name=card.title,
            date=event_date.isoformat(),
            city="Tychy",
            venue=venue,
            url=canonical_url,
            source=self.source,
            source_event_id=source_event_id,
            admission=None,
        )

    def _get_json(self, url: str, params: dict[str, int]) -> object:
        response = self._request(url, params)
        try:
            return response.json()
        except ValueError as error:
            raise RuntimeError("MOSiR Tychy returned invalid JSON") from error

    def _get_text(
        self,
        url: str,
        params: dict[str, str] | None = None,
    ) -> str:
        return self._request(url, params).text

    @staticmethod
    def _request(
        url: str,
        params: dict[str, int | str] | None = None,
    ) -> requests.Response:
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            detail = (
                type(error).__name__
                if error.response is None
                else f"HTTP {error.response.status_code}"
            )
            raise RuntimeError(f"MOSiR Tychy request failed ({detail})") from None


class _EventCardParser(HTMLParser):
    """Extract event-card links while recognizing the listing container."""

    def __init__(self) -> None:
        super().__init__()
        self.cards: list[_EventCard] = []
        self.has_listing = False
        self._card_depth = 0
        self._div_card_stack: list[bool] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = attributes.get("class") or ""
        if tag == "div":
            is_card = "item-box-wrapper" in classes
            self._div_card_stack.append(is_card)
            if is_card or "list-view" in classes or "events-list" in classes:
                self.has_listing = True
            if is_card:
                self._card_depth += 1
        if tag != "a" or self._card_depth == 0:
            return
        title = attributes.get("title")
        href = attributes.get("href")
        if title and href:
            self.cards.append(_EventCard(title=title.strip(), href=href))

    def handle_endtag(self, tag: str) -> None:
        if tag != "div" or not self._div_card_stack:
            return
        if self._div_card_stack.pop():
            self._card_depth -= 1


class _EventDetailsParser(HTMLParser):
    """Extract canonical URL and venue from a MOSiR detail page."""

    def __init__(self) -> None:
        super().__init__()
        self.canonical_url: str | None = None
        self._heading_tag: str | None = None
        self._heading_parts: list[str] = []
        self._venue_pending = False
        self._venue_anchor_depth = 0
        self._venue_title: str | None = None
        self._venue_parts: list[str] = []
        self.venue: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "meta" and attributes.get("property") == "og:url":
            self.canonical_url = attributes.get("content")

        if tag in {"h2", "h3", "div", "span"}:
            classes = attributes.get("class") or ""
            if "event-venue" in classes:
                self._venue_pending = True
        if self._heading_tag is not None:
            return
        if tag in {"h2", "h3"}:
            self._heading_tag = tag
            self._heading_parts = []
            return
        if self._venue_pending and tag == "a":
            self._venue_pending = False
            self._venue_anchor_depth = 1
            self._venue_title = attributes.get("title")
            self._venue_parts = []

    def handle_endtag(self, tag: str) -> None:
        if self._heading_tag == tag:
            label = " ".join(self._heading_parts).split()
            if " ".join(label).casefold() == "miejsce wydarzenia":
                self._venue_pending = True
            self._heading_tag = None
            self._heading_parts = []
            return
        if self._venue_anchor_depth and tag == "a":
            self._venue_anchor_depth -= 1
            if self._venue_anchor_depth == 0:
                venue = self._venue_title or " ".join(self._venue_parts)
                self.venue = " ".join(venue.split()) or None
                self._venue_title = None
                self._venue_parts = []

    def handle_data(self, data: str) -> None:
        normalized = " ".join(data.split())
        if self._heading_tag is not None and normalized:
            self._heading_parts.append(normalized)
        elif self._venue_anchor_depth and normalized:
            self._venue_parts.append(normalized)


class _EventCard:
    def __init__(self, title: str, href: str) -> None:
        self.title = title
        self.href = href


def _months_between(start_date: date, end_date: date) -> list[tuple[int, int]]:
    months = []
    year, month = start_date.year, start_date.month
    while (year, month) <= (end_date.year, end_date.month):
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def _parse_event_cards(html: str) -> tuple[list[_EventCard], bool]:
    parser = _EventCardParser()
    parser.feed(html)
    parser.close()
    return parser.cards, parser.has_listing


def _parse_event_details(html: str, requested_url: str) -> tuple[str, str | None]:
    parser = _EventDetailsParser()
    parser.feed(html)
    parser.close()
    return parser.canonical_url or requested_url, parser.venue


def _source_event_id(url: str) -> str:
    match = _CARD_ID_PATTERN.search(url)
    if match is None:
        raise ValueError("MOSiR Tychy event URL does not contain a CMS ID")
    return match.group(1)
