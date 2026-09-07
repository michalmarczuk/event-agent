import json
import os
from pathlib import Path

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


def test_load_seen_event_ids_rejects_malformed_json(tmp_path, monkeypatch):
    seen_events_file = tmp_path / "seen_events.json"
    seen_events_file.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(history, "SEEN_EVENTS_FILE", seen_events_file)

    try:
        history.load_seen_event_ids()
    except ValueError as error:
        assert str(error) == "Invalid history JSON: Expecting property name enclosed in double quotes"
    else:
        raise AssertionError("Malformed history JSON should raise ValueError")


def test_load_seen_event_ids_rejects_invalid_json_structure(tmp_path, monkeypatch):
    seen_events_file = tmp_path / "seen_events.json"
    seen_events_file.write_text(json.dumps({"event_id": "event-1"}), encoding="utf-8")
    monkeypatch.setattr(history, "SEEN_EVENTS_FILE", seen_events_file)

    try:
        history.load_seen_event_ids()
    except ValueError as error:
        assert str(error) == "History must contain a JSON list of strings"
    else:
        raise AssertionError("Invalid history structure should raise ValueError")


def test_save_seen_event_ids_replaces_target_atomically(tmp_path, monkeypatch):
    seen_events_file = tmp_path / "seen_events.json"
    seen_events_file.write_text(json.dumps(["old-event"]), encoding="utf-8")
    monkeypatch.setattr(history, "SEEN_EVENTS_FILE", seen_events_file)
    original_replace = os.replace
    replacements = []

    def replace(source, target):
        replacements.append((Path(source), Path(target)))
        original_replace(source, target)

    monkeypatch.setattr(history.os, "replace", replace)

    history.save_seen_event_ids({"event-2", "event-1"})

    assert replacements[0][1] == seen_events_file
    assert replacements[0][0].parent == seen_events_file.parent
    assert not replacements[0][0].exists()
    assert json.loads(seen_events_file.read_text(encoding="utf-8")) == [
        "event-1",
        "event-2",
    ]


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
