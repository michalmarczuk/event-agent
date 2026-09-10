from datetime import datetime, timedelta, timezone
import logging

import requests

try:
    from ..config import SearchLocation
    from ..models import Admission, Event, EventDetails
except ImportError:  # pragma: no cover - supports script execution
    from config import SearchLocation
    from models import Admission, Event, EventDetails

logger = logging.getLogger(__name__)


class TicketmasterClient:
    def __init__(self, api_key: str, location: SearchLocation):
        self.api_key = api_key
        self.location = location

    def search_events(self, days_ahead: int) -> list[Event]:
        logger.info("Searching Ticketmaster events near %s", self.location.name)

        url = "https://app.ticketmaster.com/discovery/v2/events.json"
        start_datetime = datetime.now(timezone.utc)
        end_datetime = start_datetime + timedelta(days=days_ahead)

        params = {
            "apikey": self.api_key,
            "geoPoint": self.location.geo_point,
            "radius": self.location.radius_km,
            "unit": "km",
            "countryCode": "PL",
            "classificationName": "-sports",
            "size": 10,
            "sort": "date,asc",
            "startDateTime": start_datetime.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "endDateTime": end_datetime.isoformat(timespec="seconds").replace("+00:00", "Z"),
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        events = data.get("_embedded", {}).get("events", [])

        return [
            self._event_from_response(event)
            for event in events
        ]

    def _event_from_response(self, event: dict) -> Event:
        venues = event.get("_embedded", {}).get("venues", [])
        venue = venues[0] if venues else {}

        return Event(
            id=event["id"],
            name=event["name"],
            date=event.get("dates", {}).get("start", {}).get("localDate"),
            city=venue.get("city", {}).get("name"),
            venue=None,
            url=event.get("url"),
            source="ticketmaster",
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

        url = f"https://app.ticketmaster.com/discovery/v2/events/{event_id}.json"
        response = requests.get(
            url,
            params={"apikey": self.api_key},
            timeout=10,
        )
        response.raise_for_status()

        event = response.json()
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
