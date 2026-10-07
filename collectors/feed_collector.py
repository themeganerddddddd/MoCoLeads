from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable
from urllib.parse import urljoin
import re
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from .common import get
from .war_contracts import parse_amount


def collect_feed(source_name: str, feed_urls: Iterable[str], keywords: Iterable[str], days: int = 14) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    pattern = re.compile("|".join(re.escape(k) for k in keywords), re.I)
    for feed_url in feed_urls:
        try:
            response = get(feed_url)
            root = ET.fromstring(response.content)
        except Exception:
            continue
        records: list[dict] = []
        for item in root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry"):
            def text_of(*names):
                for name in names:
                    node = item.find(name)
                    if node is not None:
                        return node.text or node.get("href")
                return None
            title = text_of("title", "{http://www.w3.org/2005/Atom}title") or ""
            summary = text_of("description", "{http://www.w3.org/2005/Atom}summary", "{http://www.w3.org/2005/Atom}content") or ""
            clean = BeautifulSoup(summary, "html.parser").get_text(" ", strip=True)
            if not pattern.search(f"{title} {clean}"):
                continue
            raw_date = text_of("pubDate", "{http://www.w3.org/2005/Atom}published", "{http://www.w3.org/2005/Atom}updated")
            published = None
            if raw_date:
                try:
                    published = parsedate_to_datetime(raw_date)
                except (ValueError, TypeError):
                    try:
                        published = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                    except ValueError:
                        pass
            if published and published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            if published and published < cutoff:
                continue
            link = text_of("link", "{http://www.w3.org/2005/Atom}link") or feed_url
            records.append({
                "collector": source_name.lower(), "announcement_date": published.date().isoformat() if published else date.today().isoformat(),
                "recipient_name": None, "amount": parse_amount(f"{title} {clean}"), "agency": source_name,
                "description": clean or title, "source_name": source_name, "source_type": "announcement",
                "source_url": urljoin(feed_url, link), "title": title,
            })
        return records
    raise RuntimeError(f"No working feed found for {source_name}")
