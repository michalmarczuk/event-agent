"""Synchronize repository-owned classic test cases with Qase project EA."""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

import requests
import yaml

API_BASE_URL = "https://api.qase.io/v1"
PROJECT_CODE = "EA"
CASES_FILE = Path(__file__).resolve().parents[1] / "tests" / "qase_cases.yaml"
PAGE_SIZE = 100
REQUEST_TIMEOUT = 15
PRIORITIES = {"undefined": 0, "high": 1, "medium": 2, "low": 3}
CASE_STATUSES = {"active": 0, "draft": 1, "deprecated": 2}
SUMMARY_KEYS = ("suites_created", "cases_created", "cases_updated", "cases_unchanged")
_ERROR_DETAIL_LIMIT = 240
_ERROR_PART_LIMIT = 160
_SENSITIVE_LABEL = re.compile(
    r"authorization|token|api.?key|secret|password|header|cookie|payload|request",
    re.IGNORECASE,
)
_SENSITIVE_TEXT = re.compile(
    r"\b(?:authorization|token|api[-_ ]?key|headers?|cookies?|payload|request body)\b\s*(?::|=|\s)",
    re.IGNORECASE,
)


class QaseSyncError(RuntimeError):
    """A local case definition or Qase API response prevents safe synchronization."""


def _safe_error_text(value: str, token: str) -> str:
    if token:
        value = value.replace(token, "[redacted]")
    value = re.sub(
        r"\b(?:Bearer|Basic)\s+\S+", "[redacted]", value, flags=re.IGNORECASE
    )
    sensitive = _SENSITIVE_TEXT.search(value)
    if sensitive:
        value = value[: sensitive.start()] + "[redacted]"
    if "{" in value:
        value = value.split("{", 1)[0] + "[details omitted]"
    value = re.sub(r"<[^>]*>", " ", value)
    value = " ".join(
        "".join(char if char.isprintable() else " " for char in value).split()
    )
    return value[:_ERROR_PART_LIMIT].rstrip()


def _validation_fragments(
    value: Any, token: str, *, field_errors: bool = False
) -> list[str]:
    if isinstance(value, str):
        fragment = _safe_error_text(value, token)
        return [fragment] if fragment else []
    if isinstance(value, list):
        return [
            fragment
            for item in value[:3]
            for fragment in _validation_fragments(item, token)
        ]
    if not isinstance(value, dict):
        return []
    fragments = []
    if field_errors:
        for field, problem in list(value.items())[:3]:
            if (
                isinstance(field, str)
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,39}", field)
                and not _SENSITIVE_LABEL.search(field)
            ):
                fragments.extend(
                    f"{field}: {fragment}"
                    for fragment in _validation_fragments(problem, token)
                )
    else:
        for key in ("error", "message", "errorMessage", "detail", "errors"):
            if key in value:
                fragments.extend(
                    _validation_fragments(value[key], token, field_errors=key == "errors")
                )
    return fragments


def _api_error_detail(response: requests.Response, token: str) -> str:
    try:
        body = response.json()
    except ValueError:
        return _safe_error_text(response.text, token)
    if not isinstance(body, dict):
        return ""
    fragments = []
    for key in ("error", "message", "errorMessage", "errors", "result"):
        if key in body:
            fragments.extend(
                _validation_fragments(body[key], token, field_errors=key == "errors")
            )
    return "; ".join(dict.fromkeys(fragments))[:_ERROR_DETAIL_LIMIT].rstrip()


def load_cases(path: Path) -> list[dict[str, Any]]:
    """Load and validate the repository's Qase suite and case definitions."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise QaseSyncError(f"Cannot read Qase cases from {path}: {error}") from None

    if not isinstance(document, dict) or not isinstance(document.get("suites"), list):
        raise QaseSyncError("Qase cases YAML must contain a suites list")

    suite_names = set()
    qase_ids = set()
    for suite in document["suites"]:
        if not isinstance(suite, dict) or not isinstance(suite.get("name"), str):
            raise QaseSyncError("Each suite needs a name")
        name = suite["name"]
        if not name.strip() or name in suite_names:
            raise QaseSyncError(f"Duplicate or empty suite name: {name!r}")
        suite_names.add(name)
        if not isinstance(suite.get("cases"), list):
            raise QaseSyncError(f"Suite {name!r} needs a cases list")
        suite_status = suite.get("status", "active")
        if not isinstance(suite_status, str) or suite_status not in CASE_STATUSES:
            raise QaseSyncError(f"Suite {name!r} has an unsupported status")

        titles = set()
        for case in suite["cases"]:
            if not isinstance(case, dict):
                raise QaseSyncError(f"Suite {name!r} contains an invalid case")
            title = case.get("title")
            if not isinstance(title, str) or not title.strip() or title in titles:
                raise QaseSyncError(f"Duplicate or empty case title in {name!r}")
            titles.add(title)
            if any(not isinstance(case.get(key), str) for key in ("description", "preconditions")):
                raise QaseSyncError(f"Case {title!r} needs description and preconditions")
            priority = case.get("priority")
            if not isinstance(priority, str) or priority not in PRIORITIES:
                raise QaseSyncError(f"Case {title!r} has an unsupported priority")
            if not isinstance(case.get("automated"), bool):
                raise QaseSyncError(f"Case {title!r} needs a boolean automated value")
            status = case.get("status", suite_status)
            if not isinstance(status, str) or status not in CASE_STATUSES:
                raise QaseSyncError(f"Case {title!r} has an unsupported status")
            case["status"] = status
            if "qase_id" in case:
                qase_id = case["qase_id"]
                if (
                    not isinstance(qase_id, int)
                    or isinstance(qase_id, bool)
                    or qase_id <= 0
                ):
                    raise QaseSyncError(f"Case {title!r} has an invalid qase_id")
                if qase_id in qase_ids:
                    raise QaseSyncError(f"Duplicate qase_id: {qase_id}")
                qase_ids.add(qase_id)
            steps = case.get("steps")
            if not isinstance(steps, list) or not steps:
                raise QaseSyncError(f"Case {title!r} needs classic steps")
            for step in steps:
                if not isinstance(step, dict) or any(
                    not isinstance(step.get(key), str) or not step[key].strip()
                    for key in ("action", "expected")
                ):
                    raise QaseSyncError(f"Case {title!r} has an invalid step")

    return document["suites"]


def _request(
    session: requests.Session,
    method: str,
    path: str,
    *,
    params: dict[str, int] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        response = session.request(
            method,
            f"{API_BASE_URL}{path}",
            params=params,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.HTTPError as error:
        failed_response = error.response
        status = failed_response.status_code if failed_response is not None else "unknown"
        token = session.headers.get("Token", "")
        detail = (
            _api_error_detail(failed_response, token)
            if failed_response is not None
            else ""
        )
        suffix = f": {detail}" if detail else ""
        raise QaseSyncError(
            f"Qase API {method} {path} failed (HTTP {status}){suffix}"
        ) from None
    except requests.RequestException as error:
        raise QaseSyncError(
            f"Qase API {method} {path} failed ({type(error).__name__})"
        ) from None

    try:
        body = response.json()
    except ValueError:
        raise QaseSyncError(f"Qase API {method} {path} returned invalid JSON") from None
    if not isinstance(body, dict) or body.get("status") is not True:
        detail = _api_error_detail(response, session.headers.get("Token", ""))
        suffix = f": {detail}" if detail else ""
        raise QaseSyncError(
            f"Qase API {method} {path} returned an unsuccessful response{suffix}"
        )
    result = body.get("result")
    if not isinstance(result, dict):
        raise QaseSyncError(f"Qase API {method} {path} returned no result")
    return result


def _list_entities(
    session: requests.Session, path: str, *, suite_id: int | None = None
) -> list[dict[str, Any]]:
    entities = []
    offset = 0
    while True:
        params = {"limit": PAGE_SIZE, "offset": offset}
        if suite_id is not None:
            params["suite_id"] = suite_id
        result = _request(session, "GET", path, params=params)
        page = result.get("entities")
        if not isinstance(page, list) or any(not isinstance(item, dict) for item in page):
            raise QaseSyncError(f"Qase API GET {path} returned invalid entities")
        entities.extend(page)
        offset += len(page)
        total = result.get("filtered")
        if not isinstance(total, int) or isinstance(total, bool):
            total = result.get("total")
        if isinstance(total, int) and not isinstance(total, bool):
            if offset >= total:
                break
            if not page:
                raise QaseSyncError(f"Qase API GET {path} stopped before all pages")
        elif len(page) < PAGE_SIZE:
            break
    return entities


def _case_payload(case: dict[str, Any], suite_id: int) -> dict[str, Any]:
    return {
        "title": case["title"],
        "suite_id": suite_id,
        "description": case["description"],
        "preconditions": case["preconditions"],
        "priority": PRIORITIES[case["priority"]],
        "status": CASE_STATUSES[case["status"]],
        "isManual": int(not case["automated"]),
        "isToBeAutomated": 0,
        "steps_type": "classic",
        "steps": [
            {"action": step["action"], "expected_result": step["expected"]}
            for step in case["steps"]
        ],
    }


def _normalized_flag(value: object) -> int | None:
    if type(value) is bool:
        return int(value)
    if type(value) is int and value in (0, 1):
        return value
    return None


def _normalized_status(value: object) -> int | None:
    if type(value) is int and value in CASE_STATUSES.values():
        return value
    if isinstance(value, str):
        return CASE_STATUSES.get(value.casefold())
    return None


def _case_differences(existing: dict[str, Any], desired: dict[str, Any]) -> list[str]:
    differences = []
    if existing.get("title") != desired["title"]:
        differences.append("title: changed")
    if existing.get("suite_id") != desired["suite_id"]:
        differences.append("suite: changed")
    priority = existing.get("priority")
    if priority != desired["priority"]:
        if type(priority) is int:
            differences.append(f"priority: {priority} -> {desired['priority']}")
        else:
            differences.append("priority: changed")
    if _normalized_status(existing.get("status")) != desired["status"]:
        differences.append("status: changed")
    manual = _normalized_flag(existing.get("isManual"))
    to_be_automated = _normalized_flag(existing.get("isToBeAutomated"))
    if manual != desired["isManual"] or to_be_automated != desired["isToBeAutomated"]:
        differences.append("automated: changed")
    for field in ("description", "preconditions"):
        if (existing.get(field) or "") != desired[field]:
            differences.append(f"{field}: changed")
    if existing.get("steps_type") != desired["steps_type"]:
        differences.append("steps_type: changed")
    steps = existing.get("steps")
    if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
        differences.append("steps: changed")
    elif [
        {"action": step.get("action"), "expected_result": step.get("expected_result")}
        for step in steps
    ] != desired["steps"]:
        differences.append("steps: changed")
    return differences


def _id(entity: dict[str, Any], kind: str) -> int:
    value = entity.get("id")
    if not isinstance(value, int) or isinstance(value, bool):
        raise QaseSyncError(f"Qase API returned a {kind} without an integer ID")
    return value


def _validate_case_reference(detail: dict[str, Any], case: dict[str, Any]) -> None:
    """Verify that a referenced Qase ID still resolves to the expected case."""

    case_id = case["qase_id"]
    resolved_id = _id(detail, "case")
    if resolved_id != case_id:
        raise QaseSyncError(
            f"Qase case ID {case_id} resolved as unexpected ID {resolved_id}"
        )
    if detail.get("title") != case["title"]:
        raise QaseSyncError(
            f"Qase case ID {case_id} resolves to a different title; "
            f"expected {case['title']!r}"
        )
def sync_cases(
    session: requests.Session, suites: list[dict[str, Any]], *, dry_run: bool = False
) -> dict[str, int]:
    """Create or update repository cases, or count planned changes in dry-run mode."""
    summary = dict.fromkeys(SUMMARY_KEYS, 0)
    existing_suites = {
        suite.get("title"): suite
        for suite in _list_entities(session, f"/suite/{PROJECT_CODE}")
    }
    for suite in suites:
        existing_suite = existing_suites.get(suite["name"])
        if existing_suite is None:
            summary["suites_created"] += 1
            if dry_run:
                summary["cases_created"] += sum(
                    "qase_id" not in case for case in suite["cases"]
                )
                summary["cases_updated"] += sum(
                    "qase_id" in case for case in suite["cases"]
                )
                continue
            existing_suite = _request(
                session, "POST", f"/suite/{PROJECT_CODE}", payload={"title": suite["name"]}
            )
        suite_id = _id(existing_suite, "suite")
        existing_cases = {}
        if any("qase_id" not in case for case in suite["cases"]):
            existing_cases = {
                case.get("title"): case
                for case in _list_entities(
                    session, f"/case/{PROJECT_CODE}", suite_id=suite_id
                )
            }
        for case in suite["cases"]:
            desired = _case_payload(case, suite_id)
            referenced_id = case.get("qase_id")
            if referenced_id is not None:
                try:
                    detail = _request(
                        session,
                        "GET",
                        f"/case/{PROJECT_CODE}/{referenced_id}",
                    )
                except QaseSyncError as error:
                    raise QaseSyncError(
                        f"Cannot validate Qase case ID {referenced_id} for "
                        f"{suite['name']!r} / {case['title']!r}: {error}"
                    ) from None
                _validate_case_reference(detail, case)
                case_id = referenced_id
            else:
                existing_case = existing_cases.get(case["title"])
                if existing_case is None:
                    summary["cases_created"] += 1
                    if not dry_run:
                        _request(
                            session,
                            "POST",
                            f"/case/{PROJECT_CODE}",
                            payload=desired,
                        )
                    continue
                case_id = _id(existing_case, "case")
                detail = _request(
                    session, "GET", f"/case/{PROJECT_CODE}/{case_id}"
                )
            differences = _case_differences(detail, desired)
            if not differences:
                summary["cases_unchanged"] += 1
            else:
                summary["cases_updated"] += 1
                if dry_run:
                    print(f"UPDATE: {suite['name']} / {case['title']}")
                    for difference in differences:
                        print(difference)
                else:
                    _request(
                        session, "PATCH", f"/case/{PROJECT_CODE}/{case_id}", payload=desired
                    )
    return summary


def main(argv: list[str] | None = None) -> int:
    """Run the Qase sync CLI and return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Count changes without writing")
    args = parser.parse_args(argv)

    try:
        token = os.environ.get("QASE_API_TOKEN")
        if not token:
            raise QaseSyncError("QASE_API_TOKEN is required")
        suites = load_cases(CASES_FILE)
        with requests.Session() as session:
            session.headers.update({"Token": token, "Accept": "application/json"})
            summary = sync_cases(session, suites, dry_run=args.dry_run)
    except QaseSyncError as error:
        print(f"Qase sync failed: {error}", file=sys.stderr)
        return 1

    prefix = "dry-run " if args.dry_run else ""
    print(prefix + " ".join(f"{key}={summary[key]}" for key in SUMMARY_KEYS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
