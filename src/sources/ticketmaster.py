"""Adapter exposing Ticketmaster through the common discovery contract."""

try:
    from ..models import Event
    from ..tools.ticketmaster import TicketmasterClient
except ImportError:  # pragma: no cover - supports script execution
    from models import Event
    from tools.ticketmaster import TicketmasterClient


class TicketmasterSource:
    """Delegate configured-location discovery to Ticketmaster."""

    source = "ticketmaster"

    def __init__(self, client: TicketmasterClient) -> None:
        self._client = client

    def search_events(
        self,
        city: str,
        days_ahead: int,
        seen_event_ids: set[str] | None = None,
    ) -> list[Event]:
        """Return Ticketmaster events for the configured search location."""
        del city
        return self._client.search_events(days_ahead, seen_event_ids)
