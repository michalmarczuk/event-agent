"""Deterministic aggregation of configured event discovery sources."""

import logging
from collections.abc import Sequence

try:
    from .event_source import EventSource
    from .models import Event
except ImportError:  # pragma: no cover - supports script execution
    from event_source import EventSource
    from models import Event


logger = logging.getLogger(__name__)

_SOURCE_PRIORITY = {
    "ticketmaster": 0,
    "mosir_tychy": 1,
}


class EventCatalog:
    """Search configured sources in order while isolating partial failures."""

    def __init__(self, sources: Sequence[EventSource]) -> None:
        self._sources = tuple(sources)

    def search_events(
        self,
        city: str,
        days_ahead: int,
        seen_event_ids: set[str] | None = None,
    ) -> list[Event]:
        """Return merged results unless every configured source fails."""
        events = []
        successful_sources = 0
        for source in self._sources:
            try:
                events.extend(
                    source.search_events(city, days_ahead, seen_event_ids)
                )
            except Exception:
                logger.warning(
                    "Event source search failed source=%s",
                    source.source,
                    exc_info=True,
                )
            else:
                successful_sources += 1

        if successful_sources == 0:
            raise RuntimeError("All event sources failed")
        return _deduplicate_events(events)


def _deduplicate_events(events: list[Event]) -> list[Event]:
    """Keep one provider-authoritative event for conservative cross-source matches."""
    deduplicated: list[Event] = []
    for event in events:
        key = _deduplication_key(event)
        if key is None:
            deduplicated.append(event)
            continue

        matches = [
            existing
            for existing in deduplicated
            if existing.source != event.source
            and _deduplication_key(existing) == key
        ]
        if not matches:
            deduplicated.append(event)
            continue

        kept_event = min(matches, key=_source_priority)
        if _source_priority(event) >= _source_priority(kept_event):
            _log_dropped_duplicate(kept_event, event)
            continue

        for matched_event in matches:
            deduplicated.remove(matched_event)
            _log_dropped_duplicate(event, matched_event)
        deduplicated.append(event)
    return deduplicated


def _deduplication_key(event: Event) -> tuple[str, str, str, str] | None:
    name = _normalize_text(event.name)
    event_date = _normalize_text(event.date)
    city = _normalize_text(event.city)
    venue = _normalize_text(event.venue)
    if not all((name, event_date, city, venue)):
        return None
    return name, event_date, city, venue


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split()).casefold()
    return normalized or None


def _source_priority(event: Event) -> int:
    return _SOURCE_PRIORITY.get(event.source, len(_SOURCE_PRIORITY))


def _log_dropped_duplicate(kept_event: Event, dropped_event: Event) -> None:
    logger.info(
        "Dropped duplicate event kept_id=%s dropped_id=%s",
        kept_event.id,
        dropped_event.id,
        extra={
            "event.action": "event_catalog_deduplicate",
            "event.outcome": "dropped",
            "event.reason": "cross_source_duplicate",
            "event.kept_id": kept_event.id,
            "event.kept_source": kept_event.source,
            "event.dropped_id": dropped_event.id,
            "event.dropped_source": dropped_event.source,
        },
    )
