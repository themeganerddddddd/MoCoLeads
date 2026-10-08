from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .classify import classify
from .company_matcher import company_payload, match_company, moco_performance_evidence, moco_recipient_evidence
from .contacts import federal_contact_payload, registry_company_contact
from .locations import format_location, parse_work_locations
from .market import apply_market_relationship


def parse_numeric_amount(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        normalized = str(value).replace("$", "").replace(",", "").strip()
        multiplier = 1
        if normalized[-1:].lower() in {"k", "m", "b"}:
            multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[normalized[-1].lower()]
            normalized = normalized[:-1]
        number = Decimal(normalized) * multiplier
        return int(number) if number == number.to_integral() else float(number)
    except (InvalidOperation, ValueError):
        return None


def amount_display(amount) -> str:
    if amount is None:
        return "Not disclosed"
    amount = float(amount)
    for threshold, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs(amount) >= threshold:
            value = amount / threshold
            return f"${value:.1f}{suffix}".replace(".0", "")
    return f"${amount:,.0f}"


def format_code(value):
    """Flatten USAspending code objects into stable JSON scalar values."""
    if isinstance(value, dict):
        return value.get("code") or value.get("naics") or value.get("psc") or None
    return value


def company_contact_payload(company: dict | None) -> dict | None:
    """Backward-compatible import used by update/tests."""
    return registry_company_contact(company)


def government_contact_payload(raw: dict) -> dict | None:
    """Backward-compatible alias; new records store this as contacts.federal."""
    return federal_contact_payload(raw)


def normalize_record(raw: dict, companies: list[dict], retrieved_at: str | None = None) -> dict:
    company, match_method = match_company(raw, companies)
    if not company and moco_recipient_evidence(raw.get("recipient_location")):
        match_method = "federal_recipient_address"
    amount = parse_numeric_amount(raw.get("amount"))
    recipient_location = format_location(raw.get("recipient_location"))
    performance = format_location(raw.get("place_of_performance"))
    work_locations = parse_work_locations(raw.get("work_locations") or performance)
    source_url = raw.get("source_url")
    source = {
        "name": raw.get("source_name") or raw.get("collector") or "Unknown",
        "source_type": raw.get("source_type") or "announcement",
        "source_url": source_url,
        "retrieved_at": retrieved_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "announcement_date": raw.get("source_announcement_date") or raw.get("announcement_date"),
        "primary": True,
    }
    additional_sources = []
    for additional in raw.get("additional_sources") or []:
        if not isinstance(additional, dict) or not additional.get("source_url"):
            continue
        additional_sources.append({
            "name": additional.get("name") or "Unknown",
            "source_type": additional.get("source_type") or "reference",
            "source_url": additional["source_url"],
            "retrieved_at": retrieved_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "announcement_date": additional.get("announcement_date") or raw.get("source_announcement_date") or raw.get("announcement_date"),
            "primary": False,
        })
    identity = "|".join(str(x or "") for x in [raw.get("contract_number"), raw.get("award_id"), raw.get("recipient_name"), amount, raw.get("action_date") or raw.get("announcement_date"), source_url])
    record = {
        "id": "moco-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
        "announcement_date": raw.get("announcement_date") or raw.get("action_date"),
        "action_date": raw.get("action_date") or raw.get("announcement_date"),
        "company": company_payload(company, raw),
        "award": {
            "amount": amount, "amount_display": amount_display(amount), "agency": raw.get("agency") or "Not disclosed",
            "subagency": raw.get("subagency"), "contract_number": raw.get("contract_number"), "award_id": raw.get("award_id"),
            "description": raw.get("description") or raw.get("title") or "Not disclosed", "naics": format_code(raw.get("naics")),
            "psc": format_code(raw.get("psc")), "award_type": raw.get("award_type") or "Contract",
            "expected_completion": raw.get("expected_completion"), "expected_completion_date": raw.get("expected_completion_date"),
            "award_date": raw.get("award_date"), "action_type": raw.get("action_type"),
            "contract_type": raw.get("contract_type"), "modification_number": raw.get("modification_number"),
            "ceiling_value": parse_numeric_amount(raw.get("ceiling_value")),
            "obligated_amount": parse_numeric_amount(raw.get("obligated_amount")),
            "funds_obligated": parse_numeric_amount(raw.get("funds_obligated")),
            "cumulative_value": parse_numeric_amount(raw.get("cumulative_value")),
            "previous_cumulative_value": parse_numeric_amount(raw.get("previous_cumulative_value")),
            "contracting_activity": raw.get("contracting_activity"), "funding": raw.get("funding") or [],
            "raw_description": raw.get("raw_description"),
        },
        "location": {
            "recipient_location": recipient_location,
            "place_of_performance": performance,
            "work_locations": work_locations,
            "recipient_moco_evidence": moco_recipient_evidence(raw.get("recipient_location")),
            "performance_moco_evidence": moco_performance_evidence(raw.get("place_of_performance")),
        },
        "classification": {}, "source": source, "sources": [source.copy(), *additional_sources],
        "match": {"method": match_method, "registry_company_id": company.get("company_id") if company else None},
        "contacts": {
            "company": company_contact_payload(company),
            "federal": federal_contact_payload(raw),
        },
    }
    if raw.get("retrieval"):
        record["retrieval"] = raw["retrieval"]
    record["classification"] = classify(record)
    return apply_market_relationship(record)
