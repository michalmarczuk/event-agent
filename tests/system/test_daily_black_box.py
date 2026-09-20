"""Black-box assertions for one completed production-container run."""

import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest


_EVENT_ID = "event-happy-1"
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


def _load_journal(artifacts_dir: Path) -> list[dict]:
    payload = json.loads(
        (artifacts_dir / "journal.json").read_text(encoding="utf-8")
    )
    return payload["requests"]


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


def test_daily_happy_path_against_production_container() -> None:
    artifacts_dir = _required_environment_path(
        "EVENT_AGENT_SYSTEM_ARTIFACTS_DIR"
    )
    data_dir = _required_environment_path("EVENT_AGENT_SYSTEM_DATA_DIR")

    exit_code = int((artifacts_dir / "exit_code.txt").read_text().strip())
    stdout = (artifacts_dir / "stdout.log").read_text(encoding="utf-8")
    stderr = (artifacts_dir / "stderr.log").read_text(encoding="utf-8")
    journal = _load_journal(artifacts_dir)

    assert exit_code == 0, f"production container failed:\n{stderr}"

    ticketmaster_requests = [
        entry
        for entry in journal
        if urlsplit(entry["path"]).path
        == "/ticketmaster/discovery/v2/events.json"
    ]
    assert ticketmaster_requests
    ticketmaster_query = dict(
        parse_qsl(urlsplit(ticketmaster_requests[0]["path"]).query)
    )
    assert ticketmaster_query["apikey"] == "[REDACTED]"

    openai_requests = [
        entry
        for entry in journal
        if entry["method"] == "POST"
        and entry["path"] == "/openai/v1/responses"
    ]
    assert len(openai_requests) == 2
    continuation_body = openai_requests[1]["body"]
    assert continuation_body["previous_response_id"] == "response-happy-tool"
    tool_outputs = [
        item
        for item in continuation_body["input"]
        if item.get("type") == "function_call_output"
    ]
    assert len(tool_outputs) == 1
    assert json.loads(tool_outputs[0]["output"])[0]["id"] == _EVENT_ID

    telegram_requests = [
        entry
        for entry in journal
        if entry["method"] == "POST"
        and entry["path"] == "/telegram/bot[REDACTED]/sendMessage"
    ]
    assert len(telegram_requests) == 1
    assert telegram_requests[0]["body"]["chat_id"] == "[REDACTED]"
    assert "Fake Concert" in telegram_requests[0]["body"]["text"]

    serialized_journal = json.dumps(journal)
    combined_logs = stdout + stderr
    for secret in _TEST_SECRETS:
        assert secret not in serialized_journal
        assert secret not in combined_logs
    assert "authorization" not in serialized_journal.casefold()

    history_file = data_dir / "seen_events.json"
    assert history_file.exists()
    assert json.loads(history_file.read_text(encoding="utf-8")) == [_EVENT_ID]

    successful_runs = [
        record
        for record in _ecs_records(stdout)
        if record.get("event", {}).get("action") == "daily_run"
        and record.get("event", {}).get("outcome") == "success"
    ]
    assert len(successful_runs) == 1
