from src.models import Admission, Recommendation
from src.telegram_formatter import format_telegram_message
from src.ticketmaster_enrichment import enrich_ticketmaster_prices


def recommendation(event_id, url, admission=None):
    return Recommendation(
        event_id=event_id,
        name=event_id,
        category="music",
        date=None,
        time=None,
        city=None,
        venue=None,
        reason="A good event.",
        url=url,
        admission=admission,
    )


class FakeScraper:
    instances = []
    prices = {}

    def __init__(self):
        self.scraped_urls = []
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback):
        return None

    def scrape(self, url):
        self.scraped_urls.append(url)
        value = self.prices.get(url)
        if isinstance(value, Exception):
            raise value
        return value


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


def test_enrichment_keeps_existing_admission_when_scrape_returns_none():
    existing = Admission(False, 20, 20, "PLN")
    recommendation_to_update = recommendation(
        "event", "https://www.ticketmaster.pl/event/1", existing
    )
    FakeScraper.prices = {recommendation_to_update.url: None}

    result = enrich_ticketmaster_prices([recommendation_to_update], FakeScraper)

    assert result[0].admission == existing


def test_enrichment_continues_after_one_scrape_fails():
    first = recommendation("first", "https://www.ticketmaster.pl/event/1")
    second = recommendation("second", "https://www.ticketmaster.pl/event/2")
    expected = Admission(False, 37.10, 63.60, "PLN")
    FakeScraper.prices = {first.url: RuntimeError("blocked"), second.url: expected}

    enrich_ticketmaster_prices([first, second], FakeScraper)

    assert first.admission is None
    assert second.admission == expected


def test_enrichment_output_is_rendered_in_telegram_message():
    ticketmaster_recommendation = recommendation(
        "event", "https://www.ticketmaster.pl/event/1"
    )
    FakeScraper.prices = {
        ticketmaster_recommendation.url: Admission(False, 37.10, 63.60, "PLN")
    }

    enrich_ticketmaster_prices([ticketmaster_recommendation], FakeScraper)
    message = format_telegram_message(
        [ticketmaster_recommendation], "Tychy", 50, 30
    )

    assert "🎟 37,10–63,60 zł" in message