from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .common import session

INDEX_URL = "https://www.war.gov/news/contracts/"
RSS_URL_TEMPLATE = "https://www.war.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=400&Site=945&max={max_entries}"
PIPEWORX_MCP_URL = "https://gateway.pipeworx.io/dod-contract-announcements/mcp"
PIPEWORX_INFO_URL = "https://pipeworx.io/packs/dod-contract-announcements/"
OCT_6_FIXTURE_URL = "https://www.war.gov/News/Contracts/Contract/Article/4620231/contracts-for-oct-6-2026/"
DEFAULT_STATE_PATH = Path(__file__).resolve().parents[1] / "data" / "war_processed.json"
DEFAULT_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "war_oct_6_2026.html"

TITLE_RE = re.compile(r"^Contracts for\s+(.+?)$", re.I)
AWARD_MARKER_RE = re.compile(r"\b(?:has been|have been|was|were) awarded\s+(?:a|an)\b", re.I)
MONEY_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{1,2})?)\s*(billion|million|thousand)?", re.I)
AWARD_AMOUNT_RE = re.compile(
    r"\b(?:has been|have been|was|were) awarded\s+(?:a|an)\s+(?:(?:ceiling|maximum|estimated)\s+)?"
    r"\$\s*([\d,]+(?:\.\d{1,2})?)\s*(billion|million|thousand)?",
    re.I,
)
MODIFICATION_RE = re.compile(r"\bmodification\s*\(([A-Z]*P\d{4,})\)", re.I)
CONTRACT_NUMBER_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-/]{7,}$", re.I)
SERVICE_NAMES = {
    "AIR FORCE": "Air Force",
    "ARMY": "Army",
    "NAVY": "Navy",
    "MARINE CORPS": "Marine Corps",
    "MISSILE DEFENSE AGENCY": "Missile Defense Agency",
    "DEFENSE LOGISTICS AGENCY": "Defense Logistics Agency",
    "DEFENSE ADVANCED RESEARCH PROJECTS AGENCY": "Defense Advanced Research Projects Agency",
    "U.S. SPECIAL OPERATIONS COMMAND": "U.S. Special Operations Command",
    "WASHINGTON HEADQUARTERS SERVICES": "Washington Headquarters Services",
}
MONTH_FORMATS = ("%b %d, %Y", "%B %d, %Y")
LAST_REPORT: dict = {}


def _clean(text: str | None) -> str:
    return " ".join((text or "").replace("\xa0", " ").split())


def _amount(match):
    if not match:
        return None
    number = float(match.group(1).replace(",", ""))
    unit = (match.group(2) or "").casefold()
    number *= {"billion": 1_000_000_000, "million": 1_000_000, "thousand": 1_000}.get(unit, 1)
    return int(number) if number.is_integer() else number


def parse_amount(text: str):
    """Compatibility helper: return the first currency amount in text."""
    return _amount(MONEY_RE.search(text or ""))


def _parse_date_text(value: str | None) -> str | None:
    if not value:
        return None
    normalized = _clean(value).strip("(). ")
    normalized = re.sub(r"\bSept\.\s", "Sep ", normalized, flags=re.I)
    normalized = re.sub(r"\b([A-Z][a-z]{2})\.\s", r"\1 ", normalized)
    for fmt in MONTH_FORMATS:
        try:
            return datetime.strptime(normalized, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_contract_date(title: str) -> str | None:
    match = TITLE_RE.match(_clean(title))
    return _parse_date_text(match.group(1)) if match else None


def discover_announcements(html: str, base_url: str = INDEX_URL) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    discovered: list[dict] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        title = _clean(" ".join(anchor.stripped_strings))
        announcement_date = parse_contract_date(title)
        if not announcement_date:
            continue
        url = urljoin(base_url, anchor["href"])
        if url in seen:
            continue
        seen.add(url)
        discovered.append({"title": title, "announcement_date": announcement_date, "url": url})
    return sorted(discovered, key=lambda item: (item["announcement_date"], item["url"]), reverse=True)


def discover_announcements_from_rss(xml: str, base_url: str = INDEX_URL) -> list[dict]:
    root = ET.fromstring(xml)
    discovered: list[dict] = []
    seen: set[str] = set()
    for item in root.findall(".//item"):
        title = _clean(item.findtext("title"))
        url = urljoin(base_url, _clean(item.findtext("link")))
        announcement_date = parse_contract_date(title)
        if not announcement_date or not url or url in seen:
            continue
        seen.add(url)
        published = _clean(item.findtext("pubDate"))
        publication_date = None
        if published:
            try:
                publication_date = parsedate_to_datetime(published).date().isoformat()
            except (TypeError, ValueError):
                publication_date = None
        discovered.append({
            "title": title,
            "announcement_date": announcement_date,
            "publication_date": publication_date,
            "url": url,
        })
    return sorted(discovered, key=lambda entry: (entry["announcement_date"], entry["url"]), reverse=True)


def parse_contractor(text: str) -> tuple[str | None, str | None]:
    marker = AWARD_MARKER_RE.search(text)
    if not marker:
        return None, None
    lead = text[: marker.start()].strip(" ,")
    parts = [part.strip() for part in lead.split(",")]
    if len(parts) < 3:
        return None, None
    company = ", ".join(parts[:-2]).strip().rstrip("*")
    location = f"{parts[-2]}, {parts[-1]}"
    return company or None, location or None


def parse_award_amount(text: str):
    return _amount(AWARD_AMOUNT_RE.search(text))


def _award_sentence(text: str) -> str:
    marker = AWARD_MARKER_RE.search(text)
    clause = text[marker.start():] if marker else text
    return clause.split(". ", 1)[0]


def parse_action_type(text: str) -> str:
    first_sentence = _award_sentence(text).casefold()
    if "modification" in first_sentence:
        return "Modification"
    if "task order" in first_sentence:
        return "Task Order"
    if "delivery order" in first_sentence:
        return "Delivery Order"
    return "Contract"


def parse_contract_type(text: str) -> str | None:
    first_sentence = _award_sentence(text).casefold()
    if "indefinite-delivery/indefinite-quantity" in first_sentence or re.search(r"\bidiq\b", first_sentence):
        return "IDIQ"
    if "firm-fixed-price" in first_sentence:
        return "Firm-Fixed-Price"
    if "cost-plus-fixed-fee" in first_sentence:
        return "Cost-Plus-Fixed-Fee"
    return None


def parse_modification_number(text: str) -> str | None:
    match = MODIFICATION_RE.search(text)
    return match.group(1).upper() if match else None


def _valid_contract_number(value: str | None) -> bool:
    if not value:
        return False
    value = value.strip().rstrip(".,;")
    return bool(
        CONTRACT_NUMBER_RE.fullmatch(value)
        and re.search(r"[A-Z]", value, re.I)
        and re.search(r"\d", value)
        and not re.fullmatch(r"[A-Z]*P\d+", value, re.I)
    )


def parse_contract_number(text: str) -> str | None:
    activity = re.search(r"is the contracting activity\s*\(([A-Z0-9\-/]+)\)", text, re.I)
    if activity and _valid_contract_number(activity.group(1)):
        return activity.group(1).upper()
    patterns = (
        r"previously awarded contract\s*\(([A-Z0-9\-/]+)\)",
        r"previously awarded contract\s+([A-Z0-9][A-Z0-9\-/]{7,})",
        r"(?:contract|task order|delivery order)(?:\s+(?:No\.|number))?\s*\(?([A-Z0-9][A-Z0-9\-/]{7,})\)?",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            candidate = match.group(1).rstrip(".,;)")
            if _valid_contract_number(candidate):
                return candidate.upper()
    return None


class _SyntheticMatch:
    """Small match-like adapter used to share exact currency conversion logic."""

    def __init__(self, number: str, unit: str | None):
        self.values = (None, number, unit)

    def group(self, index: int):
        return self.values[index]


def parse_cumulative_values(text: str) -> tuple[int | float | None, int | float | None]:
    change = re.search(
        r"(?:brings|bring|increases?).{0,90}?total cumulative face value.{0,40}?to\s+"
        r"\$\s*([\d,]+(?:\.\d{1,2})?)\s*(billion|million|thousand)?\s+from\s+"
        r"\$\s*([\d,]+(?:\.\d{1,2})?)\s*(billion|million|thousand)?",
        text,
        re.I,
    )
    if change:
        current = _amount(_SyntheticMatch(change.group(1), change.group(2)))
        previous = _amount(_SyntheticMatch(change.group(3), change.group(4)))
        return current, previous
    current = re.search(
        r"total cumulative face value (?:of|is)\s+\$\s*([\d,]+(?:\.\d{1,2})?)\s*(billion|million|thousand)?",
        text,
        re.I,
    )
    return (_amount(current), None) if current else (None, None)


def parse_work_locations(text: str) -> list[str]:
    match = re.search(
        r"\b(?:Work will be performed|The location of performance is)\s+(?:at|in)?\s*(.+?)"
        r"(?=(?:;|,)?\s+and (?:is|work is) expected|\s+with an estimated completion date|"
        r"\.\s+(?:This|Fiscal|The|No funds|Work is)|$)",
        text,
        re.I,
    )
    if not match:
        return []
    value = match.group(1).strip(" ;,.")
    if re.search(r"various locations|multiple locations|determined with each order", value, re.I):
        return [value]
    parts = re.split(r"\s*;\s*(?:and\s+)?|\s+and\s+(?=[A-Z][^,;]{1,50},\s*[A-Z])", value)
    return [re.sub(r"^the\s+", "", part.strip(" ;,."), flags=re.I) for part in parts if part.strip(" ;,.")]


def parse_completion_date(text: str) -> tuple[str | None, str | None]:
    date_value = r"([A-Z][a-z]{2,8}\.?\s+\d{1,2},\s+\d{4}|[A-Z][a-z]{3,8}\s+\d{4})"
    patterns = (
        rf"(?:work\s+)?is expected to be complete(?:d)?\s+(?:by|in)\s+{date_value}",
        rf"with an estimated completion date of\s+{date_value}",
        rf"The performance completion date is\s+{date_value}",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            raw = _clean(match.group(1)).strip(" .")
            return _parse_date_text(raw), raw
    return None, None


def parse_explicit_award_date(text: str) -> str | None:
    match = re.search(r"\(Awarded(?:\s+on)?\s+([^)]+)\)", text, re.I)
    return _parse_date_text(match.group(1)) if match else None


def parse_funding(text: str) -> list[dict]:
    entries: list[dict] = []
    pattern = re.compile(
        r"Fiscal\s+(\d{4})\s+(.{2,160}?)\s+funds\s+in the amount of\s+"
        r"\$\s*([\d,]+(?:\.\d{1,2})?)\s*(billion|million|thousand)?\s+"
        r"(?:are|were|is|was) being obligated",
        re.I,
    )
    for match in pattern.finditer(text):
        funding_type = re.sub(r"^(?:and\s+)?Fiscal\s+\d{4}\s+", "", _clean(match.group(2)), flags=re.I)
        entries.append({
            "fiscal_year": int(match.group(1)),
            "type": funding_type,
            "amount": _amount(_SyntheticMatch(match.group(3), match.group(4))),
        })
    return entries


def parse_contracting_activity(text: str) -> str | None:
    matches = list(re.finditer(r"(?:^|[.!?]\s+)(?:The\s+)?([^.!?]+?)\s+is the contracting activity", text, re.I))
    return _clean(matches[-1].group(1)).strip(" ,") if matches else None


def parse_description(text: str) -> tuple[str, str]:
    first_sentence = _clean(text)
    marker = AWARD_MARKER_RE.search(first_sentence)
    if marker:
        end = first_sentence.find(". ", marker.end())
        first_sentence = first_sentence if end < 0 else first_sentence[:end]
    else:
        first_sentence = first_sentence.split(". ", 1)[0]
    first_sentence = first_sentence.strip()
    purpose = re.search(r"\bfor\s+(.+)$", first_sentence, re.I)
    description = purpose.group(1).strip(" .") if purpose else first_sentence
    return description, first_sentence


def parse_award(paragraph: str, service: str | None, announcement: dict) -> dict | None:
    text = _clean(paragraph)
    company, contractor_location = parse_contractor(text)
    award_amount = parse_award_amount(text)
    if not company or award_amount is None:
        return None
    action_type = parse_action_type(text)
    contract_type = parse_contract_type(text)
    modification_number = parse_modification_number(text)
    contract_number = parse_contract_number(text)
    cumulative_value, previous_cumulative_value = parse_cumulative_values(text)
    work_locations = parse_work_locations(text)
    completion_date, completion_text = parse_completion_date(text)
    funding = parse_funding(text)
    if funding:
        obligated_amount = sum(entry["amount"] for entry in funding if entry.get("amount") is not None)
    elif re.search(r"\bNo funds (?:are|were) being obligated", text, re.I):
        obligated_amount = 0
    else:
        obligated_amount = None
    description, raw_description = parse_description(text)
    is_ceiling = bool(re.search(r"\b(?:ceiling|maximum)\s+\$", text, re.I))
    award_date = parse_explicit_award_date(text)
    return {
        "collector": "war",
        "announcement_date": announcement.get("announcement_date"),
        "award_date": award_date,
        "action_date": award_date or announcement.get("announcement_date"),
        "company_name": company,
        "recipient_name": company,
        "announced_contractor_location": contractor_location,
        "recipient_location": contractor_location,
        "service": service,
        "agency": "Department of Defense",
        "subagency": service,
        "award_amount": award_amount,
        "amount": award_amount,
        "ceiling_value": award_amount if is_ceiling else None,
        "obligated_amount": obligated_amount,
        "funds_obligated": obligated_amount,
        "cumulative_value": cumulative_value,
        "previous_cumulative_value": previous_cumulative_value,
        "action_type": action_type,
        "award_type": action_type,
        "contract_type": contract_type,
        "modification_number": modification_number,
        "contract_number": contract_number,
        "description": description,
        "raw_description": raw_description,
        "raw_paragraph": text,
        "work_locations": work_locations,
        "work_location_display": "; ".join(work_locations) if work_locations else "Not disclosed",
        "place_of_performance": "; ".join(work_locations) if work_locations else None,
        "expected_completion_date": completion_date,
        "expected_completion_text": completion_text,
        "expected_completion": completion_date or completion_text,
        "funding": funding,
        "funding_fiscal_year": funding[0]["fiscal_year"] if len(funding) == 1 else None,
        "funding_type": funding[0]["type"] if len(funding) == 1 else None,
        "contracting_activity": parse_contracting_activity(text),
        "source_name": "War.gov",
        "source_type": "announcement",
        "source_url": announcement.get("url"),
        "source_announcement_date": announcement.get("announcement_date"),
    }


def _service_heading(text: str) -> str | None:
    normalized = _clean(text).upper().strip(":")
    return SERVICE_NAMES.get(normalized)


def split_article_into_award_units(html: str, announcement: dict) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    candidates = soup.select("article, .article-body, .body, .content")
    content = max(candidates, key=lambda node: len(node.get_text(" ", strip=True)), default=soup)
    service: str | None = None
    units: list[dict] = []
    for node in content.find_all(["h2", "h3", "h4", "p"]):
        text = _clean(node.get_text(" ", strip=True))
        if not text:
            continue
        heading = _service_heading(text)
        if heading and (node.name in {"h2", "h3", "h4"} or len(text) < 80):
            service = heading
            continue
        if AWARD_MARKER_RE.search(text) and MONEY_RE.search(text):
            units.append({"service": service, "paragraph": text, "announcement": announcement})
    return units


def parse_article(html: str, source_url: str, announcement_date: str | None = None, title: str | None = None) -> list[dict]:
    if announcement_date is None:
        soup = BeautifulSoup(html, "html.parser")
        title_node = soup.find("h1") or soup.title
        page_title = title or _clean(title_node.get_text(" ", strip=True) if title_node else "")
        announcement_date = parse_contract_date(page_title)
    announcement = {"title": title, "announcement_date": announcement_date, "url": source_url}
    return [
        record
        for unit in split_article_into_award_units(html, announcement)
        if (record := parse_award(unit["paragraph"], unit["service"], announcement))
    ]


def parse_contract_paragraph(text: str, *, source_url: str, announcement_date: str | None = None, agency: str | None = None) -> dict | None:
    """Backward-compatible entry point retained for downstream callers."""
    return parse_award(text, agency, {"url": source_url, "announcement_date": announcement_date})


def _load_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(path: Path, seen_urls: Iterable[str], processed_urls: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "seen_urls": sorted(set(seen_urls)),
        "processed_urls": sorted(set(processed_urls)),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _http_session():
    client = session()
    client.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": INDEX_URL,
    })
    return client


def fetch_with_browser(url: str) -> tuple[str | None, int | str]:
    """Make one ordinary headless browser attempt; never bypass access controls."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "playwright_unavailable"
    try:
        with sync_playwright() as playwright:
            browser = None
            last_error = None
            for channel in (None, "chrome", "msedge"):
                try:
                    options = {"headless": True}
                    if channel:
                        options["channel"] = channel
                    browser = playwright.chromium.launch(**options)
                    break
                except Exception as exc:
                    last_error = exc
            if browser is None:
                return None, f"browser_unavailable:{type(last_error).__name__ if last_error else 'unknown'}"
            try:
                page = browser.new_page(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
                )
                response = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                status = response.status if response else "no_response"
                return (page.content(), status) if status == 200 else (None, status)
            finally:
                browser.close()
    except Exception as exc:
        return None, f"browser_error:{type(exc).__name__}"


def _discover_with_fallback(client, report: dict) -> tuple[list[dict], str]:
    announcements: list[dict] = []
    try:
        response = client.get(INDEX_URL, timeout=30)
        report["html_index_status"] = response.status_code
        if response.status_code == 200:
            announcements = discover_announcements(response.text)
    except Exception as exc:
        report["html_index_status"] = f"error:{type(exc).__name__}"
    if announcements:
        print("War.gov discovery: html_index")
        return announcements, "html_index"

    rss_max = max(1, min(100, int(os.getenv("WAR_RSS_MAX", "20"))))
    rss_url = RSS_URL_TEMPLATE.format(max_entries=rss_max)
    try:
        response = client.get(rss_url, timeout=30)
        report["rss_status"] = response.status_code
        if response.status_code == 200:
            announcements = discover_announcements_from_rss(response.text)
    except Exception as exc:
        report["rss_status"] = f"error:{type(exc).__name__}"
    if announcements:
        print("War.gov discovery: rss")
        return announcements, "rss"
    raise RuntimeError(
        f"War.gov discovery failed (index={report.get('html_index_status')}, rss={report.get('rss_status')})"
    )


def _pipeworx_recent() -> tuple[list[dict], int | str]:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "dod_awards_recent", "arguments": {}},
    }
    try:
        response = session().post(PIPEWORX_MCP_URL, json=payload, timeout=45)
        status = response.status_code
        response.raise_for_status()
        rpc = response.json()
        if rpc.get("error"):
            return [], f"rpc_error:{rpc['error'].get('code', 'unknown')}"
        content = rpc.get("result", {}).get("content", [])
        text_item = next((item.get("text") for item in content if item.get("type") == "text"), None)
        decoded = json.loads(text_item) if text_item else {}
        awards = decoded.get("awards", [])
        return (awards if isinstance(awards, list) else []), status
    except Exception as exc:
        return [], f"error:{type(exc).__name__}"


def normalize_structured_fallback(award: dict, announcement: dict, discovery_method: str) -> dict | None:
    announced_on = award.get("announced_on")
    if announced_on != announcement.get("announcement_date"):
        return None
    provider_url = award.get("url")
    if provider_url and provider_url.rstrip("/") != announcement.get("url", "").rstrip("/"):
        return None
    company = award.get("contractor")
    amount = award.get("amount")
    if not company or isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return None
    description = _clean(award.get("description"))
    service = _service_heading(str(award.get("service") or "")) or _clean(award.get("service")).title() or None
    parsed = parse_award(description, service, announcement) or {}
    funding = parse_funding(description)
    obligated = sum(item["amount"] for item in funding if item.get("amount") is not None) if funding else None
    completion_text = _clean(award.get("completion_date")) or None
    completion_date = _parse_date_text(completion_text)
    work_locations = parse_work_locations(description)
    contract_types = award.get("contract_types") if isinstance(award.get("contract_types"), list) else []
    contract_type = "IDIQ" if any("indefinite-delivery" in str(value).casefold() for value in contract_types) else (contract_types[0] if contract_types else parsed.get("contract_type"))
    action_type = parsed.get("action_type") or ("Modification" if "modification" in description[:500].casefold() else "Contract")
    return {
        **parsed,
        "collector": "war",
        "announcement_date": announced_on,
        "award_date": parsed.get("award_date") or parse_explicit_award_date(description),
        "action_date": parsed.get("award_date") or parse_explicit_award_date(description) or announced_on,
        "company_name": company,
        "recipient_name": company,
        "announced_contractor_location": award.get("contractor_location"),
        "recipient_location": award.get("contractor_location"),
        "service": service,
        "agency": "Department of Defense",
        "subagency": service,
        "award_amount": amount,
        "amount": amount,
        "ceiling_value": amount if award.get("amount_is_ceiling") else parsed.get("ceiling_value"),
        "shared_award": bool(award.get("shared_award")),
        "obligated_amount": parsed.get("obligated_amount") if parsed.get("obligated_amount") is not None else obligated,
        "funds_obligated": parsed.get("funds_obligated") if parsed.get("funds_obligated") is not None else obligated,
        "contract_number": award.get("contract_number") or parsed.get("contract_number"),
        "contract_type": contract_type,
        "contract_types": contract_types,
        "action_type": action_type,
        "award_type": action_type,
        "description": parsed.get("description") or description,
        "raw_description": parsed.get("raw_description") or description,
        "raw_paragraph": description,
        "work_locations": work_locations,
        "work_location_display": "; ".join(work_locations) if work_locations else "Not disclosed",
        "place_of_performance": "; ".join(work_locations) if work_locations else None,
        "expected_completion_date": parsed.get("expected_completion_date") or completion_date,
        "expected_completion_text": parsed.get("expected_completion_text") or completion_text,
        "expected_completion": parsed.get("expected_completion") or completion_date or completion_text,
        "funding": parsed.get("funding") or funding,
        "contracting_activity": award.get("contracting_activity") or parsed.get("contracting_activity"),
        "fallback_award_key": award.get("award_key"),
        "source_name": "War.gov",
        "source_type": "announcement",
        "source_url": announcement.get("url"),
        "source_announcement_date": announced_on,
        "additional_sources": [{
            "name": "Pipeworx",
            "source_type": "retrieval_fallback",
            "source_url": PIPEWORX_INFO_URL,
            "primary": False,
        }],
        "retrieval": {
            "discovery_method": f"war_{discovery_method}",
            "content_method": "pipeworx_fallback",
        },
    }


def _structured_fallback(announcements: list[dict], discovery_method: str) -> tuple[list[dict], int | str]:
    awards, status = _pipeworx_recent()
    by_date: dict[str, list[dict]] = {}
    for announcement in announcements:
        by_date.setdefault(announcement["announcement_date"], []).append(announcement)
    normalized: list[dict] = []
    for award in awards:
        candidates = by_date.get(award.get("announced_on"), [])
        provider_url = str(award.get("url") or "").rstrip("/")
        if provider_url:
            candidates = [item for item in candidates if item["url"].rstrip("/") == provider_url]
        if len(candidates) != 1:
            continue
        record = normalize_structured_fallback(award, candidates[0], discovery_method)
        if record:
            normalized.append(record)
    return normalized, status


def get_last_report() -> dict:
    return dict(LAST_REPORT)


def collect(days: int = 7, today: date | None = None, state_path: str | Path | None = None) -> list[dict]:
    client = _http_session()
    report = {
        "html_index_status": None,
        "rss_status": None,
        "discovery_method": None,
        "announcements_discovered": 0,
        "article_requests": 0,
        "article_http_successes": 0,
        "browser_attempts": 0,
        "browser_successes": 0,
        "structured_fallback_status": None,
        "structured_fallback_awards": 0,
        "unresolved_announcements": 0,
        "status": "failed",
    }
    try:
        announcements, discovery_method = _discover_with_fallback(client, report)
    except Exception:
        LAST_REPORT.clear()
        LAST_REPORT.update(report)
        raise
    report["discovery_method"] = discovery_method
    report["announcements_discovered"] = len(announcements)
    state_file = Path(state_path) if state_path else DEFAULT_STATE_PATH
    state = _load_state(state_file)
    seen_before = set(state.get("seen_urls", []))
    processed = set(state.get("processed_urls", []))
    current_urls = {item["url"] for item in announcements}

    lookback_days = max(7, int(os.getenv("WAR_LOOKBACK_DAYS", str(days))))
    bootstrap_value = os.getenv("WAR_BOOTSTRAP_DAYS")
    effective_days = max(lookback_days, int(bootstrap_value)) if bootstrap_value else lookback_days
    cutoff = (today or date.today()) - timedelta(days=effective_days)
    first_discovery = not seen_before
    selected = [
        item for item in announcements
        if date.fromisoformat(item["announcement_date"]) >= cutoff
        or (not first_discovery and item["url"] not in processed)
    ]

    records: list[dict] = []
    failed_announcements: list[dict] = []
    for announcement in selected:
        report["article_requests"] += 1
        try:
            response = client.get(announcement["url"], timeout=30)
            if response.status_code == 403:
                print("War.gov article blocked: HTTP 403", file=sys.stderr)
                print(f"Announcement: {announcement['title']}", file=sys.stderr)
                print(f"URL: {announcement['url']}", file=sys.stderr)
                report["browser_attempts"] += 1
                browser_html, browser_status = fetch_with_browser(announcement["url"])
                if browser_html and browser_status == 200:
                    parsed = parse_article(browser_html, announcement["url"], announcement["announcement_date"], announcement["title"])
                    for record in parsed:
                        record["retrieval"] = {
                            "discovery_method": f"war_{discovery_method}",
                            "content_method": "browser",
                        }
                    records.extend(parsed)
                    processed.add(announcement["url"])
                    report["browser_successes"] += 1
                    continue
                failed_announcements.append(announcement)
                continue
            response.raise_for_status()
            parsed = parse_article(response.text, announcement["url"], announcement["announcement_date"], announcement["title"])
            for record in parsed:
                record["retrieval"] = {
                    "discovery_method": f"war_{discovery_method}",
                    "content_method": "requests",
                }
            records.extend(parsed)
            processed.add(announcement["url"])
            report["article_http_successes"] += 1
        except Exception as exc:
            print(f"War.gov article failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            print(f"Announcement: {announcement['title']}", file=sys.stderr)
            print(f"URL: {announcement['url']}", file=sys.stderr)
            failed_announcements.append(announcement)

    if failed_announcements:
        fallback_records, fallback_status = _structured_fallback(failed_announcements, discovery_method)
        report["structured_fallback_status"] = fallback_status
        report["structured_fallback_awards"] = len(fallback_records)
        records.extend(fallback_records)
        recovered_urls = {record["source_url"] for record in fallback_records}
        processed.update(recovered_urls)
        report["unresolved_announcements"] = len({item["url"] for item in failed_announcements} - recovered_urls)

    if report["unresolved_announcements"]:
        report["status"] = "partial" if records else "failed"
    elif report["structured_fallback_awards"]:
        report["status"] = "fallback"
    else:
        report["status"] = "success"
    _save_state(state_file, seen_before | current_urls, processed)
    LAST_REPORT.clear()
    LAST_REPORT.update(report)
    print(f"War.gov collector status: {report['status']}")
    return records


def debug_report(fixture_path: str | Path = DEFAULT_FIXTURE_PATH) -> None:
    client = _http_session()
    discovery_report: dict = {}
    try:
        announcements, discovery_method = _discover_with_fallback(client, discovery_report)
    except Exception as exc:
        announcements = []
        discovery_method = f"failed ({type(exc).__name__}: {exc})"
    print("Live transport diagnostic:")
    print(f"War.gov index status: {discovery_report.get('html_index_status', 'not attempted')}")
    print(f"War.gov RSS status: {discovery_report.get('rss_status', 'not attempted')}")
    print(f"Discovery method: {discovery_method}")
    print(f"Dated links discovered: {len(announcements)}")
    print(f"Newest announcement: {announcements[0]['title'] if announcements else 'Unavailable'}")
    print(f"Newest announcement URL: {announcements[0]['url'] if announcements else 'Unavailable'}")

    article_status: int | str = "not attempted"
    browser_status: int | str = "not attempted"
    fallback_status: int | str = "not attempted"
    live_records: list[dict] = []
    if announcements:
        newest = announcements[0]
        try:
            article_response = client.get(newest["url"], timeout=30)
            article_status = article_response.status_code
            if article_response.status_code == 200:
                live_records = parse_article(
                    article_response.text, newest["url"], newest["announcement_date"], newest["title"]
                )
            elif article_response.status_code == 403:
                browser_html, browser_status = fetch_with_browser(newest["url"])
                if browser_html and browser_status == 200:
                    live_records = parse_article(
                        browser_html, newest["url"], newest["announcement_date"], newest["title"]
                    )
        except Exception as exc:
            article_status = f"error ({type(exc).__name__})"
        if not live_records:
            live_records, fallback_status = _structured_fallback([newest], discovery_method)
    print(f"Normal article request status: {article_status}")
    print(f"Browser fallback status: {browser_status}")
    print(f"Structured fallback status: {fallback_status}")
    print(f"Newest announcement awards recovered: {len(live_records)}")

    print("\nSaved Oct. 6 parser regression:")
    html = Path(fixture_path).read_text(encoding="utf-8")
    announcement = {
        "title": "Contracts for Oct. 6, 2026",
        "announcement_date": "2026-10-06",
        "url": OCT_6_FIXTURE_URL,
    }
    units = split_article_into_award_units(html, announcement)
    parsed = [
        record
        for unit in units
        if (record := parse_award(unit["paragraph"], unit["service"], announcement))
    ]
    print(f"Service sections detected: {len(set(unit['service'] for unit in units if unit['service']))}")
    print(f"Award paragraphs detected: {len(units)}")
    print(f"Contracts successfully parsed: {len(parsed)}")
    by_company = {record["company_name"]: record for record in parsed}
    weldin = by_company.get("Weldin Construction LLC", {})
    aegis = by_company.get("Aegis Aerospace Inc.", {})
    print("\nWeldin:")
    print(f"Amount: {weldin.get('award_amount')}")
    print(f"Ceiling: {weldin.get('ceiling_value')}")
    print(f"Obligated: {weldin.get('obligated_amount')}")
    print(f"Contract #: {weldin.get('contract_number')}")
    print(f"Locations: {weldin.get('work_locations')}")
    print("\nAegis:")
    print(f"Modification amount: {aegis.get('award_amount')}")
    print(f"Modification #: {aegis.get('modification_number')}")
    print(f"Underlying contract #: {aegis.get('contract_number')}")
    print(f"Cumulative value: {aegis.get('cumulative_value')}")
    print(f"Location: {aegis.get('work_locations')}")
    from pipeline.company_matcher import load_registry, match_company
    registry = load_registry(Path(__file__).resolve().parents[1] / "companies" / "moco_companies.csv")
    matches = [record for record in parsed if match_company(record, registry)[0]]
    print(f"\nMontgomery County matches: {len(matches)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="War.gov daily contract collector")
    parser.add_argument("--debug", action="store_true", help="Probe current access and print the Oct. 6 regression report")
    args = parser.parse_args()
    if args.debug:
        debug_report()
