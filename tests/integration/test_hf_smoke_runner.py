import os
from pathlib import Path
import subprocess

import pytest


_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_hf_smoke.sh"
_QASE_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "run_hf_qase_smoke.sh"
)
_RUNTIME_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "run_hf_smoke_runtime.sh"
)
_QASE_SECRET = "qase-smoke-test-secret"


def _environment_without_reporting() -> dict[str, str]:
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


def _copy_runner_with_runtime(tmp_path: Path, runner: Path) -> tuple[Path, Path]:
    copied_runner = tmp_path / runner.name
    copied_runner.write_text(runner.read_text(encoding="utf-8"), encoding="utf-8")
    copied_runner.chmod(0o755)

    capture_path = tmp_path / "capture"
    runtime = tmp_path / _RUNTIME_SCRIPT.name
    runtime.write_text(
        """#!/bin/sh
printf '%s\\n' "$@" > "${HF_SMOKE_CAPTURE}.args"
{
  printf 'mode=%s\\n' "${QASE_MODE:-}"
  printf 'project=%s\\n' "${QASE_TESTOPS_PROJECT:-}"
  printf 'title=%s\\n' "${QASE_TESTOPS_RUN_TITLE:-}"
  printf 'complete=%s\\n' "${QASE_TESTOPS_RUN_COMPLETE:-}"
  printf 'tags=%s\\n' "${QASE_TESTOPS_RUN_TAGS:-}"
  printf 'public=%s\\n' "${QASE_TESTOPS_SHOW_PUBLIC_REPORT_LINK:-}"
  if [ "${QASE_TESTOPS_API_TOKEN:-}" = "${HF_EXPECTED_QASE_TOKEN:-unused}" ]; then
    printf 'token_mapped=yes\\n'
  else
    printf 'token_mapped=no\\n'
  fi
  if [ -z "${QASE_API_TOKEN:-}" ]; then
    printf 'source_token_unset=yes\\n'
  else
    printf 'source_token_unset=no\\n'
  fi
} > "${HF_SMOKE_CAPTURE}.env"
exit "${HF_SMOKE_EXIT_CODE:-0}"
""",
        encoding="utf-8",
    )
    runtime.chmod(0o755)
    return copied_runner, capture_path


@pytest.mark.parametrize(
    ("configured", "expected_error"),
    [
        (
            {"TAILSCALE_EXIT_NODE": "100.64.0.1"},
            "TAILSCALE_AUTHKEY is required",
        ),
        (
            {"TAILSCALE_AUTHKEY": "tailscale-test-secret"},
            "TAILSCALE_EXIT_NODE is required",
        ),
    ],
)
def test_hf_smoke_runner_requires_tailscale_configuration(
    configured,
    expected_error,
):
    environment = os.environ.copy()
    environment.pop("TAILSCALE_AUTHKEY", None)
    environment.pop("TAILSCALE_EXIT_NODE", None)
    environment.update(configured)

    result = subprocess.run(
        ["/bin/sh", str(_SCRIPT)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 1
    assert expected_error in result.stderr
    assert "tailscale-test-secret" not in result.stdout + result.stderr


def test_hf_smoke_runner_preserves_cleanup_and_pytest_exit_contract():
    syntax_check = subprocess.run(
        ["/bin/sh", "-n", str(_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    script = _SCRIPT.read_text(encoding="utf-8")
    runtime_script = _RUNTIME_SCRIPT.read_text(encoding="utf-8")

    assert syntax_check.returncode == 0
    assert "export QASE_MODE=off" in script
    assert "pytest --run-smoke -m smoke -q" in script
    assert "trap cleanup EXIT" in runtime_script
    assert 'kill "$tailscaled_pid"' in runtime_script
    assert (
        "export SCRAPER_PROXY_URL=socks5://127.0.0.1:1055" in runtime_script
    )
    assert 'xvfb-run -a -e /dev/stderr "$@"' in runtime_script
    assert "pytest_status=$?" in runtime_script
    assert 'exit "$pytest_status"' in runtime_script


def test_hf_qase_smoke_runner_rejects_missing_token_before_runtime(
    tmp_path: Path,
):
    runner, capture_path = _copy_runner_with_runtime(tmp_path, _QASE_SCRIPT)
    environment = _environment_without_reporting()
    environment["HF_SMOKE_CAPTURE"] = str(capture_path)

    result = subprocess.run(
        ["/bin/sh", str(runner)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 2
    assert "QASE_API_TOKEN is required" in result.stderr
    assert not (tmp_path / "capture.args").exists()


def test_hf_qase_smoke_runner_configures_safe_selection_and_propagates_exit(
    tmp_path: Path,
):
    runner, capture_path = _copy_runner_with_runtime(tmp_path, _QASE_SCRIPT)
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    git_stub = bin_directory / "git"
    git_stub.write_text("#!/bin/sh\nprintf 'abc1234\\n'\n", encoding="utf-8")
    git_stub.chmod(0o755)

    secret_values = (
        _QASE_SECRET,
        "tailscale-smoke-test-secret",
        "telegram-smoke-test-secret",
        "elastic-smoke-test-secret",
        "proxy-smoke-test-secret",
    )
    environment = _environment_without_reporting()
    environment.update(
        {
            "PATH": f"{bin_directory}{os.pathsep}{environment['PATH']}",
            "QASE_API_TOKEN": _QASE_SECRET,
            "HF_EXPECTED_QASE_TOKEN": _QASE_SECRET,
            "HF_SMOKE_CAPTURE": str(capture_path),
            "HF_SMOKE_EXIT_CODE": "17",
            "TAILSCALE_AUTHKEY": secret_values[1],
            "TELEGRAM_BOT_TOKEN": secret_values[2],
            "ELASTIC_API_KEY": secret_values[3],
            "SCRAPER_PROXY_URL": f"socks5://user:{secret_values[4]}@proxy",
        }
    )

    result = subprocess.run(
        ["/bin/sh", str(runner)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 17
    assert (tmp_path / "capture.args").read_text().splitlines() == [
        "pytest",
        "--run-smoke",
        "-m",
        "qase and smoke",
        "-q",
    ]
    assert (tmp_path / "capture.env").read_text().splitlines() == [
        "mode=testops",
        "project=EA",
        "title=Event Agent - Live Smoke - abc1234",
        "complete=true",
        "tags=live,smoke,hf",
        "public=false",
        "token_mapped=yes",
        "source_token_unset=yes",
    ]
    output = result.stdout + result.stderr
    assert all(secret not in output for secret in secret_values)


def test_normal_hf_smoke_runner_keeps_qase_disabled(tmp_path: Path):
    runner, capture_path = _copy_runner_with_runtime(tmp_path, _SCRIPT)
    environment = _environment_without_reporting()
    environment.update(
        {
            "QASE_API_TOKEN": _QASE_SECRET,
            "QASE_MODE": "testops",
            "QASE_TESTOPS_API_TOKEN": _QASE_SECRET,
            "HF_EXPECTED_QASE_TOKEN": _QASE_SECRET,
            "HF_SMOKE_CAPTURE": str(capture_path),
        }
    )

    result = subprocess.run(
        ["/bin/sh", str(runner)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0
    assert (tmp_path / "capture.args").read_text().splitlines() == [
        "pytest",
        "--run-smoke",
        "-m",
        "smoke",
        "-q",
    ]
    captured_environment = (tmp_path / "capture.env").read_text().splitlines()
    assert "mode=off" in captured_environment
    assert "token_mapped=no" in captured_environment
    assert "source_token_unset=yes" in captured_environment
    assert _QASE_SECRET not in result.stdout + result.stderr
