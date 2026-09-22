from dataclasses import dataclass


@dataclass(frozen=True)
class Admission:
    """Normalized admission information supplied by a provider or scraper."""

    is_free: bool | None
    price_min: float | None = None
    price_max: float | None = None
    currency: str | None = None
    note: str | None = None


@dataclass
class Event:
    """Provider-neutral event returned by discovery sources.

    ``id`` is a stable namespaced identity across the application boundary.
    """

    id: str
    name: str
    date: str | None
    city: str | None
    venue: str | None
    url: str | None
    source: str
    source_event_id: str
    admission: Admission | None = None


@dataclass
class EventDetails:
    """Provider details used to complete an already grounded event."""

    name: str | None
    date: str | None
    time: str | None
    venue: str | None
    city: str | None
    url: str | None


@dataclass
class Recommendation:
    """Final event recommendation with provider-authoritative metadata."""

    event_id: str
    source: str
    name: str
    category: str
    date: str | None
    time: str | None
    city: str | None
    venue: str | None
    reason: str
    url: str | None
    admission: Admission | None = None
