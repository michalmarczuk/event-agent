import logging

from agent import run_agent
from config import load_settings
from history import load_seen_event_ids, save_seen_event_ids
from telegram_notifier import send_telegram_message
from telegram_formatter import format_telegram_message

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the daily event search and deliver its result."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    seen_event_ids = load_seen_event_ids()
    logger.info("Loaded %d seen event IDs", len(seen_event_ids))

    result = run_agent(
        "Znajdź najciekawsze wydarzenia dla mnie na najbliższe 30 dni.",
        seen_event_ids=seen_event_ids,
    )
    settings = load_settings()
    formatted_message = format_telegram_message(
        result.recommendations,
        settings.search_location.name,
        settings.search_location.radius_km,
        30,
    )

    logger.info(
        "Agent recommended %d event IDs",
        len(result.recommended_event_ids),
    )
    print(formatted_message)
    send_telegram_message(formatted_message)
    save_seen_event_ids(seen_event_ids | result.recommended_event_ids)
    logger.info(
        "Saved %d seen event IDs",
        len(seen_event_ids | result.recommended_event_ids),
    )


if __name__ == "__main__":
    main()