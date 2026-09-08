import logging

from agent import run_agent
from history import load_seen_event_ids, save_seen_event_ids
from telegram_notifier import send_telegram_message

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

    logger.info(
        "Agent discovered %d event IDs",
        len(result.discovered_event_ids),
    )
    print(result.text)
    send_telegram_message(result.text)
    save_seen_event_ids(seen_event_ids | result.discovered_event_ids)
    logger.info(
        "Saved %d seen event IDs",
        len(seen_event_ids | result.discovered_event_ids),
    )


if __name__ == "__main__":
    main()