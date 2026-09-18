"""Apply taxonomy markers according to each test file's directory."""

from pathlib import Path

import pytest


_TESTS_ROOT = Path(__file__).parent
_CATEGORIES = {"unit", "behavioral", "integration", "smoke"}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark tests in category directories without changing their modules."""
    for item in items:
        if not item.path.is_relative_to(_TESTS_ROOT):
            continue
        category = item.path.relative_to(_TESTS_ROOT).parts[0]
        if category in _CATEGORIES:
            item.add_marker(getattr(pytest.mark, category))
