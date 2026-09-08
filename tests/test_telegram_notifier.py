from unittest.mock import patch

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


def test_send_telegram_message_uses_html_parse_mode():
    response = type("Response", (), {"raise_for_status": lambda self: None})()

    with (
        patch("src.telegram_notifier.load_settings", return_value=TEST_SETTINGS),
        patch("src.telegram_notifier.requests.post", return_value=response) as post,
    ):
        send_telegram_message("<b>Report</b>")

    assert post.call_args.kwargs["json"]["parse_mode"] == "HTML"
    assert post.call_args.kwargs["json"]["text"] == "<b>Report</b>"
