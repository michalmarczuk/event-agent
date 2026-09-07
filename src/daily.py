from agent import run_agent
from history import load_seen_event_ids, save_seen_event_ids
from telegram_notifier import send_telegram_message


def main() -> None:
    """Run the daily event search and deliver its result."""
    seen_event_ids = load_seen_event_ids()
    result = run_agent(
        "Co ciekawego w Tychach, Katowicach i Gliwicach przez najbliższe 30 dni?",
        seen_event_ids=seen_event_ids,
    )

    print(result.text)
    send_telegram_message(result.text)
    save_seen_event_ids(seen_event_ids | result.discovered_event_ids)


if __name__ == "__main__":
    main()