import logging
from types import SimpleNamespace

import pytest

import src.app.daily as daily
from src.config import SearchLocation, Settings


def _patch_daily_dependencies(
    monkeypatch,
    *,
    agent,
    history,
    telegram,
    config,
    formatter,
    enrichment,
    logging_config,
):
    monkeypatch.setattr(daily, "run_agent", agent.run_agent)
    monkeypatch.setattr(daily, "load_seen_event_ids", history.load_seen_event_ids)
    monkeypatch.setattr(daily, "save_seen_event_ids", history.save_seen_event_ids)
    monkeypatch.setattr(daily, "send_telegram_message", telegram.send_telegram_message)
    monkeypatch.setattr(daily, "load_settings", config.load_settings)
    monkeypatch.setattr(daily, "format_telegram_message", formatter.format_telegram_message)
    monkeypatch.setattr(
        daily,
        "enrich_ticketmaster_prices",
        enrichment.enrich_ticketmaster_prices,
    )
    monkeypatch.setattr(daily, "configure_logging", logging_config.configure_logging)
    monkeypatch.setattr(daily, "shutdown_logging", logging_config.shutdown_logging)


def test_daily_runs_pipeline_and_saves_history_only_after_telegram_succeeds(
    monkeypatch, caplog,
):
    seen_ids = {"ticketmaster:seen"}
    recommendations = [
        SimpleNamespace(event_id="ticketmaster:new", admission=None)
    ]
    operations = []

    def run_agent(prompt, seen_event_ids):
        operations.append(("agent", prompt, seen_event_ids))
        return SimpleNamespace(
            recommendations=recommendations,
            recommended_event_ids={"ticketmaster:new"},
            discovery_failed=False,
        )

    def enrich_ticketmaster_prices(agent_recommendations):
        assert agent_recommendations is recommendations
        agent_recommendations[0].admission = "enriched"
        operations.append(("enrichment", agent_recommendations))

    def format_telegram_message(
        formatted_recommendations,
        base_location_name,
        radius_km,
        days_ahead,
    ):
        assert formatted_recommendations is recommendations
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
        assert not any(
            record.__dict__.get("event.action") == "daily_run"
            for record in caplog.records
        )
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
    fake_logging_config = SimpleNamespace(
        configure_logging=lambda: operations.append(("logging",)),
        shutdown_logging=lambda: operations.append(("logging_shutdown",)),
    )

    _patch_daily_dependencies(
        monkeypatch,
        agent=fake_agent,
        history=fake_history,
        telegram=fake_telegram,
        config=fake_config,
        formatter=fake_formatter,
        enrichment=fake_enrichment,
        logging_config=fake_logging_config,
    )

    with caplog.at_level(logging.INFO):
        daily.main()

    assert operations == [
        ("logging",),
        (
            "agent",
            "Znajdź najciekawsze wydarzenia dla mnie na najbliższe 30 dni.",
            seen_ids,
        ),
        ("enrichment", recommendations),
        ("formatter", "enriched", "Tychy", 50, 30),
        ("telegram", "formatted report"),
        ("persistence", {"ticketmaster:seen", "ticketmaster:new"}),
        ("logging_shutdown",),
    ]
    summaries = [
        record
        for record in caplog.records
        if record.__dict__.get("event.action") == "daily_run"
    ]
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.levelno == logging.INFO
    assert summary.__dict__["event.outcome"] == "success"
    assert isinstance(summary.__dict__["run.duration_ms"], int)
    assert summary.__dict__["run.duration_ms"] >= 0
    assert summary.__dict__["events.seen_loaded"] == 1
    assert summary.__dict__["events.recommended"] == 1
    assert summary.__dict__["events.seen_saved"] == 2


def test_daily_no_recommendations_sends_info_message_and_preserves_history(
    monkeypatch,
):
    operations = []
    seen_ids = {"already-seen"}

    fake_agent = SimpleNamespace(
        run_agent=lambda prompt, seen_event_ids: SimpleNamespace(
            recommendations=[],
            recommended_event_ids=set(),
            discovery_failed=False,
        )
    )
    fake_history = SimpleNamespace(
        load_seen_event_ids=lambda: seen_ids,
        save_seen_event_ids=lambda event_ids: operations.append(
            ("persistence", event_ids)
        ),
    )
    fake_telegram = SimpleNamespace(
        send_telegram_message=lambda message: operations.append(("telegram", message))
    )
    fake_config = SimpleNamespace(
        load_settings=lambda: SimpleNamespace(
            search_location=SimpleNamespace(name="Tychy", radius_km=50)
        )
    )
    fake_formatter = SimpleNamespace(
        format_telegram_message=lambda recommendations, base_location_name, radius_km, days_ahead: (
            operations.append(("formatter", recommendations))
            or "Brak nowych wydarzeń."
        )
    )
    fake_enrichment = SimpleNamespace(
        enrich_ticketmaster_prices=lambda recommendations: recommendations,
    )
    fake_logging_config = SimpleNamespace(
        configure_logging=lambda: None,
        shutdown_logging=lambda: None,
    )

    _patch_daily_dependencies(
        monkeypatch,
        agent=fake_agent,
        history=fake_history,
        telegram=fake_telegram,
        config=fake_config,
        formatter=fake_formatter,
        enrichment=fake_enrichment,
        logging_config=fake_logging_config,
    )

    daily.main()

    assert operations == [
        ("formatter", []),
        ("telegram", "Brak nowych wydarzeń."),
        ("persistence", seen_ids),
    ]


def test_daily_aborts_without_delivery_or_persistence_when_discovery_failed(
    monkeypatch,
    caplog,
    capsys,
):
    operations = []
    seen_ids = {"already-seen"}

    fake_agent = SimpleNamespace(
        run_agent=lambda prompt, seen_event_ids: (
            operations.append(("agent", seen_event_ids))
            or SimpleNamespace(
                recommendations=[],
                recommended_event_ids=set(),
                discovery_failed=True,
            )
        )
    )
    fake_history = SimpleNamespace(
        load_seen_event_ids=lambda: seen_ids,
        save_seen_event_ids=lambda event_ids: operations.append(
            ("persistence", event_ids)
        ),
    )
    fake_telegram = SimpleNamespace(
        send_telegram_message=lambda message: operations.append(("telegram", message))
    )
    fake_enrichment = SimpleNamespace(
        enrich_ticketmaster_prices=lambda recommendations: operations.append(
            ("enrichment", recommendations)
        ),
    )
    fake_formatter = SimpleNamespace(
        format_telegram_message=lambda *args: operations.append(("formatter", args))
    )
    fake_config = SimpleNamespace(load_settings=lambda: None)
    fake_logging_config = SimpleNamespace(
        configure_logging=lambda: None,
        shutdown_logging=lambda: operations.append(("logging_shutdown",)),
    )

    _patch_daily_dependencies(
        monkeypatch,
        agent=fake_agent,
        history=fake_history,
        telegram=fake_telegram,
        config=fake_config,
        formatter=fake_formatter,
        enrichment=fake_enrichment,
        logging_config=fake_logging_config,
    )

    with caplog.at_level(logging.INFO), pytest.raises(
        RuntimeError, match="Event discovery failed"
    ):
        daily.main()

    assert operations == [
        ("agent", seen_ids),
        ("logging_shutdown",),
    ]
    assert capsys.readouterr().out == ""
    assert any(
        record.message
        == "Event discovery failed; skipping delivery and history persistence"
        for record in caplog.records
    )
    assert not any(
        record.__dict__.get("event.action") == "daily_run"
        for record in caplog.records
    )


def test_daily_does_not_save_history_when_telegram_fails(monkeypatch, caplog):
    saved_ids = []
    logging_shutdowns = []
    fake_agent = SimpleNamespace(
        run_agent=lambda prompt, seen_event_ids: SimpleNamespace(
            recommendations=[],
            recommended_event_ids={"new"},
            discovery_failed=False,
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
    fake_enrichment = SimpleNamespace(
        enrich_ticketmaster_prices=lambda recommendations: recommendations,
    )
    fake_logging_config = SimpleNamespace(
        configure_logging=lambda: None,
        shutdown_logging=lambda: logging_shutdowns.append(True),
    )

    _patch_daily_dependencies(
        monkeypatch,
        agent=fake_agent,
        history=fake_history,
        telegram=fake_telegram,
        config=fake_config,
        formatter=fake_formatter,
        enrichment=fake_enrichment,
        logging_config=fake_logging_config,
    )

    with caplog.at_level(logging.INFO), pytest.raises(
        RuntimeError, match="Telegram unavailable"
    ):
        daily.main()

    assert saved_ids == []
    assert logging_shutdowns == [True]
    assert not any(
        record.__dict__.get("event.action") == "daily_run"
        for record in caplog.records
    )


def test_daily_does_not_report_success_when_history_save_fails(monkeypatch, caplog):
    operations = []

    def save_seen_event_ids(event_ids):
        operations.append(("persistence", event_ids))
        raise RuntimeError("History unavailable")

    fake_agent = SimpleNamespace(
        run_agent=lambda prompt, seen_event_ids: SimpleNamespace(
            recommendations=[],
            recommended_event_ids={"new"},
            discovery_failed=False,
        )
    )
    fake_history = SimpleNamespace(
        load_seen_event_ids=lambda: {"seen"},
        save_seen_event_ids=save_seen_event_ids,
    )
    fake_telegram = SimpleNamespace(
        send_telegram_message=lambda message: operations.append(("telegram", message))
    )
    fake_config = SimpleNamespace(
        load_settings=lambda: SimpleNamespace(
            search_location=SimpleNamespace(name="Tychy", radius_km=50)
        )
    )
    fake_formatter = SimpleNamespace(
        format_telegram_message=lambda recommendations, base_location_name, radius_km, days_ahead: "formatted report"
    )
    fake_enrichment = SimpleNamespace(
        enrich_ticketmaster_prices=lambda recommendations: recommendations,
    )
    fake_logging_config = SimpleNamespace(
        configure_logging=lambda: None,
        shutdown_logging=lambda: operations.append(("logging_shutdown",)),
    )

    _patch_daily_dependencies(
        monkeypatch,
        agent=fake_agent,
        history=fake_history,
        telegram=fake_telegram,
        config=fake_config,
        formatter=fake_formatter,
        enrichment=fake_enrichment,
        logging_config=fake_logging_config,
    )

    with caplog.at_level(logging.INFO), pytest.raises(
        RuntimeError, match="History unavailable"
    ):
        daily.main()

    assert operations == [
        ("telegram", "formatted report"),
        ("persistence", {"seen", "new"}),
        ("logging_shutdown",),
    ]
    assert not any(
        record.__dict__.get("event.action") == "daily_run"
        for record in caplog.records
    )


def test_daily_summary_logging_failure_does_not_fail_delivery(monkeypatch):
    operations = []

    def log_info(message, *args, **kwargs):
        if kwargs.get("extra", {}).get("event.action") == "daily_run":
            operations.append(("summary_logging_failed",))
            raise RuntimeError("Log sink unavailable")

    fake_agent = SimpleNamespace(
        run_agent=lambda prompt, seen_event_ids: SimpleNamespace(
            recommendations=[],
            recommended_event_ids={"new"},
            discovery_failed=False,
        )
    )
    fake_history = SimpleNamespace(
        load_seen_event_ids=lambda: {"seen"},
        save_seen_event_ids=lambda event_ids: operations.append(
            ("persistence", event_ids)
        ),
    )
    fake_telegram = SimpleNamespace(
        send_telegram_message=lambda message: operations.append(("telegram", message))
    )
    fake_config = SimpleNamespace(
        load_settings=lambda: SimpleNamespace(
            search_location=SimpleNamespace(name="Tychy", radius_km=50)
        )
    )
    fake_formatter = SimpleNamespace(
        format_telegram_message=lambda recommendations, base_location_name, radius_km, days_ahead: "formatted report"
    )
    fake_enrichment = SimpleNamespace(
        enrich_ticketmaster_prices=lambda recommendations: recommendations,
    )
    fake_logging_config = SimpleNamespace(
        configure_logging=lambda: None,
        shutdown_logging=lambda: operations.append(("logging_shutdown",)),
    )

    _patch_daily_dependencies(
        monkeypatch,
        agent=fake_agent,
        history=fake_history,
        telegram=fake_telegram,
        config=fake_config,
        formatter=fake_formatter,
        enrichment=fake_enrichment,
        logging_config=fake_logging_config,
    )

    with monkeypatch.context() as logger_patch:
        logger_patch.setattr(
            daily,
            "logger",
            SimpleNamespace(info=log_info),
        )
        daily.main()

    assert operations == [
        ("telegram", "formatted report"),
        ("persistence", {"seen", "new"}),
        ("summary_logging_failed",),
        ("logging_shutdown",),
    ]


def test_daily_persists_only_recommended_event_ids(monkeypatch):
    saved_ids = []
    recommendations = [
        SimpleNamespace(event_id="ticketmaster:event-1", url=None),
        SimpleNamespace(event_id="ticketmaster:event-2", url=None),
    ]
    fake_agent = SimpleNamespace(
        run_agent=lambda prompt, seen_event_ids: SimpleNamespace(
            recommendations=recommendations,
            recommended_event_ids={
                "ticketmaster:event-1", "ticketmaster:event-2"
            },
            discovery_failed=False,
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
    fake_enrichment = SimpleNamespace(
        enrich_ticketmaster_prices=lambda agent_recommendations: agent_recommendations,
    )
    fake_logging_config = SimpleNamespace(
        configure_logging=lambda: None,
        shutdown_logging=lambda: None,
    )

    _patch_daily_dependencies(
        monkeypatch,
        agent=fake_agent,
        history=fake_history,
        telegram=fake_telegram,
        config=fake_config,
        formatter=fake_formatter,
        enrichment=fake_enrichment,
        logging_config=fake_logging_config,
    )

    daily.main()

    assert saved_ids == [{"ticketmaster:event-1", "ticketmaster:event-2"}]
