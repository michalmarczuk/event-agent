import json

import pytest

from scripts import sync_qase_cases as qase
from tests.support.qase_sync_support import (
    FakeSession,
    _list_response,
    _response,
    _suites,
    _use_test_catalog,
)


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


def test_sync_creates_cases_across_multiple_suites():
    suites = _suites()
    suites.append(
        {
            "name": "Price Enrichment",
            "cases": [{**suites[0]["cases"][0], "title": "Scraped prices replace old prices"}],
        }
    )
    suite_ids = {"Event Discovery": 7, "Price Enrichment": 8}
    created_cases = []

    def handler(method, path, kwargs):
        if (method, path) == ("GET", "/suite/EA"):
            return _list_response([])
        if (method, path) == ("POST", "/suite/EA"):
            return _response(
                {"status": True, "result": {"id": suite_ids[kwargs["json"]["title"]]}}
            )
        if (method, path) == ("GET", "/case/EA"):
            return _list_response([])
        if (method, path) == ("POST", "/case/EA"):
            created_cases.append((kwargs["json"]["suite_id"], kwargs["json"]["title"]))
            return _response({"status": True, "result": {"id": len(created_cases)}})
        raise AssertionError((method, path))

    summary = qase.sync_cases(FakeSession(handler), suites)

    assert summary == {
        "suites_created": 2,
        "cases_created": 2,
        "cases_updated": 0,
        "cases_unchanged": 0,
    }
    assert created_cases == [
        (7, "Canceled Ticketmaster events are excluded"),
        (8, "Scraped prices replace old prices"),
    ]


def test_sync_creates_multiple_cases_in_one_suite():
    suites = _suites()
    suites[0]["cases"].append(
        {**suites[0]["cases"][0], "title": "Postponed events remain eligible"}
    )
    created_titles = []

    def handler(method, path, kwargs):
        if (method, path) == ("GET", "/suite/EA"):
            return _list_response([{"id": 7, "title": "Event Discovery"}])
        if (method, path) == ("GET", "/case/EA"):
            assert kwargs["params"]["suite_id"] == 7
            return _list_response([])
        if (method, path) == ("POST", "/case/EA"):
            created_titles.append(kwargs["json"]["title"])
            return _response({"status": True, "result": {"id": len(created_titles)}})
        raise AssertionError((method, path))

    summary = qase.sync_cases(FakeSession(handler), suites)

    assert summary == {
        "suites_created": 0,
        "cases_created": 2,
        "cases_updated": 0,
        "cases_unchanged": 0,
    }
    assert created_titles == [
        "Canceled Ticketmaster events are excluded",
        "Postponed events remain eligible",
    ]


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


def test_cli_dry_run_prints_summary_without_writing_or_exposing_token(
    monkeypatch, tmp_path, capsys
):
    token = "super-secret-qase-token"
    monkeypatch.setenv("QASE_API_TOKEN", token)
    _use_test_catalog(monkeypatch, tmp_path)
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
    dry_run, monkeypatch, tmp_path, capsys
):
    token = "super-secret-qase-token"
    monkeypatch.setenv("QASE_API_TOKEN", token)
    _use_test_catalog(monkeypatch, tmp_path)
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
