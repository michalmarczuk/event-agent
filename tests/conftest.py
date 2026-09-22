"""Configure opt-in live tests and safe Qase selections."""

import os

import pytest

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
    """Keep live checks opt-in while leaving level classification to paths."""
    if config.getoption("--run-smoke"):
        return

    skip_smoke = pytest.mark.skip(reason="requires --run-smoke")
    for item in items:
        if (
            item.get_closest_marker("smoke") is not None
            or item.get_closest_marker("live") is not None
        ):
            item.add_marker(skip_smoke)


def pytest_collection_finish(session: pytest.Session) -> None:
    """Reject unlinked selected tests before a Qase reporting run executes."""
    if os.environ.get("QASE_MODE", "").casefold() != _QASE_REPORTING_MODE:
        return

    def has_qase_id(item: pytest.Item) -> bool:
        return item.get_closest_marker("qase_id") is not None

    unlinked_node_ids = [item.nodeid for item in session.items if not has_qase_id(item)]
    if not unlinked_node_ids:
        return

    preview = ", ".join(unlinked_node_ids[:3])
    remainder = len(unlinked_node_ids) - 3
    if remainder > 0:
        preview = f"{preview}, and {remainder} more"
    raise pytest.UsageError(
        "Qase reporting safety guard rejected "
        f"{len(unlinked_node_ids)} selected test(s) without @qase.id(...): "
        f"{preview}. Select only tests linked to Qase."
    )
