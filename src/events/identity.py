"""Deterministic identifiers for normalized provider events."""


def build_event_id(source: str, source_event_id: str) -> str:
    """Build the global event identifier for one provider event."""
    if not source or ":" in source:
        raise ValueError("Event source must be a non-empty namespace")
    if not source_event_id:
        raise ValueError("Source event ID must be non-empty")
    return f"{source}:{source_event_id}"


def parse_event_id(event_id: str) -> tuple[str, str]:
    """Return the source namespace and provider-native ID from a global ID."""
    source, separator, source_event_id = event_id.partition(":")
    if not separator or not source or not source_event_id:
        raise ValueError("Event ID must use the '<source>:<source_event_id>' format")
    return source, source_event_id
