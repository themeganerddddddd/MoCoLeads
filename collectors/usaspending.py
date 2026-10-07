from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable
from urllib.parse import quote

from .common import post

API_URL = "https://api.usaspending.gov/api/v2/search/spending_by_transaction/"
FIELDS = [
    "Award ID", "Recipient Name", "Recipient UEI", "Action Date", "Transaction Amount",
    "Awarding Agency", "Awarding Sub Agency", "Transaction Description", "Award Type",
    "NAICS", "PSC", "Recipient Location", "Primary Place of Performance", "generated_internal_id",
]


def collect(companies: Iterable[dict], days: int = 7, today: date | None = None) -> list[dict]:
    """Fetch recent contract transactions for registry companies, never assuming recipient address is HQ."""
    end = today or date.today()
    start = end - timedelta(days=max(days, 7))
    records: list[dict] = []
    seen: set[str] = set()
    for company in companies:
        search_name = company.get("legal_name") or company.get("canonical_name")
        if not search_name:
            continue
        page = 1
        while page <= 5:
            payload = {
                "filters": {
                    "time_period": [{"start_date": start.isoformat(), "end_date": end.isoformat()}],
                    "award_type_codes": ["A", "B", "C", "D"],
                    "recipient_search_text": [search_name],
                },
                "fields": FIELDS,
                "page": page,
                "limit": 100,
                "sort": "Action Date",
                "order": "desc",
            }
            data = post(API_URL, json=payload).json()
            results = data.get("results", [])
            for item in results:
                key = str(item.get("generated_internal_id") or "|").join((str(item.get("Award ID")), str(item.get("Action Date")), str(item.get("Transaction Amount"))))
                if key in seen:
                    continue
                seen.add(key)
                award_id = item.get("Award ID")
                generated_id = item.get("generated_internal_id")
                award_url = f"https://www.usaspending.gov/award/{quote(str(generated_id))}/" if generated_id else "https://www.usaspending.gov/search"
                records.append({
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
                    "registry_company_id": company.get("company_id"),
                })
            if not data.get("page_metadata", {}).get("hasNext"):
                break
            page += 1
    return records
