import logging

import requests

try:
    from .config import load_settings
except ImportError:  # pragma: no cover - supports script execution
    from config import load_settings

logger = logging.getLogger(__name__)


def send_telegram_message(message: str) -> None:
    settings = load_settings()

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={
                "chat_id": settings.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        response.raise_for_status()
    except Exception:
        logger.error("Telegram delivery failed")
    else:
        logger.info("Telegram delivery succeeded")
        return

    # Raise outside the exception handler so a token-bearing request error is
    # not retained as this safe public exception's context.
    raise RuntimeError("Telegram delivery failed")
