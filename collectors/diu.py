from .feed_collector import collect_feed


def collect(days=30):
    return collect_feed("DIU", ["https://www.diu.mil/latest/feed"], ["contract", "prototype", "award", "selection"], days)
