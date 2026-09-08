from dataclasses import dataclass


@dataclass
class Event:
    id: str
    name: str
    date: str | None
    city: str | None
    venue: str | None
    url: str | None
    source: str


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
    name: str
    category: str
    date: str | None
    time: str | None
    city: str | None
    venue: str | None
    reason: str
    url: str | None
