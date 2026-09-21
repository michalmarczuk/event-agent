import src.config as config
from src.config import SearchLocation


def test_load_scraper_proxy_url_is_optional(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    monkeypatch.delenv("SCRAPER_PROXY_URL", raising=False)

    assert config.load_scraper_proxy_url() is None

    monkeypatch.setenv("SCRAPER_PROXY_URL", "socks5://127.0.0.1:1055")

    assert config.load_scraper_proxy_url() == "socks5://127.0.0.1:1055"


def test_load_elastic_logging_settings_is_optional(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    monkeypatch.delenv("ELASTIC_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("ELASTIC_API_KEY", raising=False)

    settings = config.load_elastic_logging_settings()

    assert settings == config.ElasticLoggingSettings(None, None)


def test_load_settings_returns_all_environment_values(monkeypatch):
    values = {
        "OPENAI_API_KEY": "openai-test-key",
        "OPENAI_BASE_URL": "https://openai.example/v1",
        "TICKETMASTER_API_KEY": "ticketmaster-test-key",
        "TICKETMASTER_API_BASE_URL": "https://ticketmaster.example/discovery/v2",
        "TELEGRAM_BOT_TOKEN": "telegram-test-token",
        "TELEGRAM_CHAT_ID": "telegram-test-chat",
        "TELEGRAM_API_BASE_URL": "https://telegram.example",
        "MOSIR_TYCHY_BASE_URL": "https://mosir.example",
        "MODEL": "test-model",
        "EVENT_BASE_LOCATION_NAME": "Tychy",
        "EVENT_BASE_GEOPOINT": "u2y0test",
        "EVENT_SEARCH_RADIUS_KM": "50",
        "ELASTIC_OTLP_ENDPOINT": "https://elastic.example",
        "ELASTIC_API_KEY": "elastic-test-key",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(config, "load_dotenv", lambda: None)

    settings = config.load_settings()

    assert settings.openai_api_key == "openai-test-key"
    assert settings.openai_base_url == "https://openai.example/v1"
    assert settings.ticketmaster_api_key == "ticketmaster-test-key"
    assert (
        settings.ticketmaster_api_base_url
        == "https://ticketmaster.example/discovery/v2"
    )
    assert settings.telegram_bot_token == "telegram-test-token"
    assert settings.telegram_chat_id == "telegram-test-chat"
    assert settings.telegram_api_base_url == "https://telegram.example"
    assert settings.mosir_tychy_base_url == "https://mosir.example"
    assert settings.model == "test-model"
    assert settings.search_location == SearchLocation("Tychy", "u2y0test", 50)
    assert settings.elastic_otlp_endpoint == "https://elastic.example"
    assert settings.elastic_api_key == "elastic-test-key"


def test_load_settings_uses_default_external_service_base_urls(monkeypatch):
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
    for name in (
        "OPENAI_BASE_URL",
        "TICKETMASTER_API_BASE_URL",
        "TELEGRAM_API_BASE_URL",
        "MOSIR_TYCHY_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "load_dotenv", lambda: None)

    settings = config.load_settings()

    assert settings.openai_base_url == "https://api.openai.com/v1"
    assert (
        settings.ticketmaster_api_base_url
        == "https://app.ticketmaster.com/discovery/v2"
    )
    assert settings.telegram_api_base_url == "https://api.telegram.org"
    assert settings.mosir_tychy_base_url == "https://mosir.tychy.pl"


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
