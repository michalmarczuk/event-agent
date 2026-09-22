import json
from datetime import datetime
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pytest

from tests.support.fake_external_services import FakeExternalServicesServer


@pytest.fixture
def fake_services():
    with FakeExternalServicesServer(
        scenario="happy_path",
        host="127.0.0.1",
        port=0,
    ) as server:
        yield server


def _request(fake_services, method, path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request_headers = {} if headers is None else dict(headers)
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request = Request(
        f"{fake_services.base_url}{path}",
        data=data,
        headers=request_headers,
        method=method,
    )
    with urlopen(request, timeout=2) as response:
        return response.status, json.load(response)


def _openai_request(fake_services, body):
    status, payload = _request(
        fake_services,
        "POST",
        "/openai/v1/responses",
        body,
    )
    assert status == 200
    return payload


def test_health_reports_selected_scenario(fake_services):
    status, payload = _request(fake_services, "GET", "/health")

    assert status == 200
    assert payload == {"status": "ok", "scenario": "happy_path"}


def test_openai_happy_path_returns_tool_call_then_final_recommendation(
    fake_services,
):
    initial = _openai_request(
        fake_services,
        {
            "model": "test-model",
            "input": "Find events",
            "tools": [{"type": "function", "name": "search_events"}],
        },
    )

    tool_call = initial["output"][0]
    assert tool_call["type"] == "function_call"
    assert tool_call["name"] == "search_events"
    assert json.loads(tool_call["arguments"]) == {"days_ahead": 30}

    final = _openai_request(
        fake_services,
        {
            "model": "test-model",
            "previous_response_id": initial["id"],
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": tool_call["call_id"],
                    "output": json.dumps([{"id": "ticketmaster:event-happy-1"}]),
                }
            ],
        },
    )

    content = final["output"][0]["content"][0]
    recommendation_payload = json.loads(content["text"])
    assert final["output"][0]["type"] == "message"
    assert content["type"] == "output_text"
    assert recommendation_payload["recommendations"][0]["event_id"] == (
        "ticketmaster:event-happy-1"
    )


def test_ticketmaster_search_returns_deterministic_event(fake_services):
    query = urlencode(
        {
            "apikey": "ticketmaster-secret",
            "page": 0,
            "size": 10,
        }
    )
    status, payload = _request(
        fake_services,
        "GET",
        f"/ticketmaster/discovery/v2/events.json?{query}",
    )

    events = payload["_embedded"]["events"]
    assert status == 200
    assert len(events) == 1
    assert events[0]["id"]
    assert events[0]["name"]
    assert events[0]["dates"]["status"]["code"] == "onsale"
    assert payload["page"] == {
        "number": 0,
        "size": 10,
        "totalElements": 1,
        "totalPages": 1,
    }


def test_mixed_source_scenario_returns_mosir_selection_without_authority_fields():
    current_date = datetime.now(ZoneInfo("Europe/Warsaw")).date()
    with FakeExternalServicesServer(scenario="mixed_source_discovery") as server:
        _, ticketmaster_payload = _request(
            server,
            "GET",
            "/ticketmaster/discovery/v2/events.json?page=0",
        )
        _, calendar_payload = _request(
            server,
            "GET",
            f"/mosir/item/calendar?year={current_date.year}&month={current_date.month}",
        )
        initial = _openai_request(
            server,
            {"model": "test-model", "input": "Find events"},
        )
        final = _openai_request(
            server,
            {
                "model": "test-model",
                "previous_response_id": initial["id"],
                "input": [],
            },
        )

    assert [event["id"] for event in ticketmaster_payload["_embedded"]["events"]] == [
        "event-mixed-ticketmaster-1"
    ]
    assert calendar_payload == [
        {"date": current_date.isoformat()}
    ]
    recommendation = json.loads(final["output"][0]["content"][0]["text"])[
        "recommendations"
    ][0]
    assert recommendation["event_id"] == "mosir_tychy:9002"
    assert not {"source", "url", "admission"} & recommendation.keys()


@pytest.mark.parametrize(
    ("scenario", "expected_event_ids"),
    [
        ("happy_path", ["event-happy-1"]),
        ("no_events", []),
        ("previously_seen_event", ["event-happy-1"]),
        (
            "canceled_event_filtering",
            ["event-canceled-1", "event-valid-1"],
        ),
        (
            "multiple_events",
            ["event-multiple-other-1", "event-multiple-selected-1"],
        ),
    ],
)
def test_scenarios_return_deterministic_ticketmaster_events(
    scenario,
    expected_event_ids,
):
    with FakeExternalServicesServer(scenario=scenario) as server:
        status, payload = _request(
            server,
            "GET",
            "/ticketmaster/discovery/v2/events.json?page=0",
        )

    assert status == 200
    assert [event["id"] for event in payload["_embedded"]["events"]] == (
        expected_event_ids
    )


@pytest.mark.parametrize(
    ("scenario", "path", "body"),
    [
        (
            "openai_failure",
            "/openai/v1/responses",
            {"model": "test-model", "input": "Find events"},
        ),
        (
            "telegram_failure",
            "/telegram/bottest-telegram-token/sendMessage",
            {"chat_id": "test-chat", "text": "Event report"},
        ),
    ],
)
def test_failure_scenarios_return_deterministic_5xx(
    scenario,
    path,
    body,
):
    with FakeExternalServicesServer(scenario=scenario) as server:
        with pytest.raises(HTTPError) as error:
            _request(server, "POST", path, body)

    assert error.value.code == 503


def test_ticketmaster_details_match_search_event(fake_services):
    _, search_payload = _request(
        fake_services,
        "GET",
        "/ticketmaster/discovery/v2/events.json?page=0",
    )
    search_event = search_payload["_embedded"]["events"][0]

    status, details = _request(
        fake_services,
        "GET",
        f"/ticketmaster/discovery/v2/events/{search_event['id']}.json",
    )

    assert status == 200
    assert details["id"] == search_event["id"]
    assert details["name"] == search_event["name"]
    assert details["dates"]["start"] == search_event["dates"]["start"]


def test_telegram_accepts_message_without_external_delivery(fake_services):
    status, payload = _request(
        fake_services,
        "POST",
        "/telegram/bottest-telegram-token/sendMessage",
        {
            "chat_id": "test-chat",
            "text": "Event report",
            "parse_mode": "HTML",
        },
    )

    assert status == 200
    assert payload == {"ok": True, "result": {"message_id": 1}}


def test_journal_records_method_path_and_safe_body(fake_services):
    message = {
        "chat_id": "test-chat",
        "text": "Event report",
        "parse_mode": "HTML",
    }
    _request(
        fake_services,
        "POST",
        "/telegram/bottest-telegram-token/sendMessage",
        message,
    )

    status, journal = _request(fake_services, "GET", "/__journal")

    assert status == 200
    entry = journal["requests"][0]
    assert entry["method"] == "POST"
    assert entry["path"].startswith("/telegram/bot")
    assert entry["path"].endswith("/sendMessage")
    assert entry["body"] == {
        **message,
        "chat_id": "[REDACTED]",
    }
    assert entry["response_status"] == 200


def test_journal_redacts_credentials(fake_services):
    ticketmaster_key = "ticketmaster-super-secret"
    telegram_token = "telegram-super-secret"
    authorization = "Bearer openai-super-secret"

    _request(
        fake_services,
        "GET",
        "/ticketmaster/discovery/v2/events.json?"
        + urlencode({"apikey": ticketmaster_key, "page": 0}),
        headers={"Authorization": authorization},
    )
    _request(
        fake_services,
        "POST",
        f"/telegram/bot{telegram_token}/sendMessage",
        {"chat_id": "test-chat", "text": "Report"},
    )

    _, journal = _request(fake_services, "GET", "/__journal")
    serialized = json.dumps(journal)

    assert ticketmaster_key not in serialized
    assert telegram_token not in serialized
    assert authorization not in serialized
    assert "Authorization" not in serialized


def test_reset_clears_request_journal(fake_services):
    _request(
        fake_services,
        "GET",
        "/ticketmaster/discovery/v2/events.json?page=0",
    )
    _, journal_before = _request(fake_services, "GET", "/__journal")
    assert journal_before["requests"]

    status, payload = _request(fake_services, "POST", "/__reset")
    _, journal_after = _request(fake_services, "GET", "/__journal")

    assert status == 200
    assert payload == {"reset": True}
    assert journal_after == {"requests": []}
