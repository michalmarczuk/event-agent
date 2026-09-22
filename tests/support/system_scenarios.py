"""Declarative external-world configurations for black-box System Tests."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

_EVENT_ID = "event-happy-1"
_EVENT_NAME = "Fake Concert"
_EVENT_DATE = "2030-01-15"
_EVENT_TIME = "19:00:00"
_EVENT_CITY = "Tychy"
_EVENT_VENUE = "Fake Venue"


@dataclass(frozen=True)
class SystemScenario:
    """Describe the fake external world for one black-box System Test.

    Assertions intentionally live in the System Test layer; this object only
    configures provider responses and initial persistence state.
    """

    name: str
    ticketmaster_events: tuple[dict[str, Any], ...] = ()
    ticketmaster_status: HTTPStatus = HTTPStatus.OK
    ticketmaster_use_current_local_date: bool = False
    mosir_events: tuple[dict[str, Any], ...] = ()
    mosir_status: HTTPStatus = HTTPStatus.OK
    mosir_use_current_local_date: bool = False
    openai_status: HTTPStatus = HTTPStatus.OK
    ticketmaster_recommendation_id: str | None = None
    mosir_recommendation_id: str | None = None
    ungrounded_recommendation_id: str | None = None
    telegram_status: HTTPStatus = HTTPStatus.OK
    initial_history: tuple[str, ...] = ()


def _ticketmaster_event(
    event_id: str = _EVENT_ID,
    name: str = _EVENT_NAME,
    status: str = "onsale",
) -> dict[str, Any]:
    return {
        "id": event_id,
        "name": name,
        "dates": {
            "status": {"code": status},
            "start": {"localDate": _EVENT_DATE, "localTime": _EVENT_TIME},
        },
        "url": None,
        "_embedded": {
            "venues": [
                {"name": _EVENT_VENUE, "city": {"name": _EVENT_CITY}}
            ]
        },
    }


_HAPPY_EVENT = _ticketmaster_event()
_CANCELED_EVENT = _ticketmaster_event(
    event_id="event-canceled-1",
    name="Canceled Fake Concert",
    status="canceled",
)
_VALID_EVENT = _ticketmaster_event(
    event_id="event-valid-1",
    name="Valid Fake Concert",
)
_MULTIPLE_OTHER_EVENT = _ticketmaster_event(
    event_id="event-multiple-other-1",
    name="Other Fake Concert",
)
_MULTIPLE_SELECTED_EVENT = _ticketmaster_event(
    event_id="event-multiple-selected-1",
    name="Selected Fake Concert",
)
_MIXED_TICKETMASTER_EVENT = _ticketmaster_event(
    event_id="event-mixed-ticketmaster-1",
    name="Shared Fake Concert",
)
_MIXED_MOSIR_DUPLICATE = {
    "id": "9001",
    "name": " shared   fake concert ",
    "date": _EVENT_DATE,
    "city": "tychy",
    "venue": f" {_EVENT_VENUE} ",
    "detail_path": "/mosir/9001-shared-fake-concert",
    "url": "https://mosir.tychy.pl/wydarzenia/9001-shared-fake-concert",
}
_MIXED_MOSIR_UNIQUE = {
    "id": "9002",
    "name": "Unique MOSiR Event",
    "date": _EVENT_DATE,
    "city": _EVENT_CITY,
    "venue": "MOSiR Hall",
    "detail_path": "/mosir/9002-unique-mosir-event",
    "url": "https://mosir.tychy.pl/wydarzenia/9002-unique-mosir-event",
}
_PARTIAL_FAILURE_MOSIR_EVENT = {
    "id": "9100",
    "name": "Available MOSiR Event",
    "date": _EVENT_DATE,
    "city": _EVENT_CITY,
    "venue": "MOSiR Hall",
    "detail_path": "/mosir/9100-available-mosir-event",
    "url": "https://mosir.tychy.pl/wydarzenia/9100-available-mosir-event",
}


_SCENARIO_CONFIGURATIONS = (
    SystemScenario(
        name="happy_path",
        ticketmaster_events=(_HAPPY_EVENT,),
        ticketmaster_recommendation_id=_EVENT_ID,
    ),
    SystemScenario(
        name="telegram_failure",
        ticketmaster_events=(_HAPPY_EVENT,),
        ticketmaster_recommendation_id=_EVENT_ID,
        telegram_status=HTTPStatus.SERVICE_UNAVAILABLE,
    ),
    SystemScenario(name="no_events"),
    SystemScenario(
        name="previously_seen_event",
        ticketmaster_events=(_HAPPY_EVENT,),
        initial_history=(_EVENT_ID,),
    ),
    SystemScenario(
        name="canceled_event_filtering",
        ticketmaster_events=(_CANCELED_EVENT, _VALID_EVENT),
        ticketmaster_recommendation_id="event-valid-1",
    ),
    SystemScenario(
        name="openai_failure",
        openai_status=HTTPStatus.SERVICE_UNAVAILABLE,
    ),
    SystemScenario(
        name="multiple_events",
        ticketmaster_events=(_MULTIPLE_OTHER_EVENT, _MULTIPLE_SELECTED_EVENT),
        ticketmaster_recommendation_id="event-multiple-selected-1",
    ),
    SystemScenario(
        name="ticketmaster_failure",
        ticketmaster_status=HTTPStatus.SERVICE_UNAVAILABLE,
        mosir_status=HTTPStatus.SERVICE_UNAVAILABLE,
    ),
    SystemScenario(
        name="partial_source_failure",
        ticketmaster_status=HTTPStatus.SERVICE_UNAVAILABLE,
        mosir_events=(_PARTIAL_FAILURE_MOSIR_EVENT,),
        mosir_use_current_local_date=True,
        mosir_recommendation_id="9100",
    ),
    SystemScenario(
        name="invalid_recommendation_id",
        ticketmaster_events=(_HAPPY_EVENT,),
        ungrounded_recommendation_id="ticketmaster:unknown-event-id",
    ),
    SystemScenario(
        name="mixed_source_discovery",
        ticketmaster_events=(_MIXED_TICKETMASTER_EVENT,),
        ticketmaster_use_current_local_date=True,
        mosir_events=(_MIXED_MOSIR_DUPLICATE, _MIXED_MOSIR_UNIQUE),
        mosir_use_current_local_date=True,
        mosir_recommendation_id="9002",
    ),
)

SYSTEM_SCENARIOS = {
    scenario.name: scenario for scenario in _SCENARIO_CONFIGURATIONS
}
SYSTEM_SCENARIO_NAMES = tuple(SYSTEM_SCENARIOS)
DEFAULT_SYSTEM_SCENARIO = "happy_path"


def get_system_scenario(name: str) -> SystemScenario:
    """Return a configured scenario by its stable public name."""
    try:
        return SYSTEM_SCENARIOS[name]
    except KeyError as error:
        raise ValueError(f"Unsupported System Test scenario: {name}") from error


def main() -> None:
    """Expose scenario metadata to the shell black-box driver."""
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--names", action="store_true")
    group.add_argument("--initial-history")
    arguments = parser.parse_args()

    if arguments.names:
        print(" ".join(SYSTEM_SCENARIO_NAMES))
        return
    print(json.dumps(list(get_system_scenario(arguments.initial_history).initial_history)))


if __name__ == "__main__":
    main()
