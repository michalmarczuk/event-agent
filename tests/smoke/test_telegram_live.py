"""Opt-in authentication check for the live Telegram Bot API."""

import os

from dotenv import load_dotenv
import pytest
from qase.pytest import qase
import requests


@qase.id(25)
@pytest.mark.qase
def test_telegram_bot_authentication() -> None:
    """Verify bot identity through getMe without sending a message."""
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        pytest.skip("TELEGRAM_BOT_TOKEN is not configured")

    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=10,
        )
    except requests.RequestException as error:
        raise AssertionError(
            f"Telegram getMe smoke failed ({type(error).__name__})"
        ) from None

    if not response.ok:
        raise AssertionError(
            f"Telegram getMe smoke failed (HTTP {response.status_code})"
        )

    try:
        payload = response.json()
    except ValueError:
        raise AssertionError("Telegram getMe returned invalid JSON") from None

    assert payload.get("ok") is True, "Telegram getMe reported an API failure"
    identity = payload.get("result")
    assert isinstance(identity, dict), "Telegram getMe returned no bot identity"
    assert identity.get("is_bot") is True, "Telegram identity is not a bot"
    assert isinstance(identity.get("id"), int), "Telegram bot identity has no ID"
