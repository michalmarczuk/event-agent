import json
import logging

import requests

from src.config import load_settings

logger = logging.getLogger(__name__)


def send_telegram_message(message: str) -> None:
    """Send one Telegram message and raise a sanitized delivery error."""

    settings = load_settings()
    api_base_url = settings.telegram_api_base_url.rstrip("/")

    try:
        response = requests.post(
            f"{api_base_url}/bot{settings.telegram_bot_token}/sendMessage",
            json={
                "chat_id": settings.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        response.raise_for_status()
    except requests.HTTPError as exc:
        response = exc.response
        status_code = response.status_code if response is not None else None
        description = None
        if response is not None:
            try:
                payload = response.json()
            except Exception:
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get("description"), str):
                description = payload["description"].replace(settings.telegram_bot_token, "[REDACTED]")
        if description is None:
            logger.error("Telegram delivery failed status=%s", status_code)
        else:
            logger.error(
                "Telegram delivery failed status=%s description=%s",
                status_code,
                json.dumps(description),
            )
    except requests.RequestException as exc:
        logger.error("Telegram delivery failed exception_type=%s", type(exc).__name__)
    except Exception as exc:
        logger.error("Telegram delivery failed exception_type=%s", type(exc).__name__)
    else:
        logger.info("Telegram delivery succeeded")
        return

    # Raise outside the exception handler so a token-bearing request error is
    # not retained as this safe public exception's context.
    raise RuntimeError("Telegram delivery failed")
