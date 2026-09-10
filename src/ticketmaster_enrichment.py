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
) -> list[Recommendation]:
    """Enrich final Ticketmaster recommendations with visible web pricing."""
    ticketmaster_recommendations = [
        recommendation
        for recommendation in recommendations
        if _is_ticketmaster_url(getattr(recommendation, "url", None))
    ]
    if not ticketmaster_recommendations:
        return recommendations

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
            "Ticketmaster price enrichment setup failed",
            exc_info=True,
        )

    return recommendations


def _is_ticketmaster_url(url: str | None) -> bool:
    if not url:
        return False
    hostname = urlparse(url).hostname
    return hostname == "ticketmaster.pl" or bool(
        hostname and hostname.endswith(".ticketmaster.pl")
    )