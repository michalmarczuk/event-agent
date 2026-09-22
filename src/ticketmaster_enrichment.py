import logging
from collections.abc import Callable
from urllib.parse import urlparse

try:
    from .models import Recommendation
    from .tools.ticketmaster_price_scraper import TicketmasterPriceScraper
except ImportError:  # pragma: no cover - supports script execution
    from models import Recommendation
    from tools.ticketmaster_price_scraper import TicketmasterPriceScraper

logger = logging.getLogger(__name__)


def enrich_ticketmaster_prices(
    recommendations: list[Recommendation],
    scraper_factory: Callable[[], TicketmasterPriceScraper] = TicketmasterPriceScraper,
) -> None:
    """Mutate recommendations in place with scraped Ticketmaster admission data.

    A successful scrape replaces admission data. A failed or unavailable scrape
    preserves the existing admission.
    """
    ticketmaster_recommendations = [
        recommendation
        for recommendation in recommendations
        if recommendation.source == "ticketmaster"
        and _is_ticketmaster_url(recommendation.url)
    ]
    # Source identity is the first guard; hostname validation protects against
    # a malformed or stale canonical URL before opening a browser.
    if not ticketmaster_recommendations:
        return

    try:
        with scraper_factory() as scraper:
            for recommendation in ticketmaster_recommendations:
                try:
                    admission = scraper.scrape(recommendation.url)
                except Exception:
                    logger.warning(
                        "Ticketmaster price enrichment failed event_id=%s",
                        recommendation.event_id,
                        exc_info=True,
                    )
                    continue
                if admission is not None:
                    recommendation.admission = admission
    except Exception:
        logger.warning(
            "Ticketmaster price enrichment aborted",
            exc_info=True,
        )



def _is_ticketmaster_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        hostname = urlparse(url).hostname
    except ValueError:
        logger.warning("Ticketmaster price enrichment skipped: malformed URL")
        return False
    return hostname == "ticketmaster.pl" or bool(
        hostname and hostname.endswith(".ticketmaster.pl")
    )
