import pytest
from qase.pytest import qase

from src.models import Admission
from src.telegram_formatter import format_telegram_message
from src.ticketmaster_enrichment import enrich_ticketmaster_prices
from tests.support.ticketmaster_enrichment_helpers import FakeScraper, recommendation


@qase.id(17)
@pytest.mark.qase
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
