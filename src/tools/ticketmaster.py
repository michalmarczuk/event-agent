import logging
from datetime import datetime, timedelta, timezone

import requests

try:
    from ..config import SearchLocation
    from ..event_identity import build_event_id
    from ..models import Admission, Event, EventDetails
except ImportError:  # pragma: no cover - supports script execution
    from config import SearchLocation
    from event_identity import build_event_id
    from models import Admission, Event, EventDetails

logger = logging.getLogger(__name__)

_SEARCH_PAGE_SIZE = 10
_MAX_SEARCH_PAGES = 5
_DEFAULT_API_BASE_URL = "https://app.ticketmaster.com/discovery/v2"


def _log_canceled_event(event_id: str) -> None:
    logger.info(
        "Dropped canceled Ticketmaster event event_id=%s",
        event_id,
        extra={
            "event.action": "ticketmaster_event_filter",
            "event.outcome": "dropped",
            "event.reason": "canceled",
            "ticketmaster.event_id": event_id,
        },
    )


def _get_ticketmaster_data(
    url: str,
    params: dict[str, str | int],
) -> dict:
    failure_detail = None
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as error:
        if error.response is None:
            failure_detail = type(error).__name__
        else:
            failure_detail = f"HTTP {error.response.status_code}"
    # Raise outside the handler so the credential-bearing request exception is
    # not retained as implicit exception context.
    raise RuntimeError(f"Ticketmaster request failed ({failure_detail})")


class TicketmasterClient:
    def __init__(
        self,
        api_key: str,
        location: SearchLocation,
        api_base_url: str = _DEFAULT_API_BASE_URL,
    ) -> None:
        self.api_key = api_key
        self.location = location
        self.api_base_url = api_base_url.rstrip("/")

    def search_events(
        self,
        days_ahead: int,
        seen_event_ids: set[str] | None = None,
    ) -> list[Event]:
        """Return up to ten eligible events, paging past previously seen IDs."""
        logger.info("Searching Ticketmaster events near %s", self.location.name)

        url = f"{self.api_base_url}/events.json"
        start_datetime = datetime.now(timezone.utc)
        end_datetime = start_datetime + timedelta(days=days_ahead)

        params = {
            "apikey": self.api_key,
            "geoPoint": self.location.geo_point,
            "radius": self.location.radius_km,
            "unit": "km",
            "countryCode": "PL",
            "classificationName": "-sports",
            "size": _SEARCH_PAGE_SIZE,
            "sort": "date,asc",
            "startDateTime": start_datetime.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "endDateTime": end_datetime.isoformat(timespec="seconds").replace("+00:00", "Z"),
        }

        excluded_ids = set(seen_event_ids or ())
        discovered_events = []
        pages_fetched = 0
        api_returned = 0
        for page_number in range(_MAX_SEARCH_PAGES):
            data = _get_ticketmaster_data(url, params | {"page": page_number})
            pages_fetched += 1
            events = data.get("_embedded", {}).get("events", [])
            api_returned += len(events)

            for event in events:
                if event.get("dates", {}).get("status", {}).get("code") == "canceled":
                    _log_canceled_event(event["id"])
                    continue
                raw_event_id = event["id"]
                event_id = build_event_id("ticketmaster", raw_event_id)
                if event_id in excluded_ids or raw_event_id in excluded_ids:
                    continue
                discovered_events.append(self._event_from_response(event))
                excluded_ids.add(event_id)
                if len(discovered_events) == _SEARCH_PAGE_SIZE:
                    break

            if len(discovered_events) == _SEARCH_PAGE_SIZE:
                break

            page_info = data.get("page")
            if not isinstance(page_info, dict):
                page_info = {}
            reported_page = page_info.get("number")
            if not isinstance(reported_page, int) or isinstance(reported_page, bool):
                reported_page = page_number
            total_pages = page_info.get("totalPages")
            if isinstance(total_pages, int) and not isinstance(total_pages, bool):
                if reported_page + 1 >= total_pages:
                    break
            elif len(events) < _SEARCH_PAGE_SIZE:
                break

        logger.info(
            "Ticketmaster event search completed",
            extra={
                "event.action": "ticketmaster_event_search",
                "events.api_pages_fetched": pages_fetched,
                "events.api_returned": api_returned,
                "events.unseen_eligible": len(discovered_events),
            },
        )
        return discovered_events

    def _event_from_response(self, event: dict) -> Event:
        venues = event.get("_embedded", {}).get("venues", [])
        venue = venues[0] if venues else {}

        return Event(
            id=build_event_id("ticketmaster", event["id"]),
            name=event["name"],
            date=event.get("dates", {}).get("start", {}).get("localDate"),
            city=venue.get("city", {}).get("name"),
            venue=venue.get("name"),
            url=event.get("url"),
            source="ticketmaster",
            source_event_id=event["id"],
            admission=self._admission_from_response(event),
        )

    @staticmethod
    def _admission_from_response(event: dict) -> Admission | None:
        for price_range in event.get("priceRanges", []):
            if not isinstance(price_range, dict):
                continue
            price_min = price_range.get("min")
            price_max = price_range.get("max")
            if not isinstance(price_min, (int, float)) or isinstance(price_min, bool):
                continue
            if not isinstance(price_max, (int, float)) or isinstance(price_max, bool):
                continue
            return Admission(
                is_free=False,
                price_min=price_min,
                price_max=price_max,
                currency=price_range.get("currency"),
            )
        return None

    def get_event_details(self, event_id: str) -> EventDetails:
        logger.info("Fetching Ticketmaster event details event_id=%s", event_id)

        url = f"{self.api_base_url}/events/{event_id}.json"
        event = _get_ticketmaster_data(
            url,
            {"apikey": self.api_key},
        )
        if event.get("dates", {}).get("status", {}).get("code") == "canceled":
            _log_canceled_event(event_id)
            raise ValueError("Ticketmaster event is canceled")

        venues = event.get("_embedded", {}).get("venues", [])
        venue = venues[0] if venues else {}

        return EventDetails(
            name=event.get("name"),
            date=event.get("dates", {}).get("start", {}).get("localDate"),
            time=event.get("dates", {}).get("start", {}).get("localTime"),
            venue=venue.get("name"),
            city=venue.get("city", {}).get("name"),
            url=event.get("url"),
        )
