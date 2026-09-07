import json
from pathlib import Path


SEEN_EVENTS_FILE = Path(__file__).resolve().parent.parent / "data" / "seen_events.json"


def load_seen_event_ids() -> set[str]:
    if not SEEN_EVENTS_FILE.exists():
        return set()

    with SEEN_EVENTS_FILE.open(encoding="utf-8") as file:
        return set(json.load(file))


def save_seen_event_ids(event_ids: set[str]) -> None:
    SEEN_EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)

    with SEEN_EVENTS_FILE.open("w", encoding="utf-8") as file:
        json.dump(sorted(event_ids), file)


def filter_unseen_events(events, seen_ids):
    return [event for event in events if event.id not in seen_ids]
