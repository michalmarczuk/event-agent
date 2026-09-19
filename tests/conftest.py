"""Apply taxonomy markers according to each test file's directory."""

import os
from pathlib import Path

import pytest


_TESTS_ROOT = Path(__file__).parent
_CATEGORIES = {"unit", "behavioral", "integration", "smoke"}
_QASE_REPORTING_MODE = "testops"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the explicit opt-in required for live smoke tests."""
    parser.addoption(
        "--run-smoke",
        action="store_true",
        default=False,
        help="run live external-service smoke tests",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Mark tests in category directories without changing their modules."""
    for item in items:
        if not item.path.is_relative_to(_TESTS_ROOT):
            continue
        category = item.path.relative_to(_TESTS_ROOT).parts[0]
        if category in _CATEGORIES:
            item.add_marker(getattr(pytest.mark, category))

    if config.getoption("--run-smoke"):
        return

    skip_smoke = pytest.mark.skip(reason="requires --run-smoke")
    for item in items:
        if item.get_closest_marker("smoke") is not None:
            item.add_marker(skip_smoke)


def pytest_collection_finish(session: pytest.Session) -> None:
    """Reject unlinked selected tests before a Qase reporting run executes."""
    if os.environ.get("QASE_MODE", "").casefold() != _QASE_REPORTING_MODE:
        return

    unlinked_node_ids = [
        item.nodeid
        for item in session.items
        if item.get_closest_marker("qase") is None
    ]
    if not unlinked_node_ids:
        return

    preview = ", ".join(unlinked_node_ids[:3])
    remainder = len(unlinked_node_ids) - 3
    if remainder > 0:
        preview = f"{preview}, and {remainder} more"
    raise pytest.UsageError(
        "Qase reporting safety guard rejected "
        f"{len(unlinked_node_ids)} selected test(s) without the qase marker: "
        f"{preview}. Select only linked tests with a qase marker expression."
    )
