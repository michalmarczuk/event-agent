from src.models import Recommendation


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
