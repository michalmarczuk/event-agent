import logging
import sys

import ecs_logging
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

try:
    from .config import load_elastic_logging_settings
except ImportError:  # pragma: no cover - supports direct script execution
    from config import load_elastic_logging_settings

_ECS_HANDLER_MARKER = "_event_agent_ecs_handler"
_OTLP_HANDLER_MARKER = "_event_agent_otlp_handler"
_SERVICE_METADATA = {
    "service.name": "event-agent",
    "service.environment": "production",
}
_RESOURCE_ATTRIBUTES = {
    "service.name": "event-agent",
    "deployment.environment.name": "production",
}

logger = logging.getLogger(__name__)

_otel_logger_provider: LoggerProvider | None = None


def configure_logging() -> None:
    """Configure ECS stdout logging and optional Elastic OTLP export."""
    global _otel_logger_provider

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if not any(
        getattr(handler, _ECS_HANDLER_MARKER, False)
        for handler in root_logger.handlers
    ):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            ecs_logging.StdlibFormatter(extra=_SERVICE_METADATA)
        )
        setattr(handler, _ECS_HANDLER_MARKER, True)
        root_logger.addHandler(handler)

    if _otel_logger_provider is not None or any(
        getattr(handler, _OTLP_HANDLER_MARKER, False)
        for handler in root_logger.handlers
    ):
        return

    try:
        settings = load_elastic_logging_settings()
    except Exception:
        logger.warning(
            "Elastic OTLP log export configuration failed; "
            "stdout logging remains active"
        )
        return

    endpoint = settings.elastic_otlp_endpoint
    api_key = settings.elastic_api_key
    if not endpoint and not api_key:
        return
    if not endpoint or not api_key:
        logger.warning(
            "Elastic OTLP log export disabled: both endpoint and API key "
            "are required"
        )
        return

    provider: LoggerProvider | None = None
    try:
        exporter = OTLPLogExporter(
            endpoint=f"{endpoint.rstrip('/')}/v1/logs",
            headers={"Authorization": f"ApiKey {api_key}"},
        )
        provider = LoggerProvider(
            resource=Resource.create(_RESOURCE_ATTRIBUTES),
            shutdown_on_exit=False,
        )
        provider.add_log_record_processor(
            BatchLogRecordProcessor(exporter)
        )
        otlp_handler = LoggingHandler(
            level=logging.INFO,
            logger_provider=provider,
        )
        setattr(otlp_handler, _OTLP_HANDLER_MARKER, True)
        root_logger.addHandler(otlp_handler)
        _otel_logger_provider = provider
    except Exception:
        if provider is not None:
            try:
                provider.shutdown()
            except Exception:
                pass
        logger.warning(
            "Elastic OTLP log export setup failed; stdout logging remains active"
        )


def shutdown_logging() -> None:
    """Flush and shut down optional OpenTelemetry logging safely."""
    global _otel_logger_provider

    provider = _otel_logger_provider
    if provider is None:
        return
    _otel_logger_provider = None

    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        if getattr(handler, _OTLP_HANDLER_MARKER, False):
            root_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                logger.warning("Elastic OTLP log handler cleanup failed")

    try:
        if not provider.force_flush():
            logger.warning("Elastic OTLP log flush timed out")
    except Exception:
        logger.warning("Elastic OTLP log flush failed")

    try:
        provider.shutdown()
    except Exception:
        logger.warning("Elastic OTLP log shutdown failed")
