import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    ticketmaster_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    model: str


_REQUIRED_VARIABLES = {
    "OPENAI_API_KEY": "openai_api_key",
    "TICKETMASTER_API_KEY": "ticketmaster_api_key",
    "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
    "TELEGRAM_CHAT_ID": "telegram_chat_id",
    "MODEL": "model",
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

    return Settings(
        **{
            attribute: os.environ[name]
            for name, attribute in _REQUIRED_VARIABLES.items()
        }
    )
