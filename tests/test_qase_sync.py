import json
from pathlib import Path

import pytest
import requests

from scripts import sync_qase_cases as qase


def _response(result, status_code=200):
    response = requests.Response()
    response.status_code = status_code
    response.url = qase.API_BASE_URL
    response._content = json.dumps(result).encode()
    return response


def _text_response(text, status_code):
    response = requests.Response()
    response.status_code = status_code
    response.url = qase.API_BASE_URL
    response._content = text.encode()
    return response


def _list_response(entities, total=None):
    count = len(entities) if total is None else total
    return _response(
        {"status": True, "result": {"total": count, "filtered": count, "entities": entities}}
    )


class FakeSession:
    def __init__(self, handler):
        self.handler = handler
        self.headers = {}
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def request(self, method, url, **kwargs):
        path = url.removeprefix(qase.API_BASE_URL)
        self.calls.append((method, path, kwargs))
        return self.handler(method, path, kwargs)


def _suites():
    return qase.load_cases(qase.CASES_FILE)


def test_case_file_contains_canceled_event_regression():
    suites = _suites()

    assert [suite["name"] for suite in suites] == ["Event Discovery"]
    case = suites[0]["cases"][0]
    assert case["title"] == "Canceled Ticketmaster events are excluded"
    assert case["priority"] == "high"
    assert case["automated"] is True
    assert len(case["steps"]) == 4
    assert "event.reason=canceled" in case["steps"][-1]["expected"]


@pytest.mark.parametrize(("automated", "is_manual"), [(True, 0), (False, 1)])
def test_sync_creates_missing_suite_and_classic_case(automated, is_manual):
    def handler(method, path, kwargs):
        if (method, path) == ("GET", "/suite/EA"):
            return _list_response([])
        if (method, path) == ("POST", "/suite/EA"):
            assert kwargs["json"] == {"title": "Event Discovery"}
            return _response({"status": True, "result": {"id": 7}})
        if (method, path) == ("GET", "/case/EA"):
            assert kwargs["params"]["suite_id"] == 7
            return _list_response([])
        if (method, path) == ("POST", "/case/EA"):
            return _response({"status": True, "result": {"id": 11}})
        raise AssertionError((method, path))

    session = FakeSession(handler)
    suites = _suites()
    suites[0]["cases"][0]["automated"] = automated
    summary = qase.sync_cases(session, suites)

    assert summary == {
        "suites_created": 1,
        "cases_created": 1,
        "cases_updated": 0,
        "cases_unchanged": 0,
    }
    payload = session.calls[-1][2]["json"]
    assert payload["suite_id"] == 7
    assert payload["priority"] == 1
    assert "Canceled Ticketmaster events" in payload["description"]
    assert "dates.status.code" in payload["preconditions"]
    assert payload["isManual"] == is_manual
    assert payload["isToBeAutomated"] == 0
    assert type(payload["isManual"]) is int
    assert type(payload["isToBeAutomated"]) is int
    assert f'"isManual": {is_manual}' in json.dumps(payload)
    assert '"isToBeAutomated": 0' in json.dumps(payload)
    assert "automation" not in payload
    assert payload["steps_type"] == "classic"
    assert payload["steps"][0] == {
        "action": "Execute event search with a canceled Ticketmaster event.",
        "expected_result": "Ticketmaster response is processed successfully.",
    }


def test_second_sync_does_not_create_duplicates_or_patch_unchanged_case():
    state = {"suite": None, "case": None}

    def handler(method, path, kwargs):
        if (method, path) == ("GET", "/suite/EA"):
            return _list_response([state["suite"]] if state["suite"] else [])
        if (method, path) == ("POST", "/suite/EA"):
            state["suite"] = {"id": 7, **kwargs["json"]}
            return _response({"status": True, "result": {"id": 7}})
        if (method, path) == ("GET", "/case/EA"):
            return _list_response([state["case"]] if state["case"] else [])
        if (method, path) == ("POST", "/case/EA"):
            state["case"] = {"id": 11, **kwargs["json"]}
            return _response({"status": True, "result": {"id": 11}})
        if (method, path) == ("GET", "/case/EA/11"):
            return _response({"status": True, "result": state["case"]})
        raise AssertionError((method, path))

    session = FakeSession(handler)
    first = qase.sync_cases(session, _suites())
    second = qase.sync_cases(session, _suites())

    assert first["cases_created"] == 1
    assert second == {
        "suites_created": 0,
        "cases_created": 0,
        "cases_updated": 0,
        "cases_unchanged": 1,
    }
    assert [(method, path) for method, path, _ in session.calls].count(
        ("POST", "/case/EA")
    ) == 1
    assert not any(method == "PATCH" for method, _, _ in session.calls)


def test_existing_case_is_patched_when_repository_content_changes(capsys):
    desired = qase._case_payload(_suites()[0]["cases"][0], 7)
    stored = {"id": 11, **desired, "description": "Old description"}

    def handler(method, path, kwargs):
        if (method, path) == ("GET", "/suite/EA"):
            return _list_response([{"id": 7, "title": "Event Discovery"}])
        if (method, path) == ("GET", "/case/EA"):
            return _list_response([{"id": 11, "title": desired["title"]}])
        if (method, path) == ("GET", "/case/EA/11"):
            return _response({"status": True, "result": stored})
        if (method, path) == ("PATCH", "/case/EA/11"):
            assert kwargs["json"] == desired
            assert "automation" not in kwargs["json"]
            return _response({"status": True, "result": {"id": 11}})
        raise AssertionError((method, path))

    summary = qase.sync_cases(FakeSession(handler), _suites())

    assert summary["cases_updated"] == 1
    assert summary["cases_unchanged"] == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("suite_exists", [False, True])
def test_dry_run_never_sends_mutating_requests(suite_exists):
    desired = qase._case_payload(_suites()[0]["cases"][0], 7)

    def handler(method, path, _kwargs):
        assert method == "GET"
        if path == "/suite/EA":
            return _list_response(
                [{"id": 7, "title": "Event Discovery"}] if suite_exists else []
            )
        if path == "/case/EA":
            return _list_response([{"id": 11, "title": desired["title"]}])
        if path == "/case/EA/11":
            return _response(
                {"status": True, "result": {"id": 11, **desired, "priority": 3}}
            )
        raise AssertionError(path)

    session = FakeSession(handler)
    summary = qase.sync_cases(session, _suites(), dry_run=True)

    assert summary["suites_created"] == (0 if suite_exists else 1)
    assert summary["cases_created"] == (0 if suite_exists else 1)
    assert summary["cases_updated"] == (1 if suite_exists else 0)
    assert all(method == "GET" for method, _, _ in session.calls)


def test_list_pagination_finds_existing_suite_and_case_beyond_first_page():
    desired = qase._case_payload(_suites()[0]["cases"][0], 7)

    def handler(method, path, kwargs):
        assert method == "GET"
        if path == "/suite/EA":
            if kwargs["params"]["offset"] == 0:
                return _list_response(
                    [{"id": index + 100, "title": f"Other {index}"} for index in range(100)],
                    total=101,
                )
            return _list_response([{"id": 7, "title": "Event Discovery"}], total=101)
        if path == "/case/EA":
            assert kwargs["params"]["suite_id"] == 7
            if kwargs["params"]["offset"] == 0:
                return _list_response(
                    [{"id": index + 200, "title": f"Other case {index}"} for index in range(100)],
                    total=101,
                )
            return _list_response([{"id": 11, "title": desired["title"]}], total=101)
        if path == "/case/EA/11":
            return _response({"status": True, "result": {"id": 11, **desired}})
        raise AssertionError(path)

    session = FakeSession(handler)
    summary = qase.sync_cases(session, _suites())

    assert summary["cases_unchanged"] == 1
    assert summary["suites_created"] == summary["cases_created"] == 0
    assert [(path, kwargs["params"]["offset"]) for _, path, kwargs in session.calls if path in ("/suite/EA", "/case/EA")] == [
        ("/suite/EA", 0),
        ("/suite/EA", 100),
        ("/case/EA", 0),
        ("/case/EA", 100),
    ]


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


def test_cli_api_failure_is_nonzero_and_never_prints_token(monkeypatch, capsys):
    token = "super-secret-qase-token"
    monkeypatch.setenv("QASE_API_TOKEN", token)

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
    failure_response, expected_detail, monkeypatch, capsys
):
    token = "super-secret-qase-token"
    monkeypatch.setenv("QASE_API_TOKEN", token)
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

    assert f"Qase API PATCH /case/EA/11 failed (HTTP 422): {expected_detail}" in output.err
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

    with pytest.raises(qase.QaseSyncError, match="unsuccessful response: Validation failed"):
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


def test_cli_dry_run_prints_summary_without_writing_or_exposing_token(monkeypatch, capsys):
    token = "super-secret-qase-token"
    monkeypatch.setenv("QASE_API_TOKEN", token)
    session = FakeSession(
        lambda method, path, _kwargs: _list_response([])
        if (method, path) == ("GET", "/suite/EA")
        else pytest.fail("Unexpected HTTP request")
    )
    monkeypatch.setattr(qase.requests, "Session", lambda: session)

    assert qase.main(["--dry-run"]) == 0
    output = capsys.readouterr()

    assert output.out.strip() == (
        "dry-run suites_created=1 cases_created=1 "
        "cases_updated=0 cases_unchanged=0"
    )
    assert token not in output.out + output.err
    assert session.headers["Token"] == token
    assert all(method == "GET" for method, _, _ in session.calls)


@pytest.mark.parametrize("dry_run", [True, False])
def test_cli_update_diff_is_dry_run_only_and_redacts_raw_values(
    dry_run, monkeypatch, capsys
):
    token = "super-secret-qase-token"
    monkeypatch.setenv("QASE_API_TOKEN", token)
    desired = qase._case_payload(_suites()[0]["cases"][0], 7)
    stored = {
        "id": 11,
        **desired,
        "priority": 2,
        "description": f"Remote description with {token}",
        "preconditions": f"Remote preconditions with {token}",
        "steps": [{"action": token, "expected_result": token}],
        "unmanaged_api_field": f"Raw response with {token}",
    }

    def handler(method, path, _kwargs):
        if (method, path) == ("GET", "/suite/EA"):
            return _list_response([{"id": 7, "title": "Event Discovery"}])
        if (method, path) == ("GET", "/case/EA"):
            return _list_response([{"id": 11, "title": desired["title"]}])
        if (method, path) == ("GET", "/case/EA/11"):
            return _response({"status": True, "result": stored})
        if (method, path) == ("PATCH", "/case/EA/11") and not dry_run:
            return _response({"status": True, "result": {"id": 11}})
        raise AssertionError((method, path))

    session = FakeSession(handler)
    monkeypatch.setattr(qase.requests, "Session", lambda: session)

    assert qase.main(["--dry-run"] if dry_run else []) == 0
    output = capsys.readouterr()

    summary = "suites_created=0 cases_created=0 cases_updated=1 cases_unchanged=0"
    if dry_run:
        assert output.out.splitlines() == [
            "UPDATE: Event Discovery / Canceled Ticketmaster events are excluded",
            "priority: 2 -> 1",
            "description: changed",
            "preconditions: changed",
            "steps: changed",
            f"dry-run {summary}",
        ]
        assert all(method == "GET" for method, _, _ in session.calls)
    else:
        assert output.out.strip() == summary
        assert any(method == "PATCH" for method, _, _ in session.calls)
    assert token not in output.out + output.err
    assert "unmanaged_api_field" not in output.out


def test_network_error_does_not_expose_request_exception_text(monkeypatch, capsys):
    token = "super-secret-qase-token"
    monkeypatch.setenv("QASE_API_TOKEN", token)

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
