import logging

import pytest

from src.event_catalog import EventCatalog
from src.models import Event
from src.sources.ticketmaster import TicketmasterSource


def _event(
    source: str,
    source_event_id: str,
    *,
    name: str | None = None,
    date: str | None = None,
    city: str | None = "Tychy",
    venue: str | None = None,
) -> Event:
    return Event(
        id=f"{source}:{source_event_id}",
        name=name or f"{source} event",
        date=date,
        city=city,
        venue=venue,
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


def test_catalog_merges_distinct_sources_in_configured_order():
    ticketmaster = _Source("ticketmaster", [_event("ticketmaster", "abc123")])
    mosir = _Source("mosir_tychy", [_event("mosir_tychy", "abc123")])

    events = EventCatalog([ticketmaster, mosir]).search_events("Tychy", 30)

    assert [event.id for event in events] == [
        "ticketmaster:abc123",
        "mosir_tychy:abc123",
    ]
    assert ticketmaster.calls == [("Tychy", 30, None)]
    assert mosir.calls == [("Tychy", 30, None)]


def test_catalog_deduplicates_normalized_cross_source_events_with_ticketmaster_priority(
    caplog,
):
    caplog.set_level(logging.INFO)
    ticketmaster_event = _event(
        "ticketmaster",
        "abc123",
        name="Koncert ABC",
        date="2026-10-10",
        venue="Mediateka",
    )
    mosir_event = _event(
        "mosir_tychy",
        "1836",
        name=" koncert   abc ",
        date="2026-10-10",
        city="tychy",
        venue="  Mediateka ",
    )

    events = EventCatalog(
        [
            _Source("mosir_tychy", [mosir_event]),
            _Source("ticketmaster", [ticketmaster_event]),
        ]
    ).search_events("Tychy", 30)

    assert events == [ticketmaster_event]
    record = next(
        record
        for record in caplog.records
        if record.msg == "Dropped duplicate event kept_id=%s dropped_id=%s"
    )
    assert getattr(record, "event.kept_id") == "ticketmaster:abc123"
    assert getattr(record, "event.kept_source") == "ticketmaster"
    assert getattr(record, "event.dropped_id") == "mosir_tychy:1836"
    assert getattr(record, "event.dropped_source") == "mosir_tychy"


@pytest.mark.parametrize(
    "different_field, ticketmaster_value, mosir_value",
    [
        ("date", "2026-10-10", "2026-10-11"),
        ("venue", "Mediateka", "Stadion Zimowy"),
    ],
)
def test_catalog_keeps_cross_source_events_when_required_metadata_differs(
    different_field,
    ticketmaster_value,
    mosir_value,
):
    common = {
        "name": "Koncert ABC",
        "date": "2026-10-10",
        "city": "Tychy",
        "venue": "Mediateka",
    }
    ticketmaster_event = _event(
        "ticketmaster",
        "abc123",
        **(common | {different_field: ticketmaster_value}),
    )
    mosir_event = _event(
        "mosir_tychy",
        "1836",
        **(common | {different_field: mosir_value}),
    )

    events = EventCatalog(
        [
            _Source("ticketmaster", [ticketmaster_event]),
            _Source("mosir_tychy", [mosir_event]),
        ]
    ).search_events("Tychy", 30)

    assert events == [ticketmaster_event, mosir_event]


@pytest.mark.parametrize("missing_field", ["date", "venue"])
def test_catalog_keeps_cross_source_events_when_required_metadata_is_missing(
    missing_field,
):
    ticketmaster_event = _event(
        "ticketmaster",
        "abc123",
        name="Koncert ABC",
        date="2026-10-10",
        venue="Mediateka",
    )
    mosir_metadata = {"date": "2026-10-10", "venue": "Mediateka"}
    mosir_metadata[missing_field] = None
    mosir_event = _event(
        "mosir_tychy",
        "1836",
        name="Koncert ABC",
        **mosir_metadata,
    )

    events = EventCatalog(
        [
            _Source("ticketmaster", [ticketmaster_event]),
            _Source("mosir_tychy", [mosir_event]),
        ]
    ).search_events("Tychy", 30)

    assert events == [ticketmaster_event, mosir_event]


def test_catalog_keeps_same_source_events_with_identical_metadata():
    first_event = _event(
        "ticketmaster",
        "abc123",
        name="Koncert ABC",
        date="2026-10-10",
        venue="Mediateka",
    )
    second_event = _event(
        "ticketmaster",
        "def456",
        name="Koncert ABC",
        date="2026-10-10",
        venue="Mediateka",
    )

    events = EventCatalog(
        [_Source("ticketmaster", [first_event, second_event])]
    ).search_events("Tychy", 30)

    assert events == [first_event, second_event]


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
