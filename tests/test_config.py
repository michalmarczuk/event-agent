import src.config as config
from src.config import SearchLocation


def test_load_settings_returns_all_environment_values(monkeypatch):
    values = {
        "OPENAI_API_KEY": "openai-test-key",
        "TICKETMASTER_API_KEY": "ticketmaster-test-key",
        "TELEGRAM_BOT_TOKEN": "telegram-test-token",
        "TELEGRAM_CHAT_ID": "telegram-test-chat",
        "MODEL": "test-model",
        "EVENT_BASE_LOCATION_NAME": "Tychy",
        "EVENT_BASE_GEOPOINT": "u2y0test",
        "EVENT_SEARCH_RADIUS_KM": "50",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(config, "load_dotenv", lambda: None)

    settings = config.load_settings()

    assert settings.openai_api_key == "openai-test-key"
    assert settings.ticketmaster_api_key == "ticketmaster-test-key"
    assert settings.telegram_bot_token == "telegram-test-token"
    assert settings.telegram_chat_id == "telegram-test-chat"
    assert settings.model == "test-model"
    assert settings.search_location == SearchLocation("Tychy", "u2y0test", 50)


def test_load_settings_reports_one_missing_variable(monkeypatch):
    values = {
        "OPENAI_API_KEY": "openai-test-key",
        "TICKETMASTER_API_KEY": "ticketmaster-test-key",
        "TELEGRAM_BOT_TOKEN": "telegram-test-token",
        "TELEGRAM_CHAT_ID": "telegram-test-chat",
        "MODEL": "test-model",
        "EVENT_BASE_LOCATION_NAME": "Tychy",
        "EVENT_BASE_GEOPOINT": "u2y0test",
        "EVENT_SEARCH_RADIUS_KM": "50",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("MODEL")
    monkeypatch.setattr(config, "load_dotenv", lambda: None)

    try:
        config.load_settings()
    except ValueError as error:
        assert str(error) == "Missing required environment variables: MODEL"
    else:
        raise AssertionError("load_settings() should reject missing variables")


def test_load_settings_reports_multiple_missing_variables(monkeypatch):
    for name in config._REQUIRED_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "load_dotenv", lambda: None)

    try:
        config.load_settings()
    except ValueError as error:
        message = str(error)
        assert "OPENAI_API_KEY" in message
        assert "TICKETMASTER_API_KEY" in message
        assert "TELEGRAM_BOT_TOKEN" in message
        assert "TELEGRAM_CHAT_ID" in message
        assert "MODEL" in message
        assert "EVENT_BASE_LOCATION_NAME" in message
        assert "EVENT_BASE_GEOPOINT" in message
        assert "EVENT_SEARCH_RADIUS_KM" in message
    else:
        raise AssertionError("load_settings() should reject missing variables")
