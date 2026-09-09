from dataclasses import dataclass


@dataclass(frozen=True)
class Admission:
    is_free: bool | None
    price_min: float | None = None
    price_max: float | None = None
    currency: str | None = None
    note: str | None = None


@dataclass
class Event:
    id: str
    name: str
    date: str | None
    city: str | None
    venue: str | None
    url: str | None
    source: str
    admission: Admission | None = None


@dataclass
class EventDetails:
    name: str | None
    date: str | None
    time: str | None
    venue: str | None
    city: str | None
    url: str | None


@dataclass
class Recommendation:
    event_id: str
    name: str
    category: str
    date: str | None
    time: str | None
    city: str | None
    venue: str | None
    reason: str
    url: str | None
    admission: Admission | None = None
