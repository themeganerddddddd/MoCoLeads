from .feed_collector import collect_feed


def collect(days=30):
    return collect_feed("DARPA", ["https://www.darpa.mil/news/rss.xml", "https://www.darpa.mil/rss.xml"], ["contract", "award", "agreement"], days)
