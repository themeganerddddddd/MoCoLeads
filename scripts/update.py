from __future__ import annotations

import csv
import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.classify import classify
from pipeline.company_matcher import company_payload, is_possible_moco_address, load_registry, match_company, location_text, qualify_record
from pipeline.deduplicate import deduplicate
from pipeline.normalize import company_contact_payload, format_code, normalize_record
from pipeline.validation import validate_records

COLLECTORS = ["war_contracts", "usaspending", "nasa", "diu", "darpa", "sbir", "sam"]


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def collect_all(companies: list[dict]):
    raw, status, details = [], {}, {}
    lookback = max(7, int(os.getenv("MOCO_LOOKBACK_DAYS", "7")))
    for name in COLLECTORS:
        module = None
        label = "War.gov" if name == "war_contracts" else name.upper() if name in {"diu", "darpa", "sbir"} else name.title()
        try:
            module = importlib.import_module(f"collectors.{name}")
            found = module.collect(companies, days=lookback) if name == "usaspending" else module.collect(days=lookback)
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
        if not company or not evidence:
            continue
        record["company"] = {**record.get("company", {}), **company_payload(company, raw)}
        record.setdefault("contacts", {"company": None, "government": None})
        contact = company_contact_payload(company)
        if contact:
            record["contacts"]["company"] = contact


def write_outputs(records: list[dict], status: dict, details: dict, companies: list[dict], retrieved_at: str):
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    validate_records(records)
    json_text = json.dumps(records, indent=2, ensure_ascii=False) + "\n"
    (data_dir / "contracts.json").write_text(json_text, encoding="utf-8")
    (data_dir / "latest.json").write_text(json.dumps(records[:25], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (data_dir / "companies.json").write_text(json.dumps(companies, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    fields = ["id", "announcement_date", "action_date", "company", "hq_city", "hq_status", "amount", "agency", "subagency", "category", "description", "work_location", "contract_number", "award_id", "source", "source_url"]
    with (data_dir / "contracts.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n"); writer.writeheader()
        for r in records:
            writer.writerow({
                "id": r["id"], "announcement_date": r.get("announcement_date"), "action_date": r.get("action_date"),
                "company": r["company"]["canonical_name"], "hq_city": r["company"].get("hq_city"), "hq_status": r["company"].get("hq_status"),
                "amount": r["award"].get("amount"), "agency": r["award"].get("agency"), "subagency": r["award"].get("subagency"),
                "category": r["classification"].get("primary"), "description": r["award"].get("description"),
                "work_location": r["location"].get("place_of_performance"), "contract_number": r["award"].get("contract_number"),
                "award_id": r["award"].get("award_id"), "source": r["source"].get("name"), "source_url": r["source"].get("source_url"),
            })
    metadata = {"last_updated": retrieved_at, "sources_checked": ["War.gov", "USAspending", "NASA", "DIU", "DARPA", "SBIR", "SAM.gov"], "collector_status": status, "collector_details": details, "record_count": len(records), "disclosed_value_note": "Totals include disclosed amounts only."}
    (data_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def main():
    companies = load_registry(ROOT / "companies" / "moco_companies.csv")
    raw, status, details = collect_all(companies)
    candidates = write_candidates(raw, companies, ROOT / "data" / "company_candidates.csv")
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    normalized = []
    matched = 0
    provisional = 0
    for item in raw:
        company, _, evidence = qualify_record(item, companies)
        if evidence:
            matched += 1
            if not company:
                provisional += 1
            normalized.append(normalize_record(item, companies, retrieved_at))
    historical = load_json(ROOT / "data" / "contracts.json", [])
    enrich_historical_records(historical, companies)
    combined, merged = deduplicate(historical + normalized)
    for record in combined:
        record["award"]["naics"] = format_code(record["award"].get("naics"))
        record["award"]["psc"] = format_code(record["award"].get("psc"))
        record["classification"] = classify(record)
    combined.sort(key=lambda r: (r.get("announcement_date") or r.get("action_date") or "", r.get("id", "")), reverse=True)
    validate_historical_preservation(historical, combined)
    write_outputs(combined, status, details, companies, retrieved_at)
    print(f"Qualified Montgomery County records: {matched}")
    print(f"Provisional local entities: {provisional}")
    print(f"New possible MoCo companies: {candidates}")
    print(f"Duplicates merged: {merged}")
    print(f"New dashboard records: {max(0, len(combined) - len(historical))}")


if __name__ == "__main__":
    main()
