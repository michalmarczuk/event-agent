"""Apply taxonomy markers according to each test file's directory."""

from pathlib import Path

import pytest


_TESTS_ROOT = Path(__file__).parent
_CATEGORIES = {"unit", "behavioral", "integration", "smoke"}


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
