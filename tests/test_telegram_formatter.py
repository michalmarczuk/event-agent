from src.models import Recommendation
from src.telegram_formatter import format_telegram_message


def recommendation(category="music", **overrides):
    values = {
        "event_id": "event-1",
        "name": "Summer Concert",
        "category": category,
        "date": "2026-09-10",
        "time": "19:00",
        "city": "Tychy",
        "venue": "Town Hall",
        "reason": "A distinctive local show.",
        "url": "https://example.test/event?x=1&y=2",
    }
    values.update(overrides)
    return Recommendation(**values)


def test_format_telegram_message_with_complete_data():
    message = format_telegram_message([recommendation()], "Tychy", 50, 30)

    assert "🎯 <b>Event Agent</b>" in message
    assert "📍 do 50 km od Tychów · najbliższe 30 dni" in message
    assert "🎵 <b>1. Summer Concert</b>" in message
    assert "📅 2026-09-10 · 19:00" in message
    assert "📍 Tychy · Town Hall" in message
    assert "💡 A distinctive local show." in message
    assert 'href="https://example.test/event?x=1&amp;y=2"' in message


def test_format_telegram_message_omits_missing_optional_fields():
    message = format_telegram_message(
        [recommendation(date=None, time=None, city=None, venue=None, url=None)],
        "Tychy",
        50,
        30,
    )

    assert "📅" not in message
    assert "📍 Tychy ·" not in message
    assert "🎟" not in message
    assert "💡 A distinctive local show." in message


def test_format_telegram_message_escapes_external_text():
    message = format_telegram_message(
        [
            recommendation(
                name="Rock <Night> & Friends",
                reason='Use "the link" & enjoy <music>.',
                city="A&B",
                venue="Hall <1>",
                url="https://example.test/?a=1&b=2",
            )
        ],
        "Tychy & nearby",
        50,
        30,
    )

    assert "Rock &lt;Night&gt; &amp; Friends" in message
    assert "Use &quot;the link&quot; &amp; enjoy &lt;music&gt;." in message
    assert "A&amp;B · Hall &lt;1&gt;" in message
    assert "Tychy &amp; nearby" in message


def test_format_telegram_message_maps_categories_to_emojis():
    expected = {
        "music": "🎵",
        "culture": "🎭",
        "live_performance": "🎤",
        "art": "🎨",
        "local": "🌆",
        "unusual": "✨",
    }

    for category, emoji in expected.items():
        assert f"{emoji} <b>1. Summer Concert</b>" in format_telegram_message(
            [recommendation(category)], "Tychy", 50, 30
        )
