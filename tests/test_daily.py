import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

from src.config import SearchLocation, Settings


def test_daily_runs_pipeline_and_saves_history_only_after_telegram_succeeds(
    monkeypatch,
):
    seen_ids = {"seen"}
    recommendations = [SimpleNamespace(event_id="new", admission=None)]
    priced_recommendations = [
        SimpleNamespace(event_id="new", admission="enriched")
    ]
    operations = []

    def run_agent(prompt, seen_event_ids):
        operations.append(("agent", prompt, seen_event_ids))
        return SimpleNamespace(
            recommendations=recommendations,
            recommended_event_ids={"new"},
        )

    def enrich_ticketmaster_prices(agent_recommendations):
        assert agent_recommendations is recommendations
        operations.append(("enrichment", agent_recommendations))
        return priced_recommendations

    def format_telegram_message(
        formatted_recommendations,
        base_location_name,
        radius_km,
        days_ahead,
    ):
        assert formatted_recommendations is priced_recommendations
        operations.append(
            (
                "formatter",
                formatted_recommendations[0].admission,
                base_location_name,
                radius_km,
                days_ahead,
            )
        )
        return "formatted report"

    def send_telegram_message(message):
        operations.append(("telegram", message))

    def save_seen_event_ids(event_ids):
        operations.append(("persistence", event_ids))

    fake_agent = SimpleNamespace(
        run_agent=run_agent,
    )
    fake_history = SimpleNamespace(
        load_seen_event_ids=lambda: seen_ids,
        save_seen_event_ids=save_seen_event_ids,
    )
    fake_telegram = SimpleNamespace(send_telegram_message=send_telegram_message)
    fake_enrichment = SimpleNamespace(
        enrich_ticketmaster_prices=enrich_ticketmaster_prices,
    )
    fake_config = SimpleNamespace(
        load_settings=lambda: Settings(
            openai_api_key="openai-test-key",
            ticketmaster_api_key="ticketmaster-test-key",
            telegram_bot_token="telegram-test-token",
            telegram_chat_id="telegram-test-chat",
            model="test-model",
            search_location=SearchLocation("Tychy", "u2y0test", 50),
        )
    )
    fake_formatter = SimpleNamespace(
        format_telegram_message=format_telegram_message,
    )

    monkeypatch.setitem(sys.modules, "agent", fake_agent)
    monkeypatch.setitem(sys.modules, "history", fake_history)
    monkeypatch.setitem(sys.modules, "telegram_notifier", fake_telegram)
    monkeypatch.setitem(sys.modules, "config", fake_config)
    monkeypatch.setitem(sys.modules, "telegram_formatter", fake_formatter)
    monkeypatch.setitem(sys.modules, "ticketmaster_enrichment", fake_enrichment)

    project_root = Path(__file__).resolve().parents[1]
    runpy.run_path(project_root / "src" / "daily.py", run_name="__main__")

    assert operations == [
        (
            "agent",
            "Znajdź najciekawsze wydarzenia dla mnie na najbliższe 30 dni.",
            seen_ids,
        ),
        ("enrichment", recommendations),
        ("formatter", "enriched", "Tychy", 50, 30),
        ("telegram", "formatted report"),
        ("persistence", {"seen", "new"}),
    ]


def test_daily_does_not_save_history_when_telegram_fails(monkeypatch):
    saved_ids = []
    fake_agent = SimpleNamespace(
        run_agent=lambda prompt, seen_event_ids: SimpleNamespace(
            recommendations=[],
            recommended_event_ids={"new"},
        )
    )
    fake_history = SimpleNamespace(
        load_seen_event_ids=lambda: set(),
        save_seen_event_ids=lambda event_ids: saved_ids.append(event_ids),
    )
    fake_telegram = SimpleNamespace(
        send_telegram_message=lambda message: (_ for _ in ()).throw(
            RuntimeError("Telegram unavailable")
        )
    )
    fake_config = SimpleNamespace(
        load_settings=lambda: SimpleNamespace(
            search_location=SimpleNamespace(name="Tychy", radius_km=50)
        )
    )
    fake_formatter = SimpleNamespace(
        format_telegram_message=lambda recommendations, base_location_name, radius_km, days_ahead: "formatted report"
    )

    monkeypatch.setitem(sys.modules, "agent", fake_agent)
    monkeypatch.setitem(sys.modules, "history", fake_history)
    monkeypatch.setitem(sys.modules, "telegram_notifier", fake_telegram)
    monkeypatch.setitem(sys.modules, "config", fake_config)
    monkeypatch.setitem(sys.modules, "telegram_formatter", fake_formatter)

    project_root = Path(__file__).resolve().parents[1]
    try:
        runpy.run_path(project_root / "src" / "daily.py", run_name="__main__")
    except RuntimeError as error:
        assert str(error) == "Telegram unavailable"
    else:
        raise AssertionError("Telegram failure should propagate")

    assert saved_ids == []


def test_daily_persists_only_recommended_event_ids(monkeypatch):
    saved_ids = []
    recommendations = [
        SimpleNamespace(event_id="event-1", url=None),
        SimpleNamespace(event_id="event-2", url=None),
    ]
    fake_agent = SimpleNamespace(
        run_agent=lambda prompt, seen_event_ids: SimpleNamespace(
            recommendations=recommendations,
            recommended_event_ids={"event-1", "event-2"},
        )
    )
    fake_history = SimpleNamespace(
        load_seen_event_ids=lambda: set(),
        save_seen_event_ids=lambda event_ids: saved_ids.append(event_ids),
    )
    fake_telegram = SimpleNamespace(send_telegram_message=lambda message: None)
    fake_config = SimpleNamespace(
        load_settings=lambda: SimpleNamespace(
            search_location=SimpleNamespace(name="Tychy", radius_km=50)
        )
    )
    fake_formatter = SimpleNamespace(
        format_telegram_message=lambda recommendations, base_location_name, radius_km, days_ahead: "formatted report"
    )

    monkeypatch.setitem(sys.modules, "agent", fake_agent)
    monkeypatch.setitem(sys.modules, "history", fake_history)
    monkeypatch.setitem(sys.modules, "telegram_notifier", fake_telegram)
    monkeypatch.setitem(sys.modules, "config", fake_config)
    monkeypatch.setitem(sys.modules, "telegram_formatter", fake_formatter)

    project_root = Path(__file__).resolve().parents[1]
    runpy.run_path(project_root / "src" / "daily.py", run_name="__main__")

    assert saved_ids == [{"event-1", "event-2"}]
