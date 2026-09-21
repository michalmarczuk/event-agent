import ast
from collections import Counter
from pathlib import Path

import pytest
import requests

from scripts import sync_qase_cases as qase
from tests.support.qase_sync_support import (
    FakeSession,
    _list_response,
    _response,
    _suites,
    _text_response,
    _use_test_catalog,
)


_SMOKE_CASE_TITLES = {
    "Ticketmaster Discovery API is reachable with valid credentials",
    "Telegram bot authentication succeeds without sending a message",
    "Camoufox can reach Ticketmaster through the configured browser network path",
    "Elastic OTLP endpoint accepts an event-agent log record",
}

_SYSTEM_CASE_TITLES = {
    "Daily job happy path completes delivery and persists history",
    "Telegram failure prevents history persistence",
    "No eligible events sends an explicit no-events notification",
    "Previously seen events are not delivered again",
    "Canceled Ticketmaster events are filtered before recommendation",
    "OpenAI failure prevents delivery and partial history persistence",
    "Only delivered recommendations are persisted from multiple candidates",
    "Ticketmaster failure prevents delivery and persistence",
    "Ungrounded recommendation is rejected before delivery",
}


def _qualified_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _pytest_qase_links():
    tests_root = Path(__file__).resolve().parents[1]
    links = []
    for path in sorted(tests_root.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and _qualified_name(node.func) == "qase.id"
            ):
                continue
            assert len(node.args) == 1 and not node.keywords
            value = node.args[0]
            assert isinstance(value, ast.Constant)
            assert isinstance(value.value, int) and not isinstance(value.value, bool)

            parent = node
            parameter = None
            function = None
            while parent in parents:
                parent = parents[parent]
                if (
                    parameter is None
                    and isinstance(parent, ast.Call)
                    and _qualified_name(parent.func) == "pytest.param"
                ):
                    parameter = parent
                if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    function = parent
                    break

            assert function is not None and function.name.startswith("test_")
            if parameter is not None:
                assert any(
                    _qualified_name(candidate) == "pytest.mark.regression"
                    for candidate in ast.walk(parameter)
                ) or (
                    any(
                        _qualified_name(candidate) == "pytest.mark.smoke"
                        for candidate in ast.walk(parameter)
                    )
                    and any(
                        _qualified_name(candidate) == "pytest.mark.live"
                        for candidate in ast.walk(parameter)
                    )
                )
                owner = (path, function.name, parameter.lineno)
            else:
                decorator_names = {
                    _qualified_name(decorator)
                    for decorator in function.decorator_list
                }
                assert (
                    "pytest.mark.regression" in decorator_names
                    or {
                        "pytest.mark.smoke",
                        "pytest.mark.live",
                    }.issubset(decorator_names)
                    or path.parent.name == "system"
                )
                assert not any(
                    isinstance(decorator, ast.Call)
                    and _qualified_name(decorator.func) == "pytest.mark.parametrize"
                    for decorator in function.decorator_list
                )
                owner = (path, function.name, None)
            links.append((value.value, path, owner))
    return links


def test_qase_catalog_and_pytest_traceability_are_complete():
    suites = qase.load_cases(qase.CASES_FILE)
    cases = [case for suite in suites for case in suite["cases"]]

    assert len(cases) == 36
    assert all("qase_id" in case for case in cases)
    catalog_ids = [case["qase_id"] for case in cases]
    assert all(type(case_id) is int and case_id > 0 for case_id in catalog_ids)
    assert len(set(catalog_ids)) == len(catalog_ids)

    active_cases = [case for case in cases if case["status"] == "active"]
    deprecated_cases = [case for case in cases if case["status"] == "deprecated"]
    assert len(active_cases) == 13
    assert len(deprecated_cases) == 23
    assert {case["qase_id"] for case in deprecated_cases} == set(range(1, 24))

    active_suites = {
        suite["name"] for suite in suites if suite["status"] == "active"
    }
    assert active_suites == {"System", "System Integration"}

    links = _pytest_qase_links()
    linked_ids = [case_id for case_id, _, _ in links]
    assert len(links) == 13
    assert len({owner for _, _, owner in links}) == 13
    assert Counter(linked_ids) == Counter(
        case["qase_id"] for case in active_cases
    )

    tests_root = Path(__file__).resolve().parents[1]
    qase_marker = ".".join(("pytest", "mark", "qase"))
    assert all(
        _qualified_name(node) != qase_marker
        for path in sorted(tests_root.rglob("test_*.py"))
        for node in ast.walk(
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        )
    )

    system_links = [link for link in links if link[1].parent.name == "system"]
    smoke_links = [
        link for link in links if link[1].parent.name == "system_integration"
    ]
    assert len(system_links) == 9
    assert len(smoke_links) == 4

    smoke_ids = {
        case["qase_id"]
        for case in active_cases
        if case["title"] in _SMOKE_CASE_TITLES
    }
    assert smoke_ids == {24, 25, 26, 27}
    paths_by_id = {case_id: path for case_id, path, _ in links}
    assert all(
        paths_by_id[case_id].parent.name == "system_integration"
        for case_id in smoke_ids
    )

    system_ids = {
        case["qase_id"]
        for case in active_cases
        if case["title"] in _SYSTEM_CASE_TITLES
    }
    assert system_ids == set(range(28, 37))
    paths_by_id = {case_id: path for case_id, path, _ in links}
    assert all(paths_by_id[case_id].parent.name == "system" for case_id in system_ids)


@pytest.mark.parametrize(
    ("priority", "expected_id"),
    [("undefined", 0), ("high", 1), ("medium", 2), ("low", 3)],
)
def test_priority_names_map_to_qase_ids(priority, expected_id):
    case = dict(_suites()[0]["cases"][0], priority=priority)
    case["qase_id"] = 123

    payload = qase._case_payload(case, 7)

    assert payload["priority"] == expected_id
    assert "qase_id" not in payload


@pytest.mark.parametrize(
    ("status", "expected_id"),
    [("active", 0), ("draft", 1), ("deprecated", 2)],
)
def test_case_status_names_map_to_qase_ids(status, expected_id):
    case = dict(_suites()[0]["cases"][0], status=status)

    assert qase._case_payload(case, 7)["status"] == expected_id


def test_sync_marks_existing_case_as_deprecated():
    suites = _suites()
    case = suites[0]["cases"][0]
    case.update({"qase_id": 11, "status": "deprecated"})
    desired = qase._case_payload(case, 7)
    remote = {"id": 11, **desired, "status": 0}

    def handler(method, path, kwargs):
        if (method, path) == ("GET", "/suite/EA"):
            return _list_response([{"id": 7, "title": "Event Discovery"}])
        if (method, path) == ("GET", "/case/EA/11"):
            return _response({"status": True, "result": remote})
        if (method, path) == ("PATCH", "/case/EA/11"):
            assert kwargs["json"] == desired
            return _response({"status": True, "result": {"id": 11}})
        raise AssertionError((method, path))

    summary = qase.sync_cases(FakeSession(handler), suites)

    assert summary == {
        "suites_created": 0,
        "cases_created": 0,
        "cases_updated": 1,
        "cases_unchanged": 0,
    }


def test_sync_moves_referenced_case_to_new_suite():
    suites = _suites()
    suites[0]["name"] = "System Integration"
    case = suites[0]["cases"][0]
    case.update({"qase_id": 24, "status": "active"})
    desired = qase._case_payload(case, 42)
    remote = {"id": 24, **desired, "suite_id": 7}

    def handler(method, path, kwargs):
        if (method, path) == ("GET", "/suite/EA"):
            return _list_response([])
        if (method, path) == ("POST", "/suite/EA"):
            assert kwargs["json"] == {"title": "System Integration"}
            return _response({"status": True, "result": {"id": 42}})
        if (method, path) == ("GET", "/case/EA/24"):
            return _response({"status": True, "result": remote})
        if (method, path) == ("PATCH", "/case/EA/24"):
            assert kwargs["json"] == desired
            return _response({"status": True, "result": {"id": 24}})
        raise AssertionError((method, path))

    summary = qase.sync_cases(FakeSession(handler), suites)

    assert summary == {
        "suites_created": 1,
        "cases_created": 0,
        "cases_updated": 1,
        "cases_unchanged": 0,
    }


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
