from scripts import run_mosir_live_smoke as smoke
from src.events.models import Event


class _Source:
    def __init__(self, result):
        self._result = result
        self.calls = []

    def search_events(self, city, days_ahead):
        self.calls.append((city, days_ahead))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def test_runner_treats_a_healthy_empty_window_as_success(monkeypatch, capsys):
    source = _Source([])
    monkeypatch.setattr(smoke, "MosirTychySource", lambda: source)

    assert smoke.main() == 0
    assert source.calls == [("Tychy", 30)]
    assert capsys.readouterr().out == "MOSIR_LIVE_SMOKE_OK events=0\n"


def test_runner_accepts_normalized_mosir_events(monkeypatch, capsys):
    source = _Source(
        [
            Event(
                id="mosir_tychy:123",
                name="Live event",
                date="2030-01-01",
                city="Tychy",
                venue="MOSiR Hall",
                url="https://mosir.tychy.pl/wydarzenia/123-live-event",
                source="mosir_tychy",
                source_event_id="123",
                admission=None,
            )
        ]
    )
    monkeypatch.setattr(smoke, "MosirTychySource", lambda: source)

    assert smoke.main() == 0
    assert capsys.readouterr().out == "MOSIR_LIVE_SMOKE_OK events=1\n"


def test_runner_reports_safe_failure_for_invalid_or_failed_discovery(
    monkeypatch, capsys
):
    source = _Source(
        [
            Event(
                id="unexpected:123",
                name="Invalid event",
                date=None,
                city="Tychy",
                venue=None,
                url="https://mosir.tychy.pl/wydarzenia/123",
                source="mosir_tychy",
                source_event_id="123",
                admission=None,
            )
        ]
    )
    monkeypatch.setattr(smoke, "MosirTychySource", lambda: source)

    assert smoke.main() == 1
    assert capsys.readouterr().err == (
        "MOSIR_LIVE_SMOKE_FAILED reason=invalid_event_contract\n"
    )
