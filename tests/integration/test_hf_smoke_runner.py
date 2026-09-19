import os
from pathlib import Path
import subprocess

import pytest


_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_hf_smoke.sh"


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

    assert syntax_check.returncode == 0
    assert "trap cleanup EXIT" in script
    assert 'kill "$tailscaled_pid"' in script
    assert "export SCRAPER_PROXY_URL=socks5://127.0.0.1:1055" in script
    assert "pytest --run-smoke -m smoke -q" in script
    assert "pytest_status=$?" in script
    assert 'exit "$pytest_status"' in script
