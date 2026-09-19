import pytest
from qase.pytest import qase

from src.models import Admission
from src.ticketmaster_enrichment import enrich_ticketmaster_prices
from tests.support.ticketmaster_enrichment_helpers import FakeScraper, recommendation


@qase.id(7)
@pytest.mark.qase
def test_enrichment_scrapes_only_final_ticketmaster_recommendations():
    FakeScraper.instances = []
    selected = recommendation("selected", "https://www.ticketmaster.pl/event/1")
    non_ticketmaster = recommendation("other", "https://example.test/event/2")

    enrich_ticketmaster_prices([selected, non_ticketmaster], FakeScraper)

    assert FakeScraper.instances[0].scraped_urls == [selected.url]


def test_enrichment_reuses_one_scraper_for_multiple_recommendations():
    FakeScraper.instances = []
    first = recommendation("first", "https://www.ticketmaster.pl/event/1")
    second = recommendation("second", "https://ticketmaster.pl/event/2")
    FakeScraper.prices = {
        first.url: Admission(False, 37.10, 63.60, "PLN"),
        second.url: Admission(False, 49, 49, "PLN"),
    }

    enrich_ticketmaster_prices([first, second], FakeScraper)

    assert len(FakeScraper.instances) == 1
    assert first.admission == FakeScraper.prices[first.url]
    assert second.admission == FakeScraper.prices[second.url]


@qase.id(8)
@pytest.mark.qase
def test_enrichment_replaces_existing_admission_after_successful_scrape():
    existing = Admission(False, 100, 100, "PLN")
    scraped = Admission(False, 150, 150, "PLN")
    selected = recommendation(
        "event", "https://www.ticketmaster.pl/event/1", existing
    )
    FakeScraper.prices = {selected.url: scraped}

    enrich_ticketmaster_prices([selected], FakeScraper)

    assert selected.admission == scraped
    assert selected.admission != existing


def test_enrichment_keeps_existing_admission_when_scrape_returns_none():
    existing = Admission(False, 20, 20, "PLN")
    recommendation_to_update = recommendation(
        "event", "https://www.ticketmaster.pl/event/1", existing
    )
    FakeScraper.prices = {recommendation_to_update.url: None}

    result = enrich_ticketmaster_prices([recommendation_to_update], FakeScraper)

    assert result[0].admission == existing


@qase.id(9)
@pytest.mark.qase
def test_enrichment_continues_after_one_scrape_fails():
    first = recommendation("first", "https://www.ticketmaster.pl/event/1")
    second = recommendation("second", "https://www.ticketmaster.pl/event/2")
    expected = Admission(False, 37.10, 63.60, "PLN")
    FakeScraper.prices = {first.url: RuntimeError("blocked"), second.url: expected}

    enrich_ticketmaster_prices([first, second], FakeScraper)

    assert first.admission is None
    assert second.admission == expected


def test_enrichment_skips_malformed_url_and_continues():
    FakeScraper.instances = []
    existing = Admission(False, 20, 20, "PLN")
    malformed = recommendation("malformed", "https://[invalid", existing)
    valid = recommendation("valid", "https://www.ticketmaster.pl/event/2")
    expected = Admission(False, 37.10, 63.60, "PLN")
    FakeScraper.prices = {valid.url: expected}
    recommendations = [malformed, valid]

    result = enrich_ticketmaster_prices(recommendations, FakeScraper)

    assert result is recommendations
    assert FakeScraper.instances[0].scraped_urls == [valid.url]
    assert malformed.admission == existing
    assert valid.admission == expected
