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
}
MOCO_ZIP_PREFIXES = {"208", "209"}


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


def is_possible_moco_address(location) -> bool:
    text = location_text(location).casefold()
    city_match = any(re.search(rf"\b{re.escape(city)}\b", text) for city in MOCO_CITIES)
    state_match = bool(re.search(r"\b(md|maryland)\b", text))
    zip_match = any(re.search(rf"\b{prefix}\d{{2}}\b", text) for prefix in MOCO_ZIP_PREFIXES)
    return state_match and (city_match or zip_match or "montgomery" in text)


def company_payload(company: dict | None, record: dict) -> dict:
    if company:
        return {
            "canonical_name": company.get("canonical_name"), "legal_name": company.get("legal_name") or company.get("canonical_name"),
            "uei": company.get("uei") or record.get("recipient_uei"), "ultimate_parent": company.get("ultimate_parent") or None,
            "hq_city": company.get("hq_city") or None, "hq_state": company.get("hq_state") or None,
            "hq_county": company.get("hq_county") or None, "hq_verified": bool(company.get("hq_verified")),
            "hq_status": company.get("hq_status") or "needs_review", "hq_confidence": float(company.get("hq_confidence") or 0),
        }
    possible = is_possible_moco_address(record.get("recipient_location"))
    return {
        "canonical_name": record.get("recipient_name") or "Unknown recipient", "legal_name": record.get("recipient_name"),
        "uei": record.get("recipient_uei"), "ultimate_parent": None, "hq_city": None, "hq_state": None,
        "hq_county": None, "hq_verified": False, "hq_status": "needs_review" if possible else "not_moco",
        "hq_confidence": 0.35 if possible else 0.0,
    }
