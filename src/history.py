import json
import logging
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

try:
    from .models import Event
except ImportError:  # pragma: no cover - supports script execution
    from models import Event


SEEN_EVENTS_FILE = Path(__file__).resolve().parent.parent / "data" / "seen_events.json"
logger = logging.getLogger(__name__)


def load_seen_event_ids() -> set[str]:
    """Load seen event IDs, returning an empty set when history is absent."""
    if not SEEN_EVENTS_FILE.exists():
        return set()

    try:
        with SEEN_EVENTS_FILE.open(encoding="utf-8") as file:
            event_ids = json.load(file)
    except json.JSONDecodeError as error:
        logger.error("Malformed history JSON")
        raise ValueError(f"Invalid history JSON: {error.msg}") from error

    if not isinstance(event_ids, list) or not all(
        isinstance(event_id, str) for event_id in event_ids
    ):
        logger.error("Invalid history structure")
        raise ValueError("History must contain a JSON list of strings")

    return set(event_ids)


def save_seen_event_ids(event_ids: set[str]) -> None:
    """Atomically save sorted seen event IDs to the history file."""
    SEEN_EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None

    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=SEEN_EVENTS_FILE.parent,
            prefix=f".{SEEN_EVENTS_FILE.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = file.name
            json.dump(sorted(event_ids), file)
            file.flush()
            os.fsync(file.fileno())

        os.replace(temporary_path, SEEN_EVENTS_FILE)
        temporary_path = None
    finally:
        if temporary_path is not None:
            Path(temporary_path).unlink(missing_ok=True)


def filter_unseen_events(
    events: list[Event],
    seen_ids: set[str],
) -> list[Event]:
    """Return events whose IDs are not present in the seen ID set."""
    return [event for event in events if event.id not in seen_ids]
