from pathlib import Path

import pytest
import requests

from scripts import sync_qase_cases as qase
from tests.qase_sync_support import (
    FakeSession,
    _list_response,
    _response,
    _suites,
    _text_response,
    _use_test_catalog,
)


def test_case_file_contains_canceled_event_regression():
    suites = qase.load_cases(qase.CASES_FILE)

    event_discovery = next(
        suite for suite in suites if suite["name"] == "Event Discovery"
    )
    case = next(
        case
        for case in event_discovery["cases"]
        if case["title"] == "Canceled Ticketmaster events are excluded"
    )
    assert case["title"] == "Canceled Ticketmaster events are excluded"
    assert case["priority"] == "high"
    assert case["automated"] is True
    assert len(case["steps"]) == 4
    assert "event.reason=canceled" in case["steps"][-1]["expected"]


@pytest.mark.parametrize(
    ("priority", "expected_id"),
    [("undefined", 0), ("high", 1), ("medium", 2), ("low", 3)],
)
def test_priority_names_map_to_qase_ids(priority, expected_id):
    case = dict(_suites()[0]["cases"][0], priority=priority)

    assert qase._case_payload(case, 7)["priority"] == expected_id


@pytest.mark.parametrize(
    ("automated", "remote_fields", "needs_update"),
    [
        (True, {"isManual": False, "isToBeAutomated": False, "automation": 0}, False),
        (True, {"isManual": 0, "isToBeAutomated": 0}, False),
        (True, {"isManual": False, "isToBeAutomated": 0}, False),
        (True, {"isManual": 1, "isToBeAutomated": 0}, True),
        (True, {"isManual": 0, "isToBeAutomated": True}, True),
        (True, {"automation": 2}, True),
        (False, {"isManual": True, "isToBeAutomated": False}, False),
        (False, {"isManual": 1, "isToBeAutomated": 0}, False),
        (False, {"isManual": 0, "isToBeAutomated": 0}, True),
    ],
)
def test_dry_run_compares_current_automation_fields_only(
    automated, remote_fields, needs_update, capsys
):
    suites = _suites()
    suites[0]["cases"][0]["automated"] = automated
    desired = qase._case_payload(suites[0]["cases"][0], 7)
    stored = {
        "id": 11,
        **{
            key: value
            for key, value in desired.items()
            if key not in ("isManual", "isToBeAutomated")
        },
        **remote_fields,
    }

    def handler(method, path, _kwargs):
        assert method == "GET"
        if path == "/suite/EA":
            return _list_response([{"id": 7, "title": "Event Discovery"}])
        if path == "/case/EA":
            return _list_response([{"id": 11, "title": desired["title"]}])
        if path == "/case/EA/11":
            return _response({"status": True, "result": stored})
        raise AssertionError(path)

    summary = qase.sync_cases(FakeSession(handler), suites, dry_run=True)
    output = capsys.readouterr().out

    assert summary["cases_updated"] == int(needs_update)
    assert summary["cases_unchanged"] == int(not needs_update)
    assert ("automated: changed" in output) is needs_update


def test_cli_api_failure_is_nonzero_and_never_prints_token(
    monkeypatch, tmp_path, capsys
):
    token = "super-secret-qase-token"
    monkeypatch.setenv("QASE_API_TOKEN", token)
    _use_test_catalog(monkeypatch, tmp_path)

    def handler(_method, _path, _kwargs):
        return _response({"status": False, "message": token}, status_code=401)

    monkeypatch.setattr(qase.requests, "Session", lambda: FakeSession(handler))
    result = qase.main([])
    output = capsys.readouterr()

    assert result == 1
    assert "HTTP 401" in output.err
    assert token not in output.out + output.err


@pytest.mark.parametrize(
    ("failure_response", "expected_detail"),
    [
        (
            _response(
                {
                    "status": False,
                    "error": "Unprocessable entity",
                    "message": "Validation failed",
                    "errors": {"steps": ["Missing expected_result"]},
                    "result": {
                        "message": "Case was not saved",
                        "headers": {"Authorization": "Bearer hidden-value"},
                    },
                    "request_payload": {"title": "Do not print this payload"},
                },
                status_code=422,
            ),
            "Unprocessable entity; Validation failed; steps: Missing expected_result; Case was not saved",
        ),
        (
            _text_response(
                "Invalid case data\nAuthorization: Bearer hidden-value\n"
                "Token: super-secret-qase-token\npayload={full request body}",
                status_code=422,
            ),
            "Invalid case data [redacted]",
        ),
    ],
)
def test_patch_error_includes_safe_response_detail(
    failure_response, expected_detail, monkeypatch, tmp_path, capsys
):
    token = "super-secret-qase-token"
    monkeypatch.setenv("QASE_API_TOKEN", token)
    _use_test_catalog(monkeypatch, tmp_path)
    desired = qase._case_payload(_suites()[0]["cases"][0], 7)

    def handler(method, path, _kwargs):
        if (method, path) == ("GET", "/suite/EA"):
            return _list_response([{"id": 7, "title": "Event Discovery"}])
        if (method, path) == ("GET", "/case/EA"):
            return _list_response([{"id": 11, "title": desired["title"]}])
        if (method, path) == ("GET", "/case/EA/11"):
            return _response(
                {"status": True, "result": {"id": 11, **desired, "priority": 2}}
            )
        if (method, path) == ("PATCH", "/case/EA/11"):
            return failure_response
        raise AssertionError((method, path))

    monkeypatch.setattr(qase.requests, "Session", lambda: FakeSession(handler))

    assert qase.main([]) == 1
    output = capsys.readouterr()

    assert (
        f"Qase API PATCH /case/EA/11 failed (HTTP 422): {expected_detail}"
        in output.err
    )
    assert token not in output.out + output.err
    assert "Authorization" not in output.err
    assert "hidden-value" not in output.err
    assert "Do not print this payload" not in output.err
    assert "full request body" not in output.err
    assert "\n" not in output.err.strip("\n")


def test_unsuccessful_json_response_includes_safe_message():
    session = FakeSession(
        lambda _method, _path, _kwargs: _response(
            {"status": False, "message": "Validation failed"}
        )
    )

    with pytest.raises(
        qase.QaseSyncError, match="unsuccessful response: Validation failed"
    ):
        qase.sync_cases(session, _suites())


def test_plain_text_error_excerpt_is_bounded():
    session = FakeSession(
        lambda _method, _path, _kwargs: _text_response(
            "Validation failed " + "x" * 1000, status_code=422
        )
    )

    with pytest.raises(qase.QaseSyncError) as error:
        qase.sync_cases(session, _suites())

    assert "Validation failed" in str(error.value)
    assert len(str(error.value)) < 250


def test_network_error_does_not_expose_request_exception_text(
    monkeypatch, tmp_path, capsys
):
    token = "super-secret-qase-token"
    monkeypatch.setenv("QASE_API_TOKEN", token)
    _use_test_catalog(monkeypatch, tmp_path)

    def handler(_method, _path, _kwargs):
        raise requests.ConnectionError(f"Connection failed with {token}")

    monkeypatch.setattr(qase.requests, "Session", lambda: FakeSession(handler))

    assert qase.main([]) == 1
    output = capsys.readouterr()
    assert "ConnectionError" in output.err
    assert token not in output.out + output.err


def test_cli_missing_token_fails_without_network(monkeypatch, capsys):
    monkeypatch.delenv("QASE_API_TOKEN", raising=False)
    monkeypatch.setattr(
        qase.requests, "Session", lambda: pytest.fail("No HTTP session expected")
    )

    assert qase.main([]) == 1
    assert "QASE_API_TOKEN is required" in capsys.readouterr().err


def test_invalid_yaml_is_rejected(tmp_path: Path):
    cases_file = tmp_path / "cases.yaml"
    cases_file.write_text("suites: [invalid]", encoding="utf-8")

    with pytest.raises(qase.QaseSyncError, match="Each suite needs a name"):
        qase.load_cases(cases_file)
