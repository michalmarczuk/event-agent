import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class SearchLocation:
    name: str
    geo_point: str
    radius_km: int


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    ticketmaster_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    model: str
    search_location: SearchLocation


_REQUIRED_VARIABLES = {
    "OPENAI_API_KEY": "openai_api_key",
    "TICKETMASTER_API_KEY": "ticketmaster_api_key",
    "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
    "TELEGRAM_CHAT_ID": "telegram_chat_id",
    "MODEL": "model",
    "EVENT_BASE_LOCATION_NAME": "event_base_location_name",
    "EVENT_BASE_GEOPOINT": "event_base_geopoint",
    "EVENT_SEARCH_RADIUS_KM": "event_search_radius_km",
}


def load_settings() -> Settings:
    load_dotenv()

    missing = [
        name for name in _REQUIRED_VARIABLES
        if not os.getenv(name)
    ]
    if missing:
        raise ValueError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    values = {
        attribute: os.environ[name]
        for name, attribute in _REQUIRED_VARIABLES.items()
    }

    try:
        radius_km = int(values.pop("event_search_radius_km"))
    except ValueError as error:
        raise ValueError("EVENT_SEARCH_RADIUS_KM must be an integer") from error
    if radius_km <= 0:
        raise ValueError("EVENT_SEARCH_RADIUS_KM must be greater than zero")

    location = SearchLocation(
        name=values.pop("event_base_location_name"),
        geo_point=values.pop("event_base_geopoint"),
        radius_km=radius_km,
    )

    return Settings(
        **values,
        search_location=location,
    )
