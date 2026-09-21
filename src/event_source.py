"""Provider-neutral contracts for event discovery sources."""

from typing import Protocol

try:
    from .models import Event
except ImportError:  # pragma: no cover - supports script execution
    from models import Event


class EventSource(Protocol):
    """A provider that discovers normalized events for one city."""

    source: str

    def search_events(
        self,
        city: str,
        days_ahead: int,
        seen_event_ids: set[str] | None = None,
    ) -> list[Event]:
        """Return events available from this provider."""
