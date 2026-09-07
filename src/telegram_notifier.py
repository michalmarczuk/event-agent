import requests

try:
    from .config import load_settings
except ImportError:  # pragma: no cover - supports script execution
    from config import load_settings



def send_telegram_message(message: str) -> None:
    settings = load_settings()

    response = requests.post(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
        json={"chat_id": settings.telegram_chat_id, "text": message},
        timeout=10,
    )
    response.raise_for_status()
