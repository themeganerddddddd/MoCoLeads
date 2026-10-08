from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .common import get
from .war_contracts import parse_amount

INDEX_URL = "https://www.diu.mil/latest"
RELEVANT_RE = re.compile(
    r"\b(contract|prototype agreement|prototype|award|selected vendors?|companies selected|"
    r"companies? (?:was|were|has been|have been|is|are) selected|selects?)\b",
    re.I,
)
DATE_RE = re.compile(r"\b(\d{1,2}\s+[A-Z][a-z]+\s+\d{4})\b")
LAST_REPORT: dict = {}


def _parse_date(value: str) -> str | None:
    match = DATE_RE.search(value or "")
    if not match:
        return None
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(match.group(1), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def discover_announcements(html: str, base_url: str = INDEX_URL) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    announcements: list[dict] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        if "/latest/" not in href:
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        card_text = " ".join(anchor.stripped_strings)
        if not RELEVANT_RE.search(card_text):
            continue
        seen.add(url)
        announced_on = _parse_date(card_text)
        title = DATE_RE.sub("", re.sub(r"^[^|]{1,30}\|", "", card_text)).strip(" |-–")
        announcements.append({"title": title or card_text, "announcement_date": announced_on, "url": url})
    return announcements


def _split_companies(value: str) -> list[str]:
    value = re.sub(r"\([^)]*\)", "", value)
    value = re.sub(r"^(?:the\s+)?(?:following\s+)?(?:companies|vendors)\s*:?\s*", "", value, flags=re.I)
    parts = re.split(r"\s*,\s*|\s+and\s+", value)
    companies = []
    for part in parts:
        company = part.strip(" .:;–—")
        company = re.sub(r"^(?:and|both|including)\s+", "", company, flags=re.I)
        if company and 1 <= len(company.split()) <= 12 and not re.search(r"\b(DIU|DoD|Department|project|prototype)\b", company, re.I):
            companies.append(company)
    return list(dict.fromkeys(companies))


def parse_companies(text: str) -> list[str]:
    patterns = (
        r"\bDIU\s+(?:has\s+)?selected\s+(.+?)\s+to\s+(?:develop|deliver|provide|support|prototype|build|advance)\b",
        r"\b(?:companies|vendors)\s+selected\s*(?:include|are|:)\s*(.+?)(?=\.|\n)",
        r"\bselected\s+(?:vendors|companies)\s*(?:include|are|:)\s*(.+?)(?=\.|\n)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            companies = _split_companies(" ".join(match.group(1).split()))
            if companies:
                return companies
    return []


def parse_article(html: str, url: str, fallback_date: str | None = None, fallback_title: str | None = None) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.find("h1")
    title = " ".join(title_node.stripped_strings) if title_node else (fallback_title or "DIU announcement")
    main = soup.find("main") or soup
    article = soup.find("article") or main
    body = " ".join(article.stripped_strings)
    header_text = " ".join(main.stripped_strings)[:1000]
    announced_on = _parse_date(header_text) or fallback_date or date.today().isoformat()
    companies = parse_companies(body)
    amount = parse_amount(f"{title} {body}")
    return [
        {
            "collector": "diu",
            "announcement_date": announced_on,
            "action_date": announced_on,
            "recipient_name": company,
            "amount": amount,
            "agency": "Department of Defense",
            "subagency": "Defense Innovation Unit",
            "description": body or title,
            "title": title,
            "program": title,
            "award_type": "Prototype / Selection",
            "source_name": "DIU",
            "source_type": "announcement",
            "source_url": url,
        }
        for company in companies
    ]


def collect(days: int = 30, today: date | None = None) -> list[dict]:
    report = {
        "index_status": None,
        "discovery_method": "html_index",
        "announcements_discovered": 0,
        "announcements_relevant": 0,
        "article_successes": 0,
        "article_failures": 0,
        "records_retrieved": 0,
        "status": "failed",
    }
    try:
        response = get(INDEX_URL)
        report["index_status"] = response.status_code
    except Exception as exc:
        report["index_status"] = f"error:{type(exc).__name__}"
        LAST_REPORT.clear(); LAST_REPORT.update(report)
        raise RuntimeError(f"DIU HTML index request failed: {type(exc).__name__}: {exc}") from exc

    announcements = discover_announcements(response.text)
    report["announcements_discovered"] = len(announcements)
    cutoff = (today or date.today()) - timedelta(days=max(days, 7))
    selected = [
        item for item in announcements
        if not item.get("announcement_date") or date.fromisoformat(item["announcement_date"]) >= cutoff
    ]
    report["announcements_relevant"] = len(selected)
    records: list[dict] = []
    for announcement in selected:
        try:
            article_response = get(announcement["url"])
            parsed = parse_article(article_response.text, announcement["url"], announcement.get("announcement_date"), announcement.get("title"))
            records.extend(parsed)
            report["article_successes"] += 1
        except Exception as exc:
            report["article_failures"] += 1
            print(f"DIU article failed: {announcement['url']} ({type(exc).__name__}: {exc})")
    report["records_retrieved"] = len(records)
    report["status"] = "partial" if report["article_failures"] else "success"
    LAST_REPORT.clear(); LAST_REPORT.update(report)
    return records


def get_last_report() -> dict:
    return dict(LAST_REPORT)
