"""Run a production-image smoke probe against the live MOSiR Tychy source."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from urllib.parse import urlparse

from src.events.models import Event
from src.integrations.mosir_tychy.source import MosirTychySource

_SOURCE = "mosir_tychy"
_CITY = "Tychy"
_DAYS_AHEAD = 30


class _InvalidEventContract(ValueError):
    """A live source returned an event outside the normalized contract."""


def validate_events(events: Sequence[Event]) -> None:
    """Validate provider-authoritative fields without assuming events exist."""
    for event in events:
        if event.source != _SOURCE:
            raise _InvalidEventContract
        if (
            not isinstance(event.source_event_id, str)
            or not event.source_event_id.strip()
        ):
            raise _InvalidEventContract
        if event.id != f"{_SOURCE}:{event.source_event_id}":
            raise _InvalidEventContract
        if event.city != _CITY:
            raise _InvalidEventContract
        if event.admission is not None:
            raise _InvalidEventContract
        if not _is_mosir_url(event.url):
            raise _InvalidEventContract
        if event.venue is not None and (
            not isinstance(event.venue, str) or not event.venue.strip()
        ):
            raise _InvalidEventContract


def _is_mosir_url(url: str | None) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").casefold()
    return parsed.scheme in {"http", "https"} and (
        hostname == "mosir.tychy.pl" or hostname.endswith(".mosir.tychy.pl")
    )


def main() -> int:
    """Execute the live discovery probe and return a process exit status."""
    try:
        events = MosirTychySource().search_events(_CITY, _DAYS_AHEAD)
        validate_events(events)
    except _InvalidEventContract:
        print("MOSIR_LIVE_SMOKE_FAILED reason=invalid_event_contract", file=sys.stderr)
        return 1
    except Exception as error:
        print(
            f"MOSIR_LIVE_SMOKE_FAILED reason={type(error).__name__}",
            file=sys.stderr,
        )
        return 1

    print(f"MOSIR_LIVE_SMOKE_OK events={len(events)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
