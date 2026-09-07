import runpy
import sys
from types import SimpleNamespace


def test_daily_saves_history_only_after_telegram_succeeds(monkeypatch):
    seen_ids = {"seen"}
    saved_ids = []
    telegram_checks = []

    fake_agent = SimpleNamespace(
        run_agent=lambda prompt, seen_event_ids: SimpleNamespace(
            text="Found new events",
            discovered_event_ids={"new"},
        )
    )

    def send_telegram_message(message):
        telegram_checks.append((message, list(saved_ids)))

    fake_history = SimpleNamespace(
        load_seen_event_ids=lambda: seen_ids,
        save_seen_event_ids=lambda event_ids: saved_ids.append(event_ids),
    )
    fake_telegram = SimpleNamespace(send_telegram_message=send_telegram_message)

    monkeypatch.setitem(sys.modules, "agent", fake_agent)
    monkeypatch.setitem(sys.modules, "history", fake_history)
    monkeypatch.setitem(sys.modules, "telegram_notifier", fake_telegram)

    runpy.run_path(
        "/Users/mmarczuk/Data/workspace/event-agent/src/daily.py",
        run_name="__main__",
    )

    assert telegram_checks == [("Found new events", [])]
    assert saved_ids == [{"seen", "new"}]