import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from src.sources.mosir_tychy import MosirTychySource, _parse_event_details

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "mosir_tychy"


class _Response:
    def __init__(self, *, json_payload=None, text="", error=None):
        self._json_payload = json_payload
        self.text = text
        self._error = error

    def json(self):
        if isinstance(self._json_payload, Exception):
            raise self._json_payload
        return self._json_payload

    def raise_for_status(self):
        if self._error is not None:
            raise self._error


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _source() -> MosirTychySource:
    return MosirTychySource(
        "https://mosir.example",
        today_provider=lambda: date(2026, 9, 10),
    )


def _happy_get(url, *, params=None, timeout):
    assert timeout == 10
    if url.endswith("/item/calendar"):
        assert params == {"year": 2026, "month": 9}
        return _Response(json_payload=json.loads(_fixture("calendar_2026_09.json")))
    if url.endswith("/wydarzenia"):
        assert params == {"date": "2026-09-10"}
        return _Response(text=_fixture("events_2026_09_10.html"))
    if url.endswith("/1836-mosir-concert"):
        assert params is None
        return _Response(text=_fixture("event_1836.html"))
    raise AssertionError(f"Unexpected URL: {url}")


def test_tychy_search_normalizes_server_rendered_event(caplog):
    with patch("src.sources.mosir_tychy.requests.get", side_effect=_happy_get) as get:
        events = _source().search_events("Tychy", 0)

    assert len(events) == 1
    event = events[0]
    assert event.id == "mosir_tychy:1836"
    assert event.source == "mosir_tychy"
    assert event.source_event_id == "1836"
    assert event.name == "MOSiR Concert"
    assert event.date == "2026-09-10"
    assert event.city == "Tychy"
    assert event.venue == "Stadion Zimowy"
    assert event.url == "https://mosir.tychy.pl/1836-mosir-concert"
    assert event.admission is None
    assert get.call_count == 3
    assert "skipped malformed calendar date" in caplog.text
    assert "skipped malformed event card" in caplog.text


def test_detail_parser_handles_split_venue_label():
    canonical_url, venue = _parse_event_details(
        _fixture("event_1836_split_label.html"),
        "https://mosir.example/requested",
    )

    assert canonical_url == "https://mosir.tychy.pl/1836-mosir-concert"
    assert venue == "Stadion Zimowy"


@pytest.mark.parametrize("city", ["Katowice", "Gliwice"])
def test_non_tychy_search_returns_empty_without_http(city):
    with patch("src.sources.mosir_tychy.requests.get") as get:
        events = _source().search_events(city, 30)

    assert events == []
    get.assert_not_called()


def test_date_window_filters_marked_dates_before_fetching_event_pages():
    with patch("src.sources.mosir_tychy.requests.get", side_effect=_happy_get) as get:
        _source().search_events("Tychy", 0)

    assert [call.args[0] for call in get.call_args_list] == [
        "https://mosir.example/item/calendar",
        "https://mosir.example/wydarzenia",
        "https://mosir.example/1836-mosir-concert",
    ]


def test_valid_empty_events_page_is_successful_empty_result():
    def get(url, *, params=None, timeout):
        if url.endswith("/item/calendar"):
            return _Response(json_payload=[{"date": "2026-09-10"}])
        assert url.endswith("/wydarzenia")
        return _Response(text=_fixture("empty_events.html"))

    with patch("src.sources.mosir_tychy.requests.get", side_effect=get):
        assert _source().search_events("Tychy", 0) == []


def test_unrecognized_events_layout_is_source_failure():
    def get(url, *, params=None, timeout):
        if url.endswith("/item/calendar"):
            return _Response(json_payload=[{"date": "2026-09-10"}])
        return _Response(text="<main>Unexpected layout</main>")

    with (
        patch("src.sources.mosir_tychy.requests.get", side_effect=get),
        pytest.raises(RuntimeError, match="layout was not recognized"),
    ):
        _source().search_events("Tychy", 0)


def test_http_failure_is_source_failure_without_response_details():
    response = requests.Response()
    response.status_code = 503

    with (
        patch(
            "src.sources.mosir_tychy.requests.get",
            return_value=_Response(error=requests.HTTPError(response=response)),
        ),
        pytest.raises(RuntimeError, match=r"MOSiR Tychy request failed \(HTTP 503\)"),
    ):
        _source().search_events("Tychy", 0)


def test_timeout_is_source_failure():
    with (
        patch(
            "src.sources.mosir_tychy.requests.get",
            side_effect=requests.Timeout(),
        ),
        pytest.raises(RuntimeError, match=r"MOSiR Tychy request failed \(Timeout\)"),
    ):
        _source().search_events("Tychy", 0)


def test_invalid_calendar_payload_is_source_failure():
    with (
        patch(
            "src.sources.mosir_tychy.requests.get",
            return_value=_Response(json_payload={"date": "2026-09-10"}),
        ),
        pytest.raises(RuntimeError, match="calendar returned an invalid payload"),
    ):
        _source().search_events("Tychy", 0)


def test_invalid_calendar_json_is_source_failure():
    with (
        patch(
            "src.sources.mosir_tychy.requests.get",
            return_value=_Response(json_payload=ValueError("invalid JSON")),
        ),
        pytest.raises(RuntimeError, match="returned invalid JSON"),
    ):
        _source().search_events("Tychy", 0)


def test_source_uses_warsaw_date_when_no_date_provider_is_supplied():
    assert isinstance(MosirTychySource()._current_local_date(), date)
