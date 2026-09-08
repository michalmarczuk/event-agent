import runpy
import sys
from pathlib import Path
from types import SimpleNamespace


def test_daily_saves_history_only_after_telegram_succeeds(monkeypatch):
    seen_ids = {"seen"}
    saved_ids = []
    telegram_checks = []
    prompts = []

    fake_agent = SimpleNamespace(
        run_agent=lambda prompt, seen_event_ids: (
            prompts.append(prompt)
            or SimpleNamespace(
                text="Found new events",
                discovered_event_ids={"new"},
            )
        ),
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

    project_root = Path(__file__).resolve().parents[1]
    runpy.run_path(project_root / "src" / "daily.py", run_name="__main__")

    assert telegram_checks == [("Found new events", [])]
    assert saved_ids == [{"seen", "new"}]
    assert prompts == [
        "Znajdź najciekawsze wydarzenia dla mnie na najbliższe 30 dni."
    ]