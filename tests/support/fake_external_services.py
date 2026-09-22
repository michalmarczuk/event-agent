"""Deterministic HTTP fakes for black-box event-agent tests."""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from datetime import datetime
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from tests.support.system_scenarios import (
    DEFAULT_SYSTEM_SCENARIO,
    SYSTEM_SCENARIOS,
    SystemScenario,
)

_REDACTED = "[REDACTED]"
_TELEGRAM_SEND_MESSAGE_PATTERN = re.compile(
    r"^/telegram/bot[^/]+/sendMessage$"
)
_TICKETMASTER_DETAILS_PATTERN = re.compile(
    r"^/ticketmaster/discovery/v2/events/([^/]+)\.json$"
)
_ADMIN_PATHS = {"/health", "/__journal", "/__reset"}
_SENSITIVE_BODY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "chat_id",
    "password",
    "secret",
    "token",
}

def _global_ticketmaster_event_id(source_event_id: str) -> str:
    return f"ticketmaster:{source_event_id}"


def _ticketmaster_search_payload(scenario: SystemScenario) -> dict[str, Any]:
    events = deepcopy(scenario.ticketmaster_events)
    if scenario.ticketmaster_use_current_local_date:
        for event in events:
            event["dates"]["start"]["localDate"] = _current_local_date()
    return {
        "_embedded": {"events": events},
        "page": {
            "size": 10,
            "totalElements": len(events),
            "totalPages": 1,
            "number": 0,
        },
    }


def _mosir_calendar_payload(
    scenario: SystemScenario,
    year: int | None = None,
    month: int | None = None,
) -> list[dict[str, str]]:
    if scenario.mosir_use_current_local_date:
        current_date = datetime.now(ZoneInfo("Europe/Warsaw")).date()
        if (year, month) != (current_date.year, current_date.month):
            return []
    return [
        {"date": event["date"]}
        for event in {
            event["date"]: event
            for event in _effective_mosir_events(scenario)
        }.values()
    ]


def _current_local_date() -> str:
    return datetime.now(ZoneInfo("Europe/Warsaw")).date().isoformat()


def _effective_mosir_events(
    scenario: SystemScenario,
) -> tuple[dict[str, Any], ...]:
    if not scenario.mosir_use_current_local_date:
        return scenario.mosir_events
    current_date = _current_local_date()
    return tuple({**event, "date": current_date} for event in scenario.mosir_events)


def _mosir_events_page(events: list[dict[str, Any]]) -> str:
    cards = "".join(
        "<div class=\"item-box-wrapper\">"
        f"<a title=\"{event['name']}\" href=\"{event['detail_path']}\">"
        "Event"
        "</a></div>"
        for event in events
    )
    return f"<div class=\"events-list\">{cards}</div>"


def _mosir_event_details(event: dict[str, Any]) -> str:
    return (
        "<html><head>"
        f"<meta property=\"og:url\" content=\"{event['url']}\">"
        "</head><body><h2>MIEJSCE WYDARZENIA</h2>"
        f"<a>{event['venue']}</a></body></html>"
    )


def _openai_tool_response(request_body: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "response-happy-tool",
        "object": "response",
        "created_at": 0,
        "model": request_body.get("model", "fake-model"),
        "output": [
            {
                "type": "function_call",
                "id": "function-call-happy-1",
                "call_id": "call-search-events-1",
                "name": "search_events",
                "arguments": json.dumps({"days_ahead": 30}),
                "status": "completed",
            }
        ],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
    }


def _ticketmaster_recommendation(
    event: dict[str, Any],
    event_id: str,
) -> dict[str, Any]:
    venue = event["_embedded"]["venues"][0]
    start = event["dates"]["start"]
    return {
        "event_id": event_id,
        "name": event["name"],
        "category": "music",
        "date": start["localDate"],
        "time": start.get("localTime"),
        "city": venue["city"]["name"],
        "venue": venue["name"],
        "reason": "Deterministic fake recommendation.",
    }


def _openai_final_response(
    request_body: dict[str, Any],
    scenario: SystemScenario,
) -> dict[str, Any]:
    if scenario.mosir_recommendation_id is not None:
        recommendation_event = next(
            event
            for event in _effective_mosir_events(scenario)
            if event["id"] == scenario.mosir_recommendation_id
        )
        recommendations = [
            {
                "event_id": f"mosir_tychy:{recommendation_event['id']}",
                "name": recommendation_event["name"],
                "category": "music",
                "date": recommendation_event["date"],
                "time": None,
                "city": recommendation_event["city"],
                "venue": recommendation_event["venue"],
                "reason": "Deterministic fake recommendation.",
            }
        ]
        return _openai_message_response(request_body, recommendations)

    if scenario.ungrounded_recommendation_id is not None:
        recommendation_event = scenario.ticketmaster_events[0]
        recommendation_event_id = scenario.ungrounded_recommendation_id
    else:
        recommendation_event = next(
            (
                event
                for event in scenario.ticketmaster_events
                if event["id"] == scenario.ticketmaster_recommendation_id
            ),
            None,
        )
        recommendation_event_id = (
            recommendation_event["id"] if recommendation_event is not None else None
        )
    recommendations = []
    if recommendation_event is not None:
        event_id = (
            recommendation_event_id
            if scenario.ungrounded_recommendation_id is not None
            else _global_ticketmaster_event_id(recommendation_event_id)
        )
        recommendations.append(
            _ticketmaster_recommendation(recommendation_event, event_id)
        )
    return _openai_message_response(request_body, recommendations)


def _openai_message_response(
    request_body: dict[str, Any],
    recommendations: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": "response-happy-final",
        "object": "response",
        "created_at": 0,
        "model": request_body.get("model", "fake-model"),
        "output": [
            {
                "type": "message",
                "id": "message-happy-1",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {"recommendations": recommendations}
                        ),
                        "annotations": [],
                    }
                ],
            }
        ],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
    }


def _redact_body(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                _REDACTED
                if key.casefold() in _SENSITIVE_BODY_KEYS
                else _redact_body(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_body(item) for item in value]
    return value


def _safe_json_body(raw_body: bytes) -> Any:
    if not raw_body:
        return None
    try:
        return _redact_body(json.loads(raw_body))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"unparseable_body_bytes": len(raw_body)}


def _safe_path(raw_path: str) -> str:
    parsed = urlsplit(raw_path)
    path = parsed.path
    if _TELEGRAM_SEND_MESSAGE_PATTERN.fullmatch(path):
        path = re.sub(r"/bot[^/]+/", f"/bot{_REDACTED}/", path)

    query = urlencode(
        [
            (key, _REDACTED if key.casefold() == "apikey" else value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        ]
    )
    return urlunsplit(("", "", path, query, ""))


class _RequestJournal:
    """Thread-safe journal that stores only redacted fake-service requests."""

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._lock = Lock()

    def add(self, method: str, path: str, body: Any) -> dict[str, Any]:
        """Record a safe request and return its journal entry for completion."""
        entry = {"method": method, "path": _safe_path(path), "body": body}
        with self._lock:
            self._entries.append(entry)
        return entry

    def set_response_status(
        self, entry: dict[str, Any], status: HTTPStatus
    ) -> None:
        """Attach the response status without retaining response payloads."""
        with self._lock:
            entry["response_status"] = int(status)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._entries)

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()


class _FakeRequestHandler(BaseHTTPRequestHandler):
    """Route configured fake provider requests and record safe outcomes."""

    protocol_version = "HTTP/1.1"

    def __init__(
        self,
        *args: Any,
        scenario: str,
        journal: _RequestJournal,
        **kwargs: Any,
    ) -> None:
        self._scenario = scenario
        self._journal = journal
        self._journal_entry: dict[str, Any] | None = None
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        scenario = SYSTEM_SCENARIOS[self._scenario]
        if path == "/health":
            self._send_json(
                HTTPStatus.OK,
                {"status": "ok", "scenario": self._scenario},
            )
            return
        if path == "/__journal":
            self._send_json(
                HTTPStatus.OK,
                {"requests": self._journal.snapshot()},
            )
            return

        self._record_request(None)
        if path.startswith("/mosir/") and scenario.mosir_status != HTTPStatus.OK:
            self._send_json(
                scenario.mosir_status,
                {"error": "Deterministic MOSiR failure"},
            )
            return
        if path == "/mosir/item/calendar":
            query = dict(parse_qsl(urlsplit(self.path).query))
            try:
                year = int(query.get("year", ""))
                month = int(query.get("month", ""))
            except ValueError:
                year = None
                month = None
            self._send_json(
                HTTPStatus.OK,
                _mosir_calendar_payload(scenario, year, month),
            )
            return
        if path == "/mosir/wydarzenia":
            requested_date = dict(parse_qsl(urlsplit(self.path).query)).get("date")
            events = [
                event
                for event in _effective_mosir_events(scenario)
                if event["date"] == requested_date
            ]
            self._send_html(HTTPStatus.OK, _mosir_events_page(events))
            return
        matching_mosir_event = next(
            (
                event
                for event in _effective_mosir_events(scenario)
                if event["detail_path"] == path
            ),
            None,
        )
        if matching_mosir_event is not None:
            self._send_html(
                HTTPStatus.OK,
                _mosir_event_details(matching_mosir_event),
            )
            return
        if path == "/ticketmaster/discovery/v2/events.json":
            if scenario.ticketmaster_status != HTTPStatus.OK:
                self._send_json(
                    scenario.ticketmaster_status,
                    {"error": "Deterministic Ticketmaster failure"},
                )
                return
            self._send_json(HTTPStatus.OK, _ticketmaster_search_payload(scenario))
            return

        details_match = _TICKETMASTER_DETAILS_PATTERN.fullmatch(path)
        matching_event = next(
            (
                event
                for event in scenario.ticketmaster_events
                if details_match is not None and event["id"] == details_match.group(1)
            ),
            None,
        )
        if matching_event is not None:
            self._send_json(HTTPStatus.OK, matching_event)
            return

        self._send_not_found()

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        scenario = SYSTEM_SCENARIOS[self._scenario]
        if path == "/__reset":
            self._journal.reset()
            self._send_json(HTTPStatus.OK, {"reset": True})
            return

        raw_body = self._read_body()
        request_body = _safe_json_body(raw_body)
        self._record_request(request_body)

        if path == "/openai/v1/responses":
            if not isinstance(request_body, dict):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "OpenAI request body must be a JSON object"},
                )
                return
            if scenario.openai_status != HTTPStatus.OK:
                self._send_json(
                    scenario.openai_status,
                    {"error": {"message": "Deterministic OpenAI failure"}},
                )
                return
            if request_body.get("previous_response_id"):
                response = _openai_final_response(request_body, scenario)
            else:
                response = _openai_tool_response(request_body)
            self._send_json(HTTPStatus.OK, response)
            return

        if _TELEGRAM_SEND_MESSAGE_PATTERN.fullmatch(path):
            if scenario.telegram_status != HTTPStatus.OK:
                self._send_json(
                    scenario.telegram_status,
                    {"ok": False, "description": "Deterministic Telegram failure"},
                )
                return
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "result": {"message_id": 1},
                },
            )
            return

        self._send_not_found()

    def _read_body(self) -> bytes:
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            return b""
        try:
            length = int(content_length)
        except ValueError:
            return b""
        return self.rfile.read(max(length, 0))

    def _record_request(self, body: Any) -> None:
        if urlsplit(self.path).path not in _ADMIN_PATHS:
            self._journal_entry = self._journal.add(
                self.command, self.path, body
            )

    def _record_response_status(self, status: HTTPStatus) -> None:
        if self._journal_entry is not None:
            self._journal.set_response_status(self._journal_entry, status)

    def _send_not_found(self) -> None:
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def _send_json(self, status: HTTPStatus, payload: Any) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self._record_response_status(status)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: HTTPStatus, body: str) -> None:
        encoded_body = body.encode("utf-8")
        self._record_response_status(status)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded_body)))
        self.end_headers()
        self.wfile.write(encoded_body)

    def log_message(self, format: str, *args: Any) -> None:
        return


class FakeExternalServicesServer:
    """Run deterministic external-service fakes in a background thread."""

    def __init__(
        self,
        scenario: str = DEFAULT_SYSTEM_SCENARIO,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        if scenario not in SYSTEM_SCENARIOS:
            raise ValueError(f"Unsupported fake-services scenario: {scenario}")

        self.scenario = scenario
        self._journal = _RequestJournal()
        handler = partial(
            _FakeRequestHandler,
            scenario=scenario,
            journal=self._journal,
        )
        self._httpd = ThreadingHTTPServer((host, port), handler)
        self._thread: Thread | None = None

    @property
    def base_url(self) -> str:
        """Return the bound HTTP origin after resolving an ephemeral port."""
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        """Start serving requests in a daemon thread."""
        if self._thread is not None:
            return
        self._thread = Thread(
            target=self._httpd.serve_forever,
            name="fake-external-services",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        """Stop the background server and release its listening socket."""
        if self._thread is not None:
            self._httpd.shutdown()
            self._thread.join()
            self._thread = None
        self._httpd.server_close()

    def serve_forever(self) -> None:
        """Serve synchronously until interrupted."""
        try:
            self._httpd.serve_forever()
        finally:
            self._httpd.server_close()

    def __enter__(self) -> FakeExternalServicesServer:
        self.start()
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        self.close()


def main() -> None:
    """Run the fake external services until interrupted."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=8080, type=int)
    parser.add_argument("--scenario", default=DEFAULT_SYSTEM_SCENARIO)
    arguments = parser.parse_args()

    server = FakeExternalServicesServer(
        scenario=arguments.scenario,
        host=arguments.host,
        port=arguments.port,
    )
    print(
        f"Fake external services listening on {server.base_url} "
        f"scenario={server.scenario}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
