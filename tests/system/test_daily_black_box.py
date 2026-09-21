"""Black-box assertions for completed production-container daily runs."""

import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest
from qase.pytest import qase


_HAPPY_EVENT_ID = "event-happy-1"
_VALID_EVENT_ID = "event-valid-1"
_MULTIPLE_SELECTED_EVENT_ID = "event-multiple-selected-1"
_TEST_SECRETS = (
    "system-test-openai-key",
    "system-test-ticketmaster-key",
    "system-test-telegram-token",
    "system-test-chat-id",
)


def _required_environment_path(name: str) -> Path:
    value = os.getenv(name)
    if not value:
        pytest.skip("requires scripts/run_system_tests.sh")
    return Path(value)


def _scenario_paths(scenario: str) -> tuple[Path, Path]:
    artifacts_root = _required_environment_path(
        "EVENT_AGENT_SYSTEM_ARTIFACTS_ROOT"
    )
    data_root = _required_environment_path("EVENT_AGENT_SYSTEM_DATA_ROOT")
    return artifacts_root / scenario, data_root / scenario


def _run_artifacts(scenario: str) -> tuple[int, str, str, list[dict], Path]:
    artifacts_dir, data_dir = _scenario_paths(scenario)
    exit_code = int((artifacts_dir / "exit_code.txt").read_text().strip())
    stdout = (artifacts_dir / "stdout.log").read_text(encoding="utf-8")
    stderr = (artifacts_dir / "stderr.log").read_text(encoding="utf-8")
    journal = json.loads(
        (artifacts_dir / "journal.json").read_text(encoding="utf-8")
    )["requests"]
    return exit_code, stdout, stderr, journal, data_dir


def _ecs_records(stdout: str) -> list[dict]:
    records = []
    for line in stdout.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _requests(journal: list[dict], method: str, path: str) -> list[dict]:
    return [
        entry
        for entry in journal
        if entry["method"] == method
        and urlsplit(entry["path"]).path == path
    ]


def _openai_requests(journal: list[dict]) -> list[dict]:
    return _requests(journal, "POST", "/openai/v1/responses")


def _telegram_requests(journal: list[dict]) -> list[dict]:
    return _requests(journal, "POST", "/telegram/bot[REDACTED]/sendMessage")


def _tool_output_event_ids(openai_request: dict) -> list[str]:
    outputs = [
        item
        for item in openai_request["body"]["input"]
        if item.get("type") == "function_call_output"
    ]
    assert len(outputs) == 1
    return [event["id"] for event in json.loads(outputs[0]["output"])]


def _assert_no_secrets(stdout: str, stderr: str, journal: list[dict]) -> None:
    serialized_journal = json.dumps(journal)
    combined_logs = stdout + stderr
    for secret in _TEST_SECRETS:
        assert secret not in serialized_journal
        assert secret not in combined_logs
    assert "authorization" not in serialized_journal.casefold()


def _assert_daily_success(stdout: str) -> None:
    successful_runs = [
        record
        for record in _ecs_records(stdout)
        if record.get("event", {}).get("action") == "daily_run"
        and record.get("event", {}).get("outcome") == "success"
    ]
    assert len(successful_runs) == 1


def _assert_no_daily_success(stdout: str) -> None:
    assert not [
        record
        for record in _ecs_records(stdout)
        if record.get("event", {}).get("action") == "daily_run"
        and record.get("event", {}).get("outcome") == "success"
    ]


@qase.id(28)
def test_daily_happy_path_against_production_container() -> None:
    exit_code, stdout, stderr, journal, data_dir = _run_artifacts("happy_path")

    assert exit_code == 0, f"production container failed:\n{stderr}"
    ticketmaster_requests = _requests(
        journal,
        "GET",
        "/ticketmaster/discovery/v2/events.json",
    )
    assert ticketmaster_requests
    ticketmaster_query = dict(
        parse_qsl(urlsplit(ticketmaster_requests[0]["path"]).query)
    )
    assert ticketmaster_query["apikey"] == "[REDACTED]"

    openai_requests = _openai_requests(journal)
    assert len(openai_requests) == 2
    assert openai_requests[1]["body"]["previous_response_id"] == "response-happy-tool"
    assert _tool_output_event_ids(openai_requests[1]) == [_HAPPY_EVENT_ID]

    telegram_requests = _telegram_requests(journal)
    assert len(telegram_requests) == 1
    assert telegram_requests[0]["body"]["chat_id"] == "[REDACTED]"
    assert "Fake Concert" in telegram_requests[0]["body"]["text"]

    _assert_no_secrets(stdout, stderr, journal)
    history_file = data_dir / "seen_events.json"
    assert json.loads(history_file.read_text(encoding="utf-8")) == [_HAPPY_EVENT_ID]
    _assert_daily_success(stdout)


@qase.id(29)
def test_telegram_failure_does_not_persist_history() -> None:
    exit_code, stdout, stderr, journal, data_dir = _run_artifacts(
        "telegram_failure"
    )

    assert exit_code != 0
    assert len(_telegram_requests(journal)) == 1
    assert not (data_dir / "seen_events.json").exists()
    _assert_no_secrets(stdout, stderr, journal)
    _assert_no_daily_success(stdout)


@qase.id(30)
def test_no_events_delivers_no_recommendations_and_keeps_empty_history() -> None:
    exit_code, stdout, stderr, journal, data_dir = _run_artifacts("no_events")

    assert exit_code == 0, stderr
    openai_requests = _openai_requests(journal)
    assert len(openai_requests) == 2
    assert _tool_output_event_ids(openai_requests[1]) == []
    telegram_requests = _telegram_requests(journal)
    assert len(telegram_requests) == 1
    message = telegram_requests[0]["body"]["text"]
    assert message == "Brak nowych wydarzeń."
    assert "🎯 <b>Event Agent</b>" not in message
    assert "Fake Concert" not in message
    assert json.loads((data_dir / "seen_events.json").read_text()) == []
    _assert_daily_success(stdout)


@qase.id(31)
def test_previously_seen_event_is_not_delivered_again() -> None:
    exit_code, stdout, stderr, journal, data_dir = _run_artifacts(
        "previously_seen_event"
    )

    assert exit_code == 0, stderr
    openai_requests = _openai_requests(journal)
    assert len(openai_requests) == 2
    assert _tool_output_event_ids(openai_requests[1]) == []
    telegram_requests = _telegram_requests(journal)
    assert len(telegram_requests) == 1
    assert "Fake Concert" not in telegram_requests[0]["body"]["text"]
    assert json.loads((data_dir / "seen_events.json").read_text()) == [_HAPPY_EVENT_ID]
    _assert_daily_success(stdout)


@qase.id(32)
def test_canceled_event_is_filtered_before_recommendation() -> None:
    exit_code, stdout, stderr, journal, data_dir = _run_artifacts(
        "canceled_event_filtering"
    )

    assert exit_code == 0, stderr
    openai_requests = _openai_requests(journal)
    assert len(openai_requests) == 2
    assert _tool_output_event_ids(openai_requests[1]) == [_VALID_EVENT_ID]
    telegram_requests = _telegram_requests(journal)
    assert len(telegram_requests) == 1
    assert "Valid Fake Concert" in telegram_requests[0]["body"]["text"]
    assert "Canceled Fake Concert" not in telegram_requests[0]["body"]["text"]
    assert json.loads((data_dir / "seen_events.json").read_text()) == [_VALID_EVENT_ID]
    _assert_daily_success(stdout)


@qase.id(33)
def test_openai_failure_does_not_deliver_or_persist_partial_state() -> None:
    exit_code, stdout, stderr, journal, data_dir = _run_artifacts("openai_failure")

    assert exit_code != 0
    assert _openai_requests(journal)
    assert all(
        not request["body"].get("previous_response_id")
        for request in _openai_requests(journal)
    )
    assert not _requests(journal, "GET", "/ticketmaster/discovery/v2/events.json")
    assert not _telegram_requests(journal)
    assert not (data_dir / "seen_events.json").exists()
    _assert_no_secrets(stdout, stderr, journal)
    _assert_no_daily_success(stdout)


@qase.id(35)
def test_ticketmaster_failure_does_not_deliver_or_persist() -> None:
    exit_code, stdout, stderr, journal, data_dir = _run_artifacts(
        "ticketmaster_failure"
    )

    assert exit_code != 0
    assert _requests(
        journal,
        "GET",
        "/ticketmaster/discovery/v2/events.json",
    )
    openai_requests = _openai_requests(journal)
    assert len(openai_requests) == 2
    tool_outputs = [
        item
        for item in openai_requests[1]["body"]["input"]
        if item.get("type") == "function_call_output"
    ]
    assert len(tool_outputs) == 1
    assert json.loads(tool_outputs[0]["output"])["error"] is True
    assert not _telegram_requests(journal)
    assert not (data_dir / "seen_events.json").exists()
    assert "Brak nowych wydarzeń." not in stdout + stderr
    _assert_no_secrets(stdout, stderr, journal)
    _assert_no_daily_success(stdout)


@qase.id(36)
def test_invalid_recommendation_id_does_not_deliver_or_persist() -> None:
    exit_code, stdout, stderr, journal, data_dir = _run_artifacts(
        "invalid_recommendation_id"
    )

    assert exit_code != 0
    ticketmaster_requests = _requests(
        journal,
        "GET",
        "/ticketmaster/discovery/v2/events.json",
    )
    assert ticketmaster_requests
    openai_requests = _openai_requests(journal)
    assert len(openai_requests) == 2
    assert _tool_output_event_ids(openai_requests[1]) == [_HAPPY_EVENT_ID]
    assert openai_requests[1]["body"].get("previous_response_id")
    assert not _telegram_requests(journal)
    assert not (data_dir / "seen_events.json").exists()
    _assert_no_secrets(stdout, stderr, journal)
    _assert_no_daily_success(stdout)


@qase.id(34)
def test_multiple_events_persists_only_delivered_recommendation() -> None:
    exit_code, stdout, stderr, journal, data_dir = _run_artifacts("multiple_events")

    assert exit_code == 0, stderr
    openai_requests = _openai_requests(journal)
    assert len(openai_requests) == 2
    assert _tool_output_event_ids(openai_requests[1]) == [
        "event-multiple-other-1",
        _MULTIPLE_SELECTED_EVENT_ID,
    ]
    telegram_requests = _telegram_requests(journal)
    assert len(telegram_requests) == 1
    assert "Selected Fake Concert" in telegram_requests[0]["body"]["text"]
    assert "Other Fake Concert" not in telegram_requests[0]["body"]["text"]
    assert json.loads((data_dir / "seen_events.json").read_text()) == [
        _MULTIPLE_SELECTED_EVENT_ID
    ]
    _assert_daily_success(stdout)
