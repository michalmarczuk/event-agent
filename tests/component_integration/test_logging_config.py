import json
import logging
from unittest.mock import MagicMock, Mock

import pytest
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter

import src.logging_config as logging_config
from src.config import ElasticLoggingSettings


@pytest.fixture
def isolated_root_logger(monkeypatch):
    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers[:]
    original_level = root_logger.level
    original_provider = logging_config._otel_logger_provider
    for handler in original_handlers:
        root_logger.removeHandler(handler)
    logging_config._otel_logger_provider = None
    monkeypatch.setattr(
        logging_config,
        "load_elastic_logging_settings",
        lambda: ElasticLoggingSettings(None, None),
    )

    yield root_logger

    logging_config.shutdown_logging()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()
    for handler in original_handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(original_level)
    logging_config._otel_logger_provider = original_provider


def _configure_complete_elastic(monkeypatch, exporter):
    monkeypatch.setattr(
        logging_config,
        "load_elastic_logging_settings",
        lambda: ElasticLoggingSettings(
            "https://elastic.example///",
            "elastic-test-key",
        ),
    )
    exporter_factory = Mock(return_value=exporter)
    monkeypatch.setattr(
        logging_config,
        "OTLPLogExporter",
        exporter_factory,
    )
    return exporter_factory


@pytest.mark.regression
def test_configure_logging_without_elastic_emits_ecs_json_only(
    isolated_root_logger,
    capsys,
    monkeypatch,
):
    exporter_factory = MagicMock()
    monkeypatch.setattr(
        logging_config,
        "OTLPLogExporter",
        exporter_factory,
    )

    logging_config.configure_logging()
    logging.getLogger("event_agent.test").info(
        "Loaded %d seen event IDs",
        6,
        extra={
            "event.action": "ticketmaster_price_scrape",
            "scraper.direct_price_count": 0,
        },
    )

    output = capsys.readouterr()
    event = json.loads(output.out.strip())
    assert output.err == ""
    assert event["message"] == "Loaded 6 seen event IDs"
    assert event["log.level"] == "info"
    assert event["log"]["logger"] == "event_agent.test"
    assert event["service"]["name"] == "event-agent"
    assert event["service"]["environment"] == "production"
    assert event["event"]["action"] == "ticketmaster_price_scrape"
    assert event["scraper"]["direct_price_count"] == 0
    assert not any(
        getattr(handler, logging_config._OTLP_HANDLER_MARKER, False)
        for handler in isolated_root_logger.handlers
    )
    exporter_factory.assert_not_called()


def test_complete_elastic_config_adds_one_otlp_handler(
    isolated_root_logger,
    monkeypatch,
):
    exporter = InMemoryLogRecordExporter()
    exporter_factory = _configure_complete_elastic(monkeypatch, exporter)

    logging_config.configure_logging()
    logging_config.configure_logging()

    assert sum(
        bool(getattr(handler, logging_config._ECS_HANDLER_MARKER, False))
        for handler in isolated_root_logger.handlers
    ) == 1
    assert sum(
        bool(getattr(handler, logging_config._OTLP_HANDLER_MARKER, False))
        for handler in isolated_root_logger.handlers
    ) == 1
    exporter_factory.assert_called_once_with(
        endpoint="https://elastic.example/v1/logs",
        headers={"Authorization": "ApiKey elastic-test-key"},
    )
    resource = logging_config._otel_logger_provider.resource
    assert resource.attributes["service.name"] == "event-agent"
    assert (
        resource.attributes["deployment.environment.name"]
        == "production"
    )


@pytest.mark.parametrize(
    ("endpoint", "api_key"),
    [
        ("https://elastic.example", None),
        (None, "elastic-partial-test-key"),
    ],
)
def test_incomplete_elastic_config_warns_and_disables_otlp(
    endpoint,
    api_key,
    isolated_root_logger,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        logging_config,
        "load_elastic_logging_settings",
        lambda: ElasticLoggingSettings(endpoint, api_key),
    )
    exporter_factory = MagicMock()
    monkeypatch.setattr(
        logging_config,
        "OTLPLogExporter",
        exporter_factory,
    )

    logging_config.configure_logging()

    output = capsys.readouterr().out
    assert "both endpoint and API key are required" in output
    assert "elastic-partial-test-key" not in output
    assert not any(
        getattr(handler, logging_config._OTLP_HANDLER_MARKER, False)
        for handler in isolated_root_logger.handlers
    )
    exporter_factory.assert_not_called()


def test_configure_logging_twice_does_not_duplicate_stdout(
    isolated_root_logger,
    capsys,
):
    logging_config.configure_logging()
    logging_config.configure_logging()

    logging.getLogger("event_agent.test").info("One event")

    assert len(capsys.readouterr().out.splitlines()) == 1


@pytest.mark.regression
def test_shutdown_flushes_and_shuts_down_provider_once(
    isolated_root_logger,
    monkeypatch,
):
    exporter_factory = _configure_complete_elastic(
        monkeypatch,
        MagicMock(),
    )
    provider = MagicMock()
    provider.force_flush.return_value = True
    handler = logging.NullHandler()
    handler.close = Mock(wraps=handler.close)
    monkeypatch.setattr(
        logging_config,
        "LoggerProvider",
        Mock(return_value=provider),
    )
    monkeypatch.setattr(
        logging_config,
        "BatchLogRecordProcessor",
        Mock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        logging_config,
        "LoggingHandler",
        Mock(return_value=handler),
    )

    logging_config.configure_logging()
    logging_config.shutdown_logging()
    logging_config.shutdown_logging()

    exporter_factory.assert_called_once()
    provider.force_flush.assert_called_once_with()
    provider.shutdown.assert_called_once_with()
    handler.close.assert_called_once_with()
    assert not any(
        getattr(candidate, logging_config._OTLP_HANDLER_MARKER, False)
        for candidate in isolated_root_logger.handlers
    )


@pytest.mark.regression
def test_otlp_setup_failure_does_not_log_api_key(
    isolated_root_logger,
    monkeypatch,
    capsys,
):
    secret = "elastic-super-secret-key"
    monkeypatch.setattr(
        logging_config,
        "load_elastic_logging_settings",
        lambda: ElasticLoggingSettings(
            "https://elastic.example",
            secret,
        ),
    )
    monkeypatch.setattr(
        logging_config,
        "OTLPLogExporter",
        Mock(side_effect=RuntimeError(f"rejected ApiKey {secret}")),
    )

    logging_config.configure_logging()

    output = capsys.readouterr().out
    assert "OTLP log export setup failed" in output
    assert secret not in output
    assert "Authorization" not in output


def test_structured_extras_are_exported_as_otlp_attributes(
    isolated_root_logger,
    monkeypatch,
    capsys,
):
    exporter = InMemoryLogRecordExporter()
    _configure_complete_elastic(monkeypatch, exporter)
    logging_config.configure_logging()

    logging.getLogger("event_agent.scraper").info(
        "No price found",
        extra={
            "event.action": "ticketmaster_price_scrape",
            "event.outcome": "failure",
            "event.reason": "no_price_or_best_available",
            "scraper.direct_price_count": 0,
            "scraper.best_available_found": False,
            "scraper.elapsed_ms": 125,
        },
    )
    logging_config.shutdown_logging()

    records = exporter.get_finished_logs()
    attributes = records[0].log_record.attributes
    assert attributes["event.action"] == "ticketmaster_price_scrape"
    assert attributes["event.outcome"] == "failure"
    assert attributes["event.reason"] == "no_price_or_best_available"
    assert attributes["scraper.direct_price_count"] == 0
    assert attributes["scraper.best_available_found"] is False
    assert attributes["scraper.elapsed_ms"] == 125
    capsys.readouterr()
