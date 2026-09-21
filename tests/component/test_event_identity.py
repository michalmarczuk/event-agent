import pytest

from src.event_identity import build_event_id, parse_event_id


def test_ticketmaster_event_identity_preserves_provider_id():
    event_id = build_event_id("ticketmaster", "abc123")

    assert event_id == "ticketmaster:abc123"
    assert parse_event_id(event_id) == ("ticketmaster", "abc123")


def test_parse_event_id_preserves_colons_in_provider_id():
    assert parse_event_id("source:provider:id") == ("source", "provider:id")


@pytest.mark.parametrize(
    ("source", "source_event_id"),
    [
        ("", "abc123"),
        ("ticket:master", "abc123"),
        ("ticketmaster", ""),
    ],
)
def test_build_event_id_rejects_invalid_identity_parts(source, source_event_id):
    with pytest.raises(ValueError):
        build_event_id(source, source_event_id)


@pytest.mark.parametrize("event_id", ["", "ticketmaster", ":abc123", "ticketmaster:"])
def test_parse_event_id_rejects_malformed_global_ids(event_id):
    with pytest.raises(ValueError, match="Event ID"):
        parse_event_id(event_id)
