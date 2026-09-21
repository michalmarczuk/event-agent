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
        return events
