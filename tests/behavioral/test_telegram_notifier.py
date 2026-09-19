import logging
import traceback
from unittest.mock import patch

import pytest
from qase.pytest import qase
import requests

from src.config import SearchLocation, Settings
from src.telegram_notifier import send_telegram_message


TEST_SETTINGS = Settings(
    openai_api_key="openai-test-key",
    ticketmaster_api_key="ticketmaster-test-key",
    telegram_bot_token="telegram-test-token",
    telegram_chat_id="telegram-test-chat",
    model="test-model",
    search_location=SearchLocation("Tychy", "u2y0test", 50),
)


@qase.id(19)
@pytest.mark.qase
def test_send_telegram_message_sanitizes_delivery_failure(caplog):
    token = TEST_SETTINGS.telegram_bot_token
    leaking_error = requests.HTTPError(
        f"500 Server Error for url: https://api.telegram.org/bot{token}/sendMessage"
    )

    with (
        patch("src.telegram_notifier.load_settings", return_value=TEST_SETTINGS),
        patch("src.telegram_notifier.requests.post", side_effect=leaking_error),
        caplog.at_level(logging.ERROR),
        pytest.raises(RuntimeError, match="^Telegram delivery failed$") as error_info,
    ):
        send_telegram_message("<b>Report</b>")

    error = error_info.value
    displayed_exception = "".join(traceback.format_exception(error))
    assert error.__context__ is None
    assert error.__cause__ is None
    assert token not in str(error)
    assert token not in displayed_exception
    assert token not in caplog.text
