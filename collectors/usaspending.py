from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable
from urllib.parse import quote

from .common import post
from pipeline.company_matcher import QUALIFYING_STATUSES, normalize_name, qualify_record

API_URL = "https://api.usaspending.gov/api/v2/search/spending_by_transaction/"
FIELDS = [
    "Award ID", "Recipient Name", "Recipient UEI", "Action Date", "Transaction Amount",
    "Awarding Agency", "Awarding Sub Agency", "Transaction Description", "Award Type",
    "NAICS", "PSC", "Recipient Location", "Primary Place of Performance", "generated_internal_id",
]
LAST_REPORT: dict = {}


def _record_from_item(item: dict, route: str, registry_company_id: str | None = None) -> dict:
    award_id = item.get("Award ID")
    generated_id = item.get("generated_internal_id")
    award_url = f"https://www.usaspending.gov/award/{quote(str(generated_id))}/" if generated_id else "https://www.usaspending.gov/search"
    return {
        "collector": "usaspending",
        "announcement_date": item.get("Action Date"),
        "action_date": item.get("Action Date"),
        "recipient_name": item.get("Recipient Name"),
        "recipient_uei": item.get("Recipient UEI"),
        "amount": item.get("Transaction Amount"),
        "agency": item.get("Awarding Agency"),
        "subagency": item.get("Awarding Sub Agency"),
        "description": item.get("Transaction Description"),
        "award_type": item.get("Award Type") or "Contract",
        "award_id": award_id,
        "contract_number": award_id,
        "naics": item.get("NAICS"),
        "psc": item.get("PSC"),
        "recipient_location": item.get("Recipient Location"),
        "place_of_performance": item.get("Primary Place of Performance"),
        "source_name": "USAspending",
        "source_type": "structured_award",
        "source_url": award_url,
        "registry_company_id": registry_company_id,
        "discovery_route": route,
    }


def _collect_pages(base_filters: dict, route: str, seen: set[str], registry_company_id: str | None = None, max_pages: int = 20) -> list[dict]:
    records: list[dict] = []
    page = 1
    while page <= max_pages:
        payload = {
            "filters": base_filters,
            "fields": FIELDS,
            "page": page,
            "limit": 100,
            "sort": "Action Date",
            "order": "desc",
        }
        data = post(API_URL, json=payload).json()
        for item in data.get("results", []):
            key = str(item.get("generated_internal_id") or "|".join(str(item.get(field) or "") for field in ("Award ID", "Action Date", "Transaction Amount")))
            if key in seen:
                continue
            seen.add(key)
            records.append(_record_from_item(item, route, registry_company_id))
        if not data.get("page_metadata", {}).get("hasNext"):
            break
        page += 1
    return records


def collect(companies: Iterable[dict], days: int = 7, today: date | None = None, performance_days: int | None = None) -> list[dict]:
    """Fetch known recipients, county recipients, and contracts performed in Montgomery County."""
    company_rows = list(companies)
    end = today or date.today()
    start = end - timedelta(days=max(days, 7))
    records: list[dict] = []
    seen: set[str] = set()
    common_filters = {
        "time_period": [{"start_date": start.isoformat(), "end_date": end.isoformat()}],
        "award_type_codes": ["A", "B", "C", "D"],
    }
    known_count = 0
    for company in company_rows:
        if company.get("hq_status") not in QUALIFYING_STATUSES:
            continue
        search_value = company.get("uei") or company.get("legal_name") or company.get("canonical_name")
        if not search_value:
            continue
        found = _collect_pages(
            {**common_filters, "recipient_search_text": [search_value]},
            "known_company",
            seen,
            company.get("company_id"),
        )
        known_count += len(found)
        records.extend(found)

    county_records = _collect_pages(
        {**common_filters, "recipient_locations": [{"country": "USA", "state": "MD", "county": "031"}]},
        "county_recipient",
        seen,
    )
    records.extend(county_records)
    performance_start = end - timedelta(days=max(performance_days or days, 7))
    performance_records = _collect_pages(
        {
            "time_period": [{"start_date": performance_start.isoformat(), "end_date": end.isoformat()}],
            "award_type_codes": ["A", "B", "C", "D"],
            "place_of_performance_locations": [{"country": "USA", "state": "MD", "county": "031"}],
        },
        "county_place_of_performance",
        seen,
        max_pages=200,
    )
    records.extend(performance_records)
    registry_names = {
        normalize_name(value)
        for company in company_rows
        for value in (company.get("canonical_name"), company.get("legal_name"), *(company.get("aliases_list") or []))
        if value
    }
    new_entities = {
        record.get("recipient_name")
        for record in county_records
        if record.get("recipient_name") and normalize_name(record.get("recipient_name")) not in registry_names
    }
    LAST_REPORT.clear()
    LAST_REPORT.update({
        "status": "success",
        "records_retrieved": len(records),
        "known_company_matches": known_count,
        "county_discovery_matches": len(county_records),
        "place_of_performance_matches": len(performance_records),
        "outside_company_performance_matches": sum(not bool(qualify_record(record, company_rows)[2]) for record in performance_records),
        "place_of_performance_lookback_days": max(performance_days or days, 7),
        "new_entities_discovered": len(new_entities),
    })
    return records


def get_last_report() -> dict:
    return dict(LAST_REPORT)
