import logging
import traceback
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.config import SearchLocation, Settings
from src.integrations.telegram.notifier import send_telegram_message

TEST_SETTINGS = Settings(
    openai_api_key="openai-test-key",
    ticketmaster_api_key="ticketmaster-test-key",
    telegram_bot_token="telegram-test-token",
    telegram_chat_id="telegram-test-chat",
    model="test-model",
    search_location=SearchLocation("Tychy", "u2y0test", 50),
)


def test_send_telegram_message_logs_http_status_and_description_without_token(caplog):
    token = TEST_SETTINGS.telegram_bot_token
    response = MagicMock(status_code=400)
    response.json.return_value = {"ok": False, "description": "Bad Request: chat not found"}
    http_error = requests.HTTPError(
        f"400 Client Error for url: https://api.telegram.org/bot{token}/sendMessage"
    )
    http_error.response = response

    with (
        patch("src.integrations.telegram.notifier.load_settings", return_value=TEST_SETTINGS),
        patch(
            "src.integrations.telegram.notifier.requests.post",
            side_effect=http_error,
        ),
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
    assert "Telegram delivery failed status=400" in caplog.text
    assert 'description="Bad Request: chat not found"' in caplog.text
    assert token not in caplog.text


def test_send_telegram_message_logs_only_status_for_invalid_json(caplog):
    response = MagicMock(status_code=400)
    response.json.side_effect = ValueError("not JSON with sensitive details")
    http_error = requests.HTTPError("HTTP error")
    http_error.response = response

    with (
        patch("src.integrations.telegram.notifier.load_settings", return_value=TEST_SETTINGS),
        patch("src.integrations.telegram.notifier.requests.post", side_effect=http_error),
        caplog.at_level(logging.ERROR),
        pytest.raises(RuntimeError, match="^Telegram delivery failed$"),
    ):
        send_telegram_message("Report")

    assert "Telegram delivery failed status=400" in caplog.text
    assert "description=" not in caplog.text
    assert "sensitive details" not in caplog.text


def test_send_telegram_message_logs_network_exception_type_without_token(caplog):
    token = TEST_SETTINGS.telegram_bot_token
    network_error = requests.ConnectionError(
        f"Connection failed for https://api.telegram.org/bot{token}/sendMessage"
    )

    with (
        patch("src.integrations.telegram.notifier.load_settings", return_value=TEST_SETTINGS),
        patch("src.integrations.telegram.notifier.requests.post", side_effect=network_error),
        caplog.at_level(logging.ERROR),
        pytest.raises(RuntimeError, match="^Telegram delivery failed$") as error_info,
    ):
        send_telegram_message("Report")

    assert "exception_type=ConnectionError" in caplog.text
    assert token not in caplog.text
    assert error_info.value.__context__ is None


def test_send_telegram_message_uses_html_parse_mode():
    response = MagicMock()

    with (
        patch("src.integrations.telegram.notifier.load_settings", return_value=TEST_SETTINGS),
        patch("src.integrations.telegram.notifier.requests.post", return_value=response) as post,
    ):
        send_telegram_message("<b>Report</b>")

    assert post.call_args.kwargs["json"]["parse_mode"] == "HTML"
    assert post.call_args.kwargs["json"]["text"] == "<b>Report</b>"
    assert (
        post.call_args.args[0]
        == "https://api.telegram.org/bottelegram-test-token/sendMessage"
    )
    response.raise_for_status.assert_called_once_with()


def test_send_telegram_message_builds_url_from_configured_api_base_url():
    response = MagicMock()
    settings = Settings(
        openai_api_key="openai-test-key",
        ticketmaster_api_key="ticketmaster-test-key",
        telegram_bot_token="telegram-test-token",
        telegram_chat_id="telegram-test-chat",
        model="test-model",
        search_location=SearchLocation("Tychy", "u2y0test", 50),
        telegram_api_base_url="http://fake-services:8080/telegram/",
    )

    with (
        patch("src.integrations.telegram.notifier.load_settings", return_value=settings),
        patch("src.integrations.telegram.notifier.requests.post", return_value=response) as post,
    ):
        send_telegram_message("Report")

    assert (
        post.call_args.args[0]
        == "http://fake-services:8080/telegram/bottelegram-test-token/sendMessage"
    )
