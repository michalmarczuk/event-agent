"""Deterministic aggregation of configured event discovery sources."""

import logging
from collections.abc import Sequence
from time import monotonic_ns

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
        events: list[Event] = []
        successful_sources = 0
        failed_sources = 0
        for source in self._sources:
            started_at_ns = monotonic_ns()
            try:
                source_events = source.search_events(
                    city, days_ahead, seen_event_ids
                )
                source_event_count = len(source_events)
                events.extend(source_events)
            except Exception as error:
                failed_sources += 1
                logger.warning(
                    "Event source search failed source=%s",
                    source.source,
                    extra={
                        "event.action": "event_source_search",
                        "event.outcome": "failure",
                        "event.reason": type(error).__name__,
                        "event_source.name": source.source,
                        "event_source.duration_ms": _duration_ms(started_at_ns),
                        "event_source.event_count": 0,
                    },
                )
            else:
                successful_sources += 1
                logger.info(
                    "Event source search completed source=%s",
                    source.source,
                    extra={
                        "event.action": "event_source_search",
                        "event.outcome": "success",
                        "event_source.name": source.source,
                        "event_source.duration_ms": _duration_ms(started_at_ns),
                        "event_source.event_count": source_event_count,
                    },
                )

        if successful_sources == 0:
            self._log_search_summary(
                outcome="failure",
                successful_sources=successful_sources,
                failed_sources=failed_sources,
                raw_event_count=len(events),
                duplicate_count=0,
                final_event_count=0,
            )
            raise RuntimeError("All event sources failed")

        deduplicated_events, duplicate_count = _deduplicate_events(events)
        self._log_search_summary(
            outcome="success",
            successful_sources=successful_sources,
            failed_sources=failed_sources,
            raw_event_count=len(events),
            duplicate_count=duplicate_count,
            final_event_count=len(deduplicated_events),
        )
        return deduplicated_events

    def _log_search_summary(
        self,
        *,
        outcome: str,
        successful_sources: int,
        failed_sources: int,
        raw_event_count: int,
        duplicate_count: int,
        final_event_count: int,
    ) -> None:
        logger.log(
            logging.INFO if outcome == "success" else logging.ERROR,
            "Event catalog search completed",
            extra={
                "event.action": "event_catalog_search",
                "event.outcome": outcome,
                "event.reason": (
                    None if outcome == "success" else "all_sources_failed"
                ),
                "event_catalog.source_count": len(self._sources),
                "event_catalog.successful_source_count": successful_sources,
                "event_catalog.failed_source_count": failed_sources,
                "event_catalog.raw_event_count": raw_event_count,
                "event_catalog.duplicate_count": duplicate_count,
                "event_catalog.final_event_count": final_event_count,
                "event_catalog.degraded": (
                    successful_sources > 0 and failed_sources > 0
                ),
            },
        )


def _deduplicate_events(events: list[Event]) -> tuple[list[Event], int]:
    """Keep one provider-authoritative event for conservative cross-source matches."""
    deduplicated: list[Event] = []
    duplicate_count = 0
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
            duplicate_count += 1
            continue

        for matched_event in matches:
            deduplicated.remove(matched_event)
            _log_dropped_duplicate(event, matched_event)
            duplicate_count += 1
        deduplicated.append(event)
    return deduplicated, duplicate_count


def _duration_ms(started_at_ns: int) -> int:
    """Return elapsed monotonic time rounded down to whole milliseconds."""
    return (monotonic_ns() - started_at_ns) // 1_000_000


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
