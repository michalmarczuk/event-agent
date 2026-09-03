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
