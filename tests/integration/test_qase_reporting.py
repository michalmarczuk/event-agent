"""Integration tests for opt-in Qase execution reporting safeguards."""

import json
import os
from pathlib import Path
import subprocess
import sys


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_QASE_CONFIG = _REPOSITORY_ROOT / "qase.config.json"
_QASE_RUNNER = _REPOSITORY_ROOT / "scripts" / "run_qase_regression.sh"
_SECRET = "qase-regression-test-secret"


def _environment_without_qase_reporting() -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "QASE_API_TOKEN",
        "QASE_MODE",
        "QASE_TESTOPS_API_TOKEN",
        "QASE_TESTOPS_PROJECT",
        "QASE_TESTOPS_RUN_TITLE",
        "QASE_TESTOPS_RUN_COMPLETE",
        "QASE_TESTOPS_RUN_TAGS",
        "QASE_TESTOPS_SHOW_PUBLIC_REPORT_LINK",
    ):
        environment.pop(name, None)
    return environment


def _run_isolated_pytest(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = _environment_without_qase_reporting()
    environment.update(
        {
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "QASE_MODE": "testops",
            "QASE_TESTOPS_API_TOKEN": _SECRET,
        }
    )
    return subprocess.run(
        [sys.executable, "-m", "pytest", *arguments],
        cwd=_REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_qase_reporting_is_off_by_default():
    assert json.loads(_QASE_CONFIG.read_text()) == {
        "mode": "off",
        "testops": {
            "project": "EA",
            "run": {"complete": True},
        },
    }


def test_qase_regression_runner_rejects_missing_token():
    result = subprocess.run(
        [_QASE_RUNNER],
        cwd=_REPOSITORY_ROOT,
        env=_environment_without_qase_reporting(),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode != 0
    assert "QASE_API_TOKEN is required" in result.stderr


def test_qase_regression_runner_selects_only_offline_linked_tests(
    tmp_path: Path,
):
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    capture_path = tmp_path / "capture"

    pytest_stub = bin_directory / "pytest"
    pytest_stub.write_text(
        """#!/bin/sh
printf '%s\\n' "$@" > "${QASE_TEST_CAPTURE}.args"
{
  printf 'mode=%s\\n' "$QASE_MODE"
  printf 'project=%s\\n' "$QASE_TESTOPS_PROJECT"
  printf 'title=%s\\n' "$QASE_TESTOPS_RUN_TITLE"
  printf 'complete=%s\\n' "$QASE_TESTOPS_RUN_COMPLETE"
  printf 'tags=%s\\n' "$QASE_TESTOPS_RUN_TAGS"
  printf 'public=%s\\n' "$QASE_TESTOPS_SHOW_PUBLIC_REPORT_LINK"
  if [ "$QASE_TESTOPS_API_TOKEN" = "$QASE_API_TOKEN" ]; then
    printf 'token_mapped=yes\\n'
  else
    printf 'token_mapped=no\\n'
  fi
} > "${QASE_TEST_CAPTURE}.env"
"""
    )
    pytest_stub.chmod(0o755)

    git_stub = bin_directory / "git"
    git_stub.write_text("#!/bin/sh\nprintf 'abc1234\\n'\n")
    git_stub.chmod(0o755)

    environment = _environment_without_qase_reporting()
    environment.update(
        {
            "PATH": f"{bin_directory}{os.pathsep}{environment['PATH']}",
            "QASE_API_TOKEN": _SECRET,
            "QASE_TEST_CAPTURE": str(capture_path),
        }
    )
    result = subprocess.run(
        [_QASE_RUNNER],
        cwd=_REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0
    assert (tmp_path / "capture.args").read_text().splitlines() == [
        "-m",
        "qase and not smoke",
        "-q",
    ]
    assert (tmp_path / "capture.env").read_text().splitlines() == [
        "mode=testops",
        "project=EA",
        "title=Event Agent - Offline Regression - abc1234",
        "complete=true",
        "tags=offline,regression",
        "public=false",
        "token_mapped=yes",
    ]
    assert _SECRET not in result.stdout
    assert _SECRET not in result.stderr


def test_qase_reporting_guard_rejects_an_unlinked_selected_test():
    result = _run_isolated_pytest(
        "-q",
        "tests/unit/test_config.py::test_load_scraper_proxy_url_is_optional",
    )
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "Qase reporting safety guard rejected 1 selected test" in output
    assert "qase marker expression" in output
    assert _SECRET not in output


def test_qase_reporting_guard_allows_only_linked_offline_selection():
    result = _run_isolated_pytest(
        "--collect-only",
        "-q",
        "-m",
        "qase and not smoke",
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "23/" in output or "23 tests collected" in output
    assert "tests/smoke/" not in output
    assert "Qase reporting safety guard rejected" not in output
    assert _SECRET not in output


def test_qase_reporting_guard_allows_only_linked_smoke_selection():
    result = _run_isolated_pytest(
        "--collect-only",
        "-q",
        "--run-smoke",
        "-m",
        "qase and smoke",
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "4/" in output or "4 tests collected" in output
    assert "tests/smoke/" in output
    assert "Qase reporting safety guard rejected" not in output
    assert _SECRET not in output
