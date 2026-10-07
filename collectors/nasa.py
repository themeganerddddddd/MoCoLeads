from .feed_collector import collect_feed


def collect(days=14):
    return collect_feed("NASA", ["https://www.nasa.gov/news-release/feed/", "https://www.nasa.gov/feed/"],
                        ["award", "contract", "task order", "procurement"], days)
