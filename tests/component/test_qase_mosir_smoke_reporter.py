import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from scripts import qase_mosir_smoke_reporter as reporter_module

_TOKEN = "qase-mosir-test-token"
_WRAPPER = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "run_hf_qase_mosir_live_smoke.sh"
)


class _Response:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self._payload


class _Reporter:
    def __init__(self, *, create_error=None, submit_error=None, complete_error=None):
        self.create_error = create_error
        self.submit_error = submit_error
        self.complete_error = complete_error
        self.calls = []

    def create_run(self, case_id, title):
        self.calls.append(("create", case_id, title))
        if self.create_error:
            raise self.create_error
        return 901

    def submit_result(self, run_id, case_id, status):
        self.calls.append(("submit", run_id, case_id, status))
        if self.submit_error:
            raise self.submit_error

    def complete_run(self, run_id):
        self.calls.append(("complete", run_id))
        if self.complete_error:
            raise self.complete_error


def test_create_run_uses_only_the_mosir_case(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return _Response({"status": True, "result": {"id": 901}})

    monkeypatch.setattr(reporter_module, "urlopen", fake_urlopen)

    run_id = reporter_module.QaseMosirReporter(_TOKEN).create_run(
        39, "Event Agent - MOSiR Live Smoke"
    )

    assert run_id == 901
    request, timeout = requests[0]
    assert request.full_url == "https://api.qase.io/v1/run/EA"
    assert request.method == "POST"
    assert timeout == 15
    assert json.loads(request.data) == {
        "title": "Event Agent - MOSiR Live Smoke",
        "include_all_cases": False,
        "cases": [39],
        "tags": ["live", "smoke", "hf", "mosir_tychy"],
    }


def test_complete_run_accepts_a_success_response_without_a_result(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return _Response({"status": True})

    monkeypatch.setattr(reporter_module, "urlopen", fake_urlopen)

    reporter_module.QaseMosirReporter(_TOKEN).complete_run(901)

    request, timeout = requests[0]
    assert request.full_url == "https://api.qase.io/v1/run/EA/901/complete"
    assert request.method == "POST"
    assert request.data is None
    assert timeout == 15


@pytest.mark.parametrize("status", ["passed", "failed"])
def test_submit_result_uses_the_requested_pass_or_fail_payload(monkeypatch, status):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return _Response({"status": True, "result": {"id": 12}})

    monkeypatch.setattr(reporter_module, "urlopen", fake_urlopen)

    reporter_module.QaseMosirReporter(_TOKEN).submit_result(901, 39, status)

    request, timeout = requests[0]
    assert request.full_url == "https://api.qase.io/v1/result/EA/901"
    assert request.method == "POST"
    assert json.loads(request.data) == {"case_id": 39, "status": status}
    assert timeout == 15


@pytest.mark.parametrize("probe_status, expected_status", [(0, "passed"), (7, "failed")])
def test_probe_outcome_submits_pass_or_fail_and_completes_run(
    probe_status, expected_status
):
    reporter = _Reporter()

    exit_code = reporter_module.report_probe_outcome(
        reporter,
        39,
        "Event Agent - MOSiR Live Smoke",
        lambda: probe_status,
    )

    assert exit_code == probe_status
    assert reporter.calls == [
        ("create", 39, "Event Agent - MOSiR Live Smoke"),
        ("submit", 901, 39, expected_status),
        ("complete", 901),
    ]


def test_submit_failure_is_nonzero_and_still_attempts_completion(capsys):
    reporter = _Reporter(
        submit_error=reporter_module.QaseReportingError(
            "Qase submit result failed (HTTP 500)"
        )
    )

    exit_code = reporter_module.report_probe_outcome(
        reporter, 39, "Event Agent - MOSiR Live Smoke", lambda: 0
    )

    assert exit_code == 1
    assert reporter.calls[-1] == ("complete", 901)
    assert "Qase submit result failed (HTTP 500)" in capsys.readouterr().err


def test_create_failure_is_nonzero_without_running_the_probe(capsys):
    reporter = _Reporter(
        create_error=reporter_module.QaseReportingError(
            "Qase create run failed (HTTP 500)"
        )
    )
    probe_calls = []

    exit_code = reporter_module.report_probe_outcome(
        reporter,
        39,
        "Event Agent - MOSiR Live Smoke",
        lambda: probe_calls.append("called") or 0,
    )

    assert exit_code == 1
    assert probe_calls == []
    assert reporter.calls == [("create", 39, "Event Agent - MOSiR Live Smoke")]
    assert "Qase create run failed (HTTP 500)" in capsys.readouterr().err


def test_completion_failure_is_nonzero_after_a_successful_result(capsys):
    reporter = _Reporter(
        complete_error=reporter_module.QaseReportingError(
            "Qase complete run failed (HTTP 500)"
        )
    )

    exit_code = reporter_module.report_probe_outcome(
        reporter, 39, "Event Agent - MOSiR Live Smoke", lambda: 0
    )

    assert exit_code == 1
    assert reporter.calls == [
        ("create", 39, "Event Agent - MOSiR Live Smoke"),
        ("submit", 901, 39, "passed"),
        ("complete", 901),
    ]
    assert "Qase complete run failed (HTTP 500)" in capsys.readouterr().err


def test_api_error_and_missing_token_never_print_the_token(monkeypatch, capsys):
    def fake_urlopen(request, timeout):
        raise HTTPError(
            request.full_url,
            422,
            "validation failed",
            {},
            io.BytesIO(_TOKEN.encode("utf-8")),
        )

    monkeypatch.setattr(reporter_module, "urlopen", fake_urlopen)
    reporter = reporter_module.QaseMosirReporter(_TOKEN)
    with pytest.raises(reporter_module.QaseReportingError, match="HTTP 422"):
        reporter.create_run(39, "Event Agent - MOSiR Live Smoke")

    monkeypatch.delenv("QASE_API_TOKEN", raising=False)
    assert reporter_module.main(
        ["--case-id", "39", "--title", "run", "--probe", "/missing"]
    ) == 1
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert _TOKEN not in output


def test_wrapper_requires_the_token_and_runs_the_production_probe():
    script = _WRAPPER.read_text(encoding="utf-8")

    assert "QASE_API_TOKEN is required" in script
    assert "scripts.qase_mosir_smoke_reporter" in script
    assert "/app/scripts/run_hf_mosir_live_smoke.sh" in script
