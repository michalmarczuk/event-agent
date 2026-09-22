import logging
import time

from src.agent.runner import run_agent
from src.config import load_settings
from src.integrations.telegram.formatter import format_telegram_message
from src.integrations.telegram.notifier import send_telegram_message
from src.integrations.ticketmaster.enrichment import enrich_ticketmaster_prices
from src.observability.logging import configure_logging, shutdown_logging
from src.persistence.history import load_seen_event_ids, save_seen_event_ids

logger = logging.getLogger(__name__)

DAYS_AHEAD = 30


def main() -> None:
    """Run the daily event search and deliver its result."""
    started_at = time.monotonic()
    configure_logging()
    try:
        seen_event_ids = load_seen_event_ids()
        seen_loaded = len(seen_event_ids)
        logger.info("Loaded %d seen event IDs", len(seen_event_ids))

        result = run_agent(
            f"Znajdź najciekawsze wydarzenia dla mnie na najbliższe {DAYS_AHEAD} dni.",
            seen_event_ids=seen_event_ids,
        )
        if result.discovery_failed:
            logger.error(
                "Event discovery failed; skipping delivery and history persistence"
            )
            raise RuntimeError("Event discovery failed")
        enrich_ticketmaster_prices(result.recommendations)
        recommendations = result.recommendations
        settings = load_settings()
        formatted_message = format_telegram_message(
            recommendations,
            settings.search_location.name,
            settings.search_location.radius_km,
            DAYS_AHEAD,
        )

        logger.info(
            "Agent recommended %d event IDs",
            len(result.recommended_event_ids),
        )
        print(formatted_message)
        send_telegram_message(formatted_message)
        # Persist only after delivery succeeds, so a failed notification does
        # not mark recommendations as seen and suppress a future retry.
        updated_seen_event_ids = seen_event_ids | result.recommended_event_ids
        save_seen_event_ids(updated_seen_event_ids)
        logger.info(
            "Saved %d seen event IDs",
            len(updated_seen_event_ids),
        )
        try:
            logger.info(
                "Daily event-agent run completed",
                extra={
                    "event.action": "daily_run",
                    "event.outcome": "success",
                    "run.duration_ms": int((time.monotonic() - started_at) * 1_000),
                    "events.seen_loaded": seen_loaded,
                    "events.recommended": len(result.recommended_event_ids),
                    "events.seen_saved": len(updated_seen_event_ids),
                },
            )
        except Exception:
            # A telemetry failure must not change delivery or persistence.
            pass
    finally:
        shutdown_logging()


if __name__ == "__main__":
    main()
