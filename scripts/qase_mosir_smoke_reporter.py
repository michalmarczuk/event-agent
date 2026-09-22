"""Report one production-image MOSiR smoke probe to Qase TestOps."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_API_BASE_URL = "https://api.qase.io/v1"
_PROJECT_CODE = "EA"
_REPORTING_FAILURE_EXIT_CODE = 1


class QaseReportingError(RuntimeError):
    """A safe summary of a Qase reporting operation failure."""


@dataclass(frozen=True)
class QaseMosirReporter:
    """Perform the limited Qase API operations required by the MOSiR probe."""

    token: str

    def create_run(self, case_id: int, title: str) -> int:
        """Create a run containing only the MOSiR live-smoke case."""
        result = self._request(
            "create run",
            "POST",
            f"/run/{_PROJECT_CODE}",
            {
                "title": title,
                "include_all_cases": False,
                "cases": [case_id],
                "tags": ["live", "smoke", "hf", "mosir_tychy"],
            },
        )
        return _result_id(result, "run")

    def submit_result(self, run_id: int, case_id: int, status: str) -> None:
        """Submit the safe passed or failed outcome for the MOSiR case."""
        self._request(
            "submit result",
            "POST",
            f"/result/{_PROJECT_CODE}/{run_id}",
            {"case_id": case_id, "status": status},
        )

    def complete_run(self, run_id: int) -> None:
        """Complete a Qase run after attempting to submit its only result."""
        self._request(
            "complete run",
            "POST",
            f"/run/{_PROJECT_CODE}/{run_id}/complete",
            None,
            require_result=False,
        )

    def _request(
        self,
        operation: str,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        *,
        require_result: bool = True,
    ) -> dict[str, Any] | None:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{_API_BASE_URL}{path}",
            data=data,
            method=method,
            headers={
                "Token": self.token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=15) as response:  # noqa: S310
                body = response.read()
        except HTTPError as error:
            raise QaseReportingError(
                f"Qase {operation} failed (HTTP {error.code})"
            ) from None
        except URLError as error:
            raise QaseReportingError(
                f"Qase {operation} failed ({type(error.reason).__name__})"
            ) from None
        except OSError as error:
            raise QaseReportingError(
                f"Qase {operation} failed ({type(error).__name__})"
            ) from None

        try:
            response_body = json.loads(body)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            raise QaseReportingError(
                f"Qase {operation} returned invalid JSON"
            ) from None
        if not isinstance(response_body, dict) or response_body.get("status") is not True:
            raise QaseReportingError(f"Qase {operation} returned an unsuccessful response")
        result = response_body.get("result")
        if not require_result:
            return result if isinstance(result, dict) else None
        if not isinstance(result, dict):
            raise QaseReportingError(f"Qase {operation} returned no result")
        return result


def _result_id(result: dict[str, Any], kind: str) -> int:
    value = result.get("id")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise QaseReportingError(f"Qase {kind} response has no valid ID")
    return value


def _run_probe(command: Sequence[str]) -> int:
    try:
        return subprocess.run(command, check=False).returncode
    except OSError as error:
        print(
            f"MOSIR_QASE_LIVE_SMOKE_FAILED reason=probe_{type(error).__name__}",
            file=sys.stderr,
        )
        return _REPORTING_FAILURE_EXIT_CODE


def report_probe_outcome(
    reporter: QaseMosirReporter,
    case_id: int,
    title: str,
    probe: Callable[[], int],
) -> int:
    """Run the probe once and report its outcome, completing the Qase run."""
    try:
        run_id = reporter.create_run(case_id, title)
    except QaseReportingError as error:
        print(f"MOSIR_QASE_LIVE_SMOKE_FAILED reason={error}", file=sys.stderr)
        return _REPORTING_FAILURE_EXIT_CODE

    probe_status = probe()
    result_status = "passed" if probe_status == 0 else "failed"
    reporting_failed = False
    try:
        reporter.submit_result(run_id, case_id, result_status)
    except QaseReportingError as error:
        reporting_failed = True
        print(f"MOSIR_QASE_LIVE_SMOKE_FAILED reason={error}", file=sys.stderr)
    try:
        reporter.complete_run(run_id)
    except QaseReportingError as error:
        reporting_failed = True
        print(f"MOSIR_QASE_LIVE_SMOKE_FAILED reason={error}", file=sys.stderr)

    if reporting_failed:
        return _REPORTING_FAILURE_EXIT_CODE
    return probe_status


def _required_token() -> str:
    token = os.environ.get("QASE_API_TOKEN", "")
    if not token:
        raise QaseReportingError("QASE_API_TOKEN is required for Qase MOSiR reporting")
    return token


def main(argv: Sequence[str] | None = None) -> int:
    """Run the production MOSiR probe and report it as one Qase result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", type=int, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--probe", required=True)
    args = parser.parse_args(argv)
    if args.case_id <= 0:
        parser.error("--case-id must be a positive integer")

    try:
        reporter = QaseMosirReporter(_required_token())
    except QaseReportingError as error:
        print(f"MOSIR_QASE_LIVE_SMOKE_FAILED reason={error}", file=sys.stderr)
        return _REPORTING_FAILURE_EXIT_CODE

    return report_probe_outcome(
        reporter,
        args.case_id,
        args.title,
        lambda: _run_probe((args.probe,)),
    )


if __name__ == "__main__":
    raise SystemExit(main())
