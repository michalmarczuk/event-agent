import html

try:
    from .models import Recommendation
except ImportError:  # pragma: no cover - supports script execution
    from models import Recommendation


_CATEGORY_EMOJIS = {
    "music": "🎵",
    "culture": "🎭",
    "live_performance": "🎤",
    "art": "🎨",
    "local": "🌆",
    "unusual": "✨",
}


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def _format_location(recommendation: Recommendation) -> str | None:
    parts = [part for part in (recommendation.city, recommendation.venue) if part]
    return " · ".join(_escape(part) for part in parts) or None


def _format_datetime(recommendation: Recommendation) -> str | None:
    parts = [part for part in (recommendation.date, recommendation.time) if part]
    return " · ".join(_escape(part) for part in parts) or None


def format_telegram_message(
    recommendations: list[Recommendation],
    base_location_name: str,
    radius_km: int,
    days_ahead: int,
) -> str:
    """Format recommendations as deterministic Telegram HTML."""
    location_name = "Tychów" if base_location_name == "Tychy" else base_location_name
    lines = [
        "🎯 <b>Event Agent</b>",
        f"📍 do {_escape(str(radius_km))} km od {_escape(location_name)} · najbliższe {_escape(str(days_ahead))} dni",
    ]

    for index, recommendation in enumerate(recommendations, start=1):
        emoji = _CATEGORY_EMOJIS.get(recommendation.category, "✨")
        lines.append("")
        lines.append(f"{emoji} <b>{index}. {_escape(recommendation.name)}</b>")

        date_time = _format_datetime(recommendation)
        if date_time:
            lines.append(f"📅 {date_time}")

        location = _format_location(recommendation)
        if location:
            lines.append(f"📍 {location}")

        lines.append(f"💡 {_escape(recommendation.reason)}")

        if recommendation.url:
            lines.append(
                f'🎟 <a href="{_escape(recommendation.url)}">Szczegóły / bilety</a>'
            )

    return "\n".join(lines)
