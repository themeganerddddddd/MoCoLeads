from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable

LEGAL_SUFFIXES = re.compile(r"\b(incorporated|inc|llc|ltd|limited|corp|corporation|company|co|lp|l\.p)\b", re.I)
PUNCT = re.compile(r"[^a-z0-9]+")
MOCO_CITIES = {
    "bethesda", "rockville", "gaithersburg", "germantown", "silver spring", "takoma park",
    "chevy chase", "potomac", "olney", "wheaton", "kensington", "clarksburg", "burtonsville",
    "derwood", "poolesville", "damascus", "boyds", "montgomery village", "north bethesda",
    "brookeville", "cabin john", "sandy spring", "spencerville", "dickerson", "barnesville",
    "garrett park", "washington grove",
}
QUALIFYING_STATUSES = {"verified", "strong", "local_entity"}


def normalize_name(value: str | None) -> str:
    value = (value or "").casefold().replace("&", " and ")
    value = LEGAL_SUFFIXES.sub(" ", value)
    return " ".join(PUNCT.sub(" ", value).split())


def load_registry(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["aliases_list"] = [x.strip() for x in (row.get("aliases") or "").split("|") if x.strip()]
        row["hq_verified"] = str(row.get("hq_verified", "")).lower() in {"true", "1", "yes"}
        try:
            row["hq_confidence"] = float(row.get("hq_confidence") or 0)
        except ValueError:
            row["hq_confidence"] = 0.0
    return rows


def build_indexes(companies: Iterable[dict]):
    by_uei: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for company in companies:
        if company.get("uei"):
            by_uei[company["uei"].strip().upper()] = company
        for value in [company.get("canonical_name"), company.get("legal_name"), *company.get("aliases_list", [])]:
            normalized = normalize_name(value)
            if normalized:
                by_name[normalized] = company
    return by_uei, by_name


def match_company(record: dict, companies: Iterable[dict]) -> tuple[dict | None, str | None]:
    by_uei, by_name = build_indexes(companies)
    uei = str(record.get("recipient_uei") or "").strip().upper()
    if uei and uei in by_uei:
        return by_uei[uei], "uei"
    normalized = normalize_name(record.get("recipient_name"))
    if normalized in by_name:
        return by_name[normalized], "exact_name"
    # Conservative alias containment, only for distinctive names of at least two tokens.
    for alias, company in by_name.items():
        if len(alias.split()) >= 2 and (normalized.startswith(alias + " ") or alias.startswith(normalized + " ")):
            return company, "alias_prefix"
    # Announcement feeds may describe a company without a dedicated recipient field.
    # Require a distinctive multi-word registry name to appear as a full normalized phrase.
    haystack = normalize_name(" ".join(str(record.get(key) or "") for key in ("title", "description")))
    padded = f" {haystack} "
    for alias, company in sorted(by_name.items(), key=lambda item: len(item[0]), reverse=True):
        if len(alias.split()) >= 2 and f" {alias} " in padded:
            return company, "announcement_text"
    return None, None


def location_text(location) -> str:
    if isinstance(location, dict):
        return " ".join(str(v) for v in location.values() if v)
    return str(location or "")


def moco_recipient_evidence(location) -> dict | None:
    """Return official recipient-address evidence; never inspect place of performance."""
    text = location_text(location).casefold()
    if isinstance(location, dict):
        state = str(location.get("state_code") or location.get("state") or location.get("state_name") or "").casefold()
        county = str(location.get("county_name") or location.get("county") or "").casefold()
        county_code = str(location.get("county_code") or location.get("county_fips") or location.get("county_fips_code") or "").strip()
        full_fips = str(location.get("fips") or location.get("location_fips") or "").strip()
        city = str(location.get("city_name") or location.get("city") or "").casefold()
        state_is_md = state in {"md", "maryland", "24"} or full_fips.startswith("24")
        county_is_moco = county in {"montgomery", "montgomery county"} or county_code in {"031", "24031"} or full_fips == "24031"
        if state_is_md and county_is_moco:
            return {"basis": "federal_recipient_address", "confidence": 0.95, "reason": "Montgomery County recipient FIPS/county"}
        if state_is_md and city in MOCO_CITIES:
            return {"basis": "federal_recipient_address", "confidence": 0.85, "reason": f"official recipient city: {city.title()}, Maryland"}
    if re.search(r"\b24031\b", text):
        return {"basis": "federal_recipient_address", "confidence": 0.95, "reason": "Montgomery County FIPS 24031"}
    state_match = bool(re.search(r"\b(md|maryland)\b", text))
    county_match = bool(re.search(r"\bmontgomery(?:\s+county)?\b", text))
    city = next((city for city in MOCO_CITIES if re.search(rf"\b{re.escape(city)}\b", text)), None)
    if state_match and county_match:
        return {"basis": "federal_recipient_address", "confidence": 0.95, "reason": "official Montgomery County recipient address"}
    if state_match and city:
        return {"basis": "federal_recipient_address", "confidence": 0.85, "reason": f"official recipient city: {city.title()}, Maryland"}
    return None


def is_possible_moco_address(location) -> bool:
    return moco_recipient_evidence(location) is not None


def moco_performance_evidence(location) -> dict | None:
    """Return Montgomery County evidence for the work location, never the recipient."""
    evidence = moco_recipient_evidence(location)
    if not evidence:
        return None
    reason = evidence["reason"].replace("recipient", "place of performance").replace("address", "location")
    return {**evidence, "basis": "federal_place_of_performance", "reason": reason}


def qualify_record(record: dict, companies: Iterable[dict]) -> tuple[dict | None, str | None, dict | None]:
    company, method = match_company(record, companies)
    if company:
        status = company.get("hq_status") or "needs_review"
        if status in QUALIFYING_STATUSES:
            return company, method, {
                "basis": company.get("moco_basis") or ("verified_local_legal_entity" if status == "local_entity" else "manual_registry"),
                "confidence": float(company.get("moco_confidence") or company.get("hq_confidence") or 0),
                "reason": f"registry status: {status}",
            }
        return company, "registry_conflict", None
    evidence = moco_recipient_evidence(record.get("recipient_location"))
    return None, (evidence or {}).get("basis"), evidence


def company_payload(company: dict | None, record: dict) -> dict:
    if company:
        status = company.get("hq_status") or "needs_review"
        return {
            "company_id": company.get("company_id") or None,
            "canonical_name": company.get("canonical_name"), "legal_name": company.get("legal_name") or company.get("canonical_name"),
            "uei": company.get("uei") or record.get("recipient_uei"), "ultimate_parent": company.get("ultimate_parent") or None,
            "hq_city": company.get("hq_city") or None, "hq_state": company.get("hq_state") or None,
            "hq_county": company.get("hq_county") or None, "hq_verified": bool(company.get("hq_verified")),
            "hq_status": status, "hq_confidence": float(company.get("hq_confidence") or 0),
            "moco_city": company.get("hq_city") or None,
            "moco_basis": company.get("moco_basis") or ("verified_local_legal_entity" if status == "local_entity" else "manual_registry"),
            "moco_confidence": float(company.get("moco_confidence") or company.get("hq_confidence") or 0),
        }
    evidence = moco_recipient_evidence(record.get("recipient_location"))
    location = record.get("recipient_location")
    text = location_text(location).casefold()
    if isinstance(location, dict):
        city = location.get("city_name") or location.get("city")
    else:
        city = next((candidate.title() for candidate in MOCO_CITIES if re.search(rf"\b{re.escape(candidate)}\b", text)), None)
    uei = str(record.get("recipient_uei") or "").strip().upper()
    name_key = normalize_name(record.get("recipient_name")).replace(" ", "-")[:80] or "unknown-recipient"
    return {
        "company_id": f"uei-{uei.casefold()}" if uei else f"name-{name_key}",
        "canonical_name": record.get("recipient_name") or "Unknown recipient", "legal_name": record.get("recipient_name"),
        "uei": record.get("recipient_uei"), "ultimate_parent": None, "hq_city": city, "hq_state": "MD" if evidence else None,
        "hq_county": "Montgomery County" if evidence else None, "hq_verified": False,
        "hq_status": "local_entity" if evidence else "not_moco", "hq_confidence": float((evidence or {}).get("confidence", 0)),
        "moco_city": city, "moco_basis": (evidence or {}).get("basis"), "moco_confidence": float((evidence or {}).get("confidence", 0)),
    }
