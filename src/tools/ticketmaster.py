from datetime import datetime, timedelta, timezone

import requests

try:
    from ..models import Event, EventDetails
except ImportError:  # pragma: no cover - supports script execution
    from models import Event, EventDetails


class TicketmasterClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def search_events(self, city: str, days_ahead: int) -> list[Event]:
        print(f"TOOL: szukam prawdziwych wydarzeń w: {city}")

        url = "https://app.ticketmaster.com/discovery/v2/events.json"
        start_datetime = datetime.now(timezone.utc)
        end_datetime = start_datetime + timedelta(days=days_ahead)

        params = {
            "apikey": self.api_key,
            "city": city,
            "countryCode": "PL",
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
            Event(
                id=event["id"],
                name=event["name"],
                date=event.get("dates", {}).get("start", {}).get("localDate"),
                city=city,
                venue=None,
                url=event.get("url"),
                source="ticketmaster",
            )
            for event in events
        ]

    def get_event_details(self, event_id: str) -> EventDetails:
        print(f"TOOL: pobieram szczegóły wydarzenia: {event_id}")

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
