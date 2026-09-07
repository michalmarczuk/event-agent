import json

import src.history as history
from src.models import Event


def test_load_seen_event_ids_returns_saved_ids(tmp_path, monkeypatch):
    seen_events_file = tmp_path / "seen_events.json"
    seen_events_file.write_text(json.dumps(["event-1", "event-2"]), encoding="utf-8")
    monkeypatch.setattr(history, "SEEN_EVENTS_FILE", seen_events_file)

    assert history.load_seen_event_ids() == {"event-1", "event-2"}


def test_save_seen_event_ids_writes_sorted_json_list(tmp_path, monkeypatch):
    seen_events_file = tmp_path / "data" / "seen_events.json"
    monkeypatch.setattr(history, "SEEN_EVENTS_FILE", seen_events_file)

    history.save_seen_event_ids({"event-3", "event-1", "event-2"})

    assert json.loads(seen_events_file.read_text(encoding="utf-8")) == [
        "event-1",
        "event-2",
        "event-3",
    ]


def test_load_seen_event_ids_returns_empty_set_when_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "SEEN_EVENTS_FILE", tmp_path / "missing.json")

    assert history.load_seen_event_ids() == set()


def test_filter_unseen_events_returns_all_events_when_all_are_new():
    events = [
        Event("event-1", "First", None, None, None, None, "test"),
        Event("event-2", "Second", None, None, None, None, "test"),
    ]

    assert history.filter_unseen_events(events, set()) == events


def test_filter_unseen_events_excludes_already_seen_events():
    events = [
        Event("event-1", "First", None, None, None, None, "test"),
        Event("event-2", "Second", None, None, None, None, "test"),
    ]

    assert history.filter_unseen_events(events, {"event-1"}) == [events[1]]


def test_filter_unseen_events_returns_empty_list_when_all_are_seen():
    events = [
        Event("event-1", "First", None, None, None, None, "test"),
        Event("event-2", "Second", None, None, None, None, "test"),
    ]

    assert history.filter_unseen_events(events, {"event-1", "event-2"}) == []
