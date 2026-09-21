import pytest

from src.event_catalog import EventCatalog
from src.models import Event
from src.sources.ticketmaster import TicketmasterSource


def _event(source: str, source_event_id: str) -> Event:
    return Event(
        id=f"{source}:{source_event_id}",
        name=f"{source} event",
        date=None,
        city="Tychy",
        venue=None,
        url=None,
        source=source,
        source_event_id=source_event_id,
    )


class _Source:
    def __init__(self, source: str, result):
        self.source = source
        self._result = result
        self.calls = []

    def search_events(self, city, days_ahead, seen_event_ids=None):
        self.calls.append((city, days_ahead, seen_event_ids))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def test_catalog_merges_sources_in_configured_order_without_deduplication():
    ticketmaster = _Source("ticketmaster", [_event("ticketmaster", "abc123")])
    mosir = _Source("mosir_tychy", [_event("mosir_tychy", "abc123")])

    events = EventCatalog([ticketmaster, mosir]).search_events("Tychy", 30)

    assert [event.id for event in events] == [
        "ticketmaster:abc123",
        "mosir_tychy:abc123",
    ]
    assert ticketmaster.calls == [("Tychy", 30, None)]
    assert mosir.calls == [("Tychy", 30, None)]


def test_empty_successful_source_does_not_make_catalog_fail():
    catalog = EventCatalog(
        [
            _Source("ticketmaster", []),
            _Source("mosir_tychy", [_event("mosir_tychy", "1836")]),
        ]
    )

    events = catalog.search_events("Tychy", 30)

    assert [event.id for event in events] == ["mosir_tychy:1836"]


def test_catalog_keeps_successful_source_results_after_partial_failure():
    catalog = EventCatalog(
        [
            _Source("ticketmaster", RuntimeError("unavailable")),
            _Source("mosir_tychy", [_event("mosir_tychy", "1836")]),
        ]
    )

    events = catalog.search_events("Tychy", 30)

    assert [event.id for event in events] == ["mosir_tychy:1836"]


def test_catalog_fails_when_every_configured_source_fails():
    catalog = EventCatalog(
        [
            _Source("ticketmaster", RuntimeError("unavailable")),
            _Source("mosir_tychy", RuntimeError("unavailable")),
        ]
    )

    with pytest.raises(RuntimeError, match="All event sources failed"):
        catalog.search_events("Tychy", 30)


def test_ticketmaster_adapter_preserves_provider_search_contract():
    calls = []

    class _Client:
        def search_events(self, days_ahead, seen_event_ids=None):
            calls.append((days_ahead, seen_event_ids))
            return [_event("ticketmaster", "abc123")]

    events = TicketmasterSource(_Client()).search_events(
        "Tychy",
        30,
        {"ticketmaster:seen"},
    )

    assert [event.id for event in events] == ["ticketmaster:abc123"]
    assert calls == [(30, {"ticketmaster:seen"})]
