from __future__ import annotations

import csv
import importlib
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.classify import classify
from pipeline.company_matcher import company_payload, is_possible_moco_address, load_registry, match_company, moco_performance_evidence, location_text, qualify_record
from pipeline.contacts import choose_better_contact, map_sam_entity_contact, registry_company_contact
from pipeline.deduplicate import deduplicate
from pipeline.normalize import company_contact_payload, format_code, normalize_record
from pipeline.market import apply_market_relationship
from pipeline.validation import validate_records

COLLECTORS = ["war_contracts", "usaspending", "nasa", "diu", "darpa", "sbir", "sam"]


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def collect_all(companies: list[dict], performance_days: int = 7):
    raw, status, details = [], {}, {}
    lookback = max(7, int(os.getenv("MOCO_LOOKBACK_DAYS", "7")))
    for name in COLLECTORS:
        module = None
        label = "War.gov" if name == "war_contracts" else name.upper() if name in {"diu", "darpa", "sbir"} else name.title()
        try:
            module = importlib.import_module(f"collectors.{name}")
            found = module.collect(companies, days=lookback, performance_days=performance_days) if name == "usaspending" else module.collect(days=lookback)
            raw.extend(found)
            key = name.replace("_contracts", "")
            report = module.get_last_report() if hasattr(module, "get_last_report") else {}
            if report is not None:
                report.setdefault("records_retrieved", len(found))
                report["moco_matches"] = sum(1 for record in found if qualify_record(record, companies)[2])
            status[key] = report.get("status", "success")
            if report:
                details[key] = report
            print(f"{label}: {len(found)} raw records")
        except Exception as exc:
            key = name.replace("_contracts", "")
            status[key] = f"failed: {type(exc).__name__}: {exc}"
            if module is not None and hasattr(module, "get_last_report"):
                details[key] = module.get_last_report()
            print(f"ERROR {label}: {type(exc).__name__}: {exc}", file=sys.stderr)
    return raw, status, details


def write_candidates(raw: list[dict], companies: list[dict], path: Path):
    existing = {}
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                existing[(row.get("company"), row.get("award_url"))] = row
    today = datetime.now(timezone.utc).date().isoformat()
    for row in existing.values():
        company, _ = match_company({"recipient_name": row.get("company")}, companies)
        if company and company.get("hq_status") == "local_entity":
            row["suggested_status"] = "promoted_local_entity"
        elif company and company.get("hq_status") in {"needs_review", "not_moco"}:
            row["suggested_status"] = "needs_review"
    for record in raw:
        company, _, evidence = qualify_record(record, companies)
        if evidence and is_possible_moco_address(record.get("recipient_location")):
            key = (record.get("recipient_name") or "Unknown", record.get("source_url") or "")
            candidate = existing.setdefault(key, {
                "company": key[0], "recipient_address": location_text(record.get("recipient_location")), "first_seen": today,
                "award_source": record.get("source_name") or record.get("collector"), "award_url": key[1], "suggested_status": "local_entity",
            })
            if company and company.get("hq_status") == "local_entity":
                candidate["suggested_status"] = "promoted_local_entity"
    fields = ["company", "recipient_address", "first_seen", "award_source", "award_url", "suggested_status"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(existing.values())
    return len(existing)


def validate_historical_preservation(previous: list[dict], current: list[dict]) -> None:
    """Fail closed if a routine update would remove any published historical record."""
    previous_ids = {record.get("id") for record in previous if record.get("id")}
    current_ids = {record.get("id") for record in current if record.get("id")}
    missing = previous_ids - current_ids
    if missing:
        sample = ", ".join(sorted(missing)[:5])
        raise RuntimeError(f"historical preservation guard blocked removal of {len(missing)} record(s): {sample}")
    if len(current) < len(previous):
        raise RuntimeError(f"historical preservation guard blocked count drop from {len(previous)} to {len(current)}")


def enrich_historical_records(records: list[dict], companies: list[dict]) -> None:
    """Apply current entity qualification and public contact data without changing award history."""
    for record in records:
        raw = {
            "recipient_name": record.get("company", {}).get("legal_name") or record.get("company", {}).get("canonical_name"),
            "recipient_uei": record.get("company", {}).get("uei"),
            "recipient_location": record.get("location", {}).get("recipient_location"),
        }
        company, _, evidence = qualify_record(raw, companies)
        if company and evidence:
            record["company"] = {**record.get("company", {}), **company_payload(company, raw)}
        record.setdefault("contacts", {"company": None, "federal": None})
        record["contacts"]["federal"] = record["contacts"].get("federal") or record["contacts"].pop("government", None)
        contact = company_contact_payload(company) if company and evidence else None
        if contact:
            record["contacts"]["company"] = choose_better_contact(record["contacts"].get("company"), contact)
        apply_market_relationship(record)


def _iso_is_stale(value: str | None, refresh_days: int = 30) -> bool:
    try:
        return date.fromisoformat(str(value)[:10]) < date.today() - timedelta(days=refresh_days)
    except (TypeError, ValueError):
        return True


def _entity_uei(entity: dict) -> str | None:
    data = entity.get("entityData") or entity
    registration = data.get("entityRegistration") or data.get("entity_registration") or {}
    return (registration.get("ueiSAM") or registration.get("uei") or data.get("ueiSAM") or data.get("uei") or "").strip().upper() or None


def enrich_company_contacts(records: list[dict], companies: list[dict], retrieved_at: str) -> tuple[dict, dict]:
    """Refresh a company-level contact cache and attach it to every award for that entity."""
    cache_path = ROOT / "data" / "company_contacts.json"
    cache = load_json(cache_path, {"refresh_days": 30, "by_company_id": {}, "by_uei": {}})
    cache.setdefault("by_company_id", {})
    cache.setdefault("by_uei", {})
    registry_by_id = {row.get("company_id"): row for row in companies if row.get("company_id")}
    candidates: dict[str, dict] = {}
    for record in records:
        company = record.get("company") or {}
        company_id = company.get("company_id") or (record.get("match") or {}).get("registry_company_id")
        if not company_id:
            continue
        candidates.setdefault(company_id, company)
    for company_id, row in registry_by_id.items():
        candidates.setdefault(company_id, row)

    stale_ueis: list[str] = []
    for company_id, candidate in candidates.items():
        entry = cache["by_company_id"].setdefault(company_id, {
            "company_id": company_id,
            "uei": candidate.get("uei") or None,
            "company_name": candidate.get("canonical_name") or candidate.get("legal_name"),
            "company": None,
            "last_checked": None,
        })
        uei = str(candidate.get("uei") or entry.get("uei") or "").strip().upper() or None
        entry.update({"uei": uei, "company_name": candidate.get("canonical_name") or candidate.get("legal_name") or entry.get("company_name")})
        public_contact = registry_company_contact(registry_by_id.get(company_id))
        if public_contact:
            entry["company"] = choose_better_contact(entry.get("company"), public_contact)
            entry["last_checked"] = public_contact.get("verified_date") or retrieved_at[:10]
        if uei:
            cache["by_uei"][uei] = company_id
            if _iso_is_stale(entry.get("last_checked")) and (entry.get("company") or {}).get("contact_quality") != "high":
                stale_ueis.append(uei)

    sam_names = 0
    if stale_ueis and os.getenv("SAM_API_KEY"):
        try:
            sam_module = importlib.import_module("collectors.sam")
            for entity in sam_module.fetch_entities(stale_ueis):
                uei = _entity_uei(entity)
                company_id = cache["by_uei"].get(uei)
                if not company_id:
                    continue
                source_url = f"https://sam.gov/entity/{uei}/coreData?status=Active"
                contact = map_sam_entity_contact(entity, source_url)
                entry = cache["by_company_id"][company_id]
                entry["company"] = choose_better_contact(entry.get("company"), contact)
                entry["last_checked"] = retrieved_at[:10]
                sam_names += int(bool(contact and contact.get("name")))
        except Exception as exc:
            print(f"WARNING SAM contact enrichment failed: {type(exc).__name__}: {exc}", file=sys.stderr)

    for record in records:
        company_id = (record.get("company") or {}).get("company_id") or (record.get("match") or {}).get("registry_company_id")
        cached = (cache["by_company_id"].get(company_id) or {}).get("company")
        record.setdefault("contacts", {"company": None, "federal": None})
        if cached:
            record["contacts"]["company"] = choose_better_contact(record["contacts"].get("company"), cached)

    cache["updated_at"] = retrieved_at
    cache["refresh_days"] = 30
    cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    cached_contacts = [entry.get("company") for entry in cache["by_company_id"].values() if entry.get("company")]
    federal_contacts = [record.get("contacts", {}).get("federal") for record in records if record.get("contacts", {}).get("federal")]
    stats = {
        "companies_examined": len(candidates),
        "company_contacts_found": len(cached_contacts),
        "named_company_contacts": sum(bool(contact.get("name")) for contact in cached_contacts),
        "company_contacts_with_email": sum(bool(contact.get("email")) for contact in cached_contacts),
        "gsa_contacts": sum(contact.get("source_name") == "GSA eLibrary" for contact in cached_contacts),
        "generic_contacts": sum(contact.get("contact_quality") == "generic" for contact in cached_contacts),
        "sam_poc_names_found_this_run": sam_names,
        "federal_award_contacts": len(federal_contacts),
    }
    return cache, stats


def production_report(records: list[dict], previous_count: int, contact_stats: dict, retrieved_at: str) -> dict:
    moco_records = [r for r in records if r.get("recipient_in_moco")]
    work_records = [r for r in records if r.get("market_relationship") == "outside_company_working_in_moco"]
    active = Counter(r.get("company", {}).get("canonical_name") for r in work_records)
    dated = [r.get("action_date") or r.get("announcement_date") for r in work_records if r.get("action_date") or r.get("announcement_date")]
    largest = sorted(work_records, key=lambda r: float(r.get("award", {}).get("amount") or 0), reverse=True)[:10]
    return {
        "generated_at": retrieved_at,
        "contact_enrichment": contact_stats,
        "bootstrap": {
            "previous_archive_records": previous_count,
            "required_moco_record_floor": 470,
            "moco_company_records": len(moco_records),
            "moco_record_floor_passed": len(moco_records) >= 470,
            "outside_company_working_in_moco_records": len(work_records),
            "work_records_earliest_date": min(dated) if dated else None,
            "work_records_latest_date": max(dated) if dated else None,
            "largest_10": [{
                "company": r.get("company", {}).get("canonical_name"),
                "amount": r.get("award", {}).get("amount"),
                "date": r.get("action_date") or r.get("announcement_date"),
                "contract_number": r.get("award", {}).get("contract_number"),
            } for r in largest],
            "most_active_10": [{"company": name, "records": count} for name, count in active.most_common(10) if name],
        },
        "archive_preservation_passed": len(records) >= previous_count,
    }


def write_outputs(records: list[dict], status: dict, details: dict, companies: list[dict], retrieved_at: str, report: dict):
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    validate_records(records)
    json_text = json.dumps(records, indent=2, ensure_ascii=False) + "\n"
    (data_dir / "contracts.json").write_text(json_text, encoding="utf-8")
    (data_dir / "latest.json").write_text(json.dumps(records[:25], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (data_dir / "companies.json").write_text(json.dumps(companies, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    fields = ["id", "announcement_date", "action_date", "company", "company_location", "hq_city", "hq_status", "market_relationship", "recipient_in_moco", "performance_in_moco", "amount", "agency", "subagency", "category", "description", "work_location", "contract_number", "award_id", "source", "source_url"]
    with (data_dir / "contracts.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n"); writer.writeheader()
        for r in records:
            writer.writerow({
                "id": r["id"], "announcement_date": r.get("announcement_date"), "action_date": r.get("action_date"),
                "company": r["company"]["canonical_name"], "company_location": r["location"].get("recipient_location"), "hq_city": r["company"].get("hq_city"), "hq_status": r["company"].get("hq_status"),
                "market_relationship": r.get("market_relationship"), "recipient_in_moco": r.get("recipient_in_moco"), "performance_in_moco": r.get("performance_in_moco"),
                "amount": r["award"].get("amount"), "agency": r["award"].get("agency"), "subagency": r["award"].get("subagency"),
                "category": r["classification"].get("primary"), "description": r["award"].get("description"),
                "work_location": r["location"].get("place_of_performance"), "contract_number": r["award"].get("contract_number"),
                "award_id": r["award"].get("award_id"), "source": r["source"].get("name"), "source_url": r["source"].get("source_url"),
            })
    metadata = {"last_updated": retrieved_at, "sources_checked": ["War.gov", "USAspending", "NASA", "DIU", "DARPA", "SBIR", "SAM.gov"], "collector_status": status, "collector_details": details, "record_count": len(records), "market_counts": dict(Counter(r.get("market_relationship") for r in records)), "contact_stats": report["contact_enrichment"], "disclosed_value_note": "Totals include disclosed amounts only."}
    (data_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (data_dir / "production_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    companies = load_registry(ROOT / "companies" / "moco_companies.csv")
    historical = load_json(ROOT / "data" / "contracts.json", [])
    has_work_archive = any(record.get("market_relationship") == "outside_company_working_in_moco" for record in historical)
    performance_days = max(7, int(os.getenv("MOCO_POP_BOOTSTRAP_DAYS", "7" if has_work_archive else "365")))
    raw, status, details = collect_all(companies, performance_days=performance_days)
    candidates = write_candidates(raw, companies, ROOT / "data" / "company_candidates.csv")
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    normalized = []
    matched = 0
    provisional = 0
    outside_matched = 0
    for item in raw:
        company, _, evidence = qualify_record(item, companies)
        performance_evidence = moco_performance_evidence(item.get("place_of_performance"))
        if evidence or performance_evidence:
            matched += 1
            if not company:
                provisional += 1
            record = normalize_record(item, companies, retrieved_at)
            outside_matched += int(record.get("market_relationship") == "outside_company_working_in_moco")
            normalized.append(record)
    enrich_historical_records(historical, companies)
    combined, merged = deduplicate(historical + normalized)
    for record in combined:
        record["award"]["naics"] = format_code(record["award"].get("naics"))
        record["award"]["psc"] = format_code(record["award"].get("psc"))
        record["classification"] = classify(record)
        apply_market_relationship(record)
    combined.sort(key=lambda r: (r.get("announcement_date") or r.get("action_date") or "", r.get("id", "")), reverse=True)
    validate_historical_preservation(historical, combined)
    _, contact_stats = enrich_company_contacts(combined, companies, retrieved_at)
    report = production_report(combined, len(historical), contact_stats, retrieved_at)
    write_outputs(combined, status, details, companies, retrieved_at, report)
    print(f"Qualified Montgomery County records: {matched}")
    print(f"Provisional local entities: {provisional}")
    print(f"New possible MoCo companies: {candidates}")
    print(f"Duplicates merged: {merged}")
    print(f"New dashboard records: {max(0, len(combined) - len(historical))}")
    print(f"Outside companies working in Montgomery County this collection: {outside_matched}")
    print(f"Total outside-company work records: {report['bootstrap']['outside_company_working_in_moco_records']}")


if __name__ == "__main__":
    main()
