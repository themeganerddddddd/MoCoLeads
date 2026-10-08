from __future__ import annotations

from copy import deepcopy
from difflib import SequenceMatcher

from .company_matcher import normalize_name
from .contacts import choose_better_contact


def _same(a: dict, b: dict) -> bool:
    aa, ba = a["award"], b["award"]
    for field in ("contract_number", "award_id"):
        av, bv = aa.get(field), ba.get(field)
        if av and bv and str(av).upper() == str(bv).upper():
            return True
    ac, bc = a["company"], b["company"]
    if ac.get("uei") and bc.get("uei") and ac["uei"] == bc["uei"] and aa.get("amount") == ba.get("amount") and a.get("action_date") == b.get("action_date"):
        return True
    same_name = normalize_name(ac.get("canonical_name")) == normalize_name(bc.get("canonical_name"))
    same_amount = aa.get("amount") is not None and aa.get("amount") == ba.get("amount")
    same_date = a.get("announcement_date") == b.get("announcement_date") or a.get("action_date") == b.get("action_date")
    if same_name and same_amount and same_date:
        return True
    if same_name and same_amount and SequenceMatcher(None, aa.get("description", ""), ba.get("description", "")).ratio() > 0.82:
        return True
    return False


def _merge_value(old, new):
    return old if old not in (None, "", [], "Not disclosed") else new


def merge_records(base: dict, incoming: dict) -> dict:
    result = deepcopy(base)
    announcement = next((r for r in (base, incoming) if r.get("source", {}).get("source_type") == "announcement"), None)
    structured = next((r for r in (base, incoming) if r.get("source", {}).get("source_type") == "structured_award"), None)
    for section in ("company", "award", "location"):
        for key, value in incoming.get(section, {}).items():
            result[section][key] = _merge_value(result[section].get(key), value)
    result.setdefault("contacts", {"company": None, "federal": None})
    result["contacts"]["federal"] = result["contacts"].get("federal") or result["contacts"].pop("government", None)
    incoming_contacts = incoming.get("contacts", {})
    incoming_federal = incoming_contacts.get("federal") or incoming_contacts.get("government")
    for kind, incoming_contact in (("company", incoming_contacts.get("company")), ("federal", incoming_federal)):
        existing_contact = result["contacts"].get(kind)
        result["contacts"][kind] = deepcopy(choose_better_contact(existing_contact, incoming_contact))
    if structured:
        for key in ("award_id", "naics", "psc", "contract_number", "subagency"):
            result["award"][key] = _merge_value(structured["award"].get(key), result["award"].get(key))
    if announcement:
        for key in (
            "amount", "amount_display", "description", "raw_description", "expected_completion",
            "expected_completion_date", "award_date", "action_type", "contract_type", "modification_number",
            "ceiling_value", "obligated_amount", "funds_obligated", "cumulative_value",
            "previous_cumulative_value", "contracting_activity", "funding",
        ):
            result["award"][key] = _merge_value(announcement["award"].get(key), result["award"].get(key))
        if announcement["location"].get("work_locations"):
            result["location"]["work_locations"] = announcement["location"]["work_locations"]
            result["location"]["place_of_performance"] = announcement["location"].get("place_of_performance")
        result["source"] = announcement["source"].copy()
        if announcement.get("retrieval"):
            result["retrieval"] = deepcopy(announcement["retrieval"])
    all_sources = base.get("sources", [base.get("source")]) + incoming.get("sources", [incoming.get("source")])
    result["sources"] = list({(s.get("name"), s.get("source_url")): s for s in all_sources if s and s.get("source_url")}.values())
    primary_key = (result["source"].get("name"), result["source"].get("source_url"))
    for source in result["sources"]:
        source["primary"] = (source.get("name"), source.get("source_url")) == primary_key
    return result


def deduplicate(records: list[dict]) -> tuple[list[dict], int]:
    output: list[dict] = []
    merged = 0
    strong_index: dict[tuple[str, str], set[int]] = {}
    uei_index: dict[tuple, set[int]] = {}
    dated_index: dict[tuple, set[int]] = {}
    fuzzy_index: dict[tuple, set[int]] = {}

    def add_indexes(record: dict, index: int) -> None:
        award, company = record["award"], record["company"]
        for field in ("contract_number", "award_id"):
            value = str(award.get(field) or "").upper()
            if value:
                strong_index.setdefault((field, value), set()).add(index)
        uei = str(company.get("uei") or "").upper()
        if uei:
            uei_index.setdefault((uei, award.get("amount"), record.get("action_date")), set()).add(index)
        name = normalize_name(company.get("canonical_name"))
        amount = award.get("amount")
        if name and amount is not None:
            fuzzy_index.setdefault((name, amount), set()).add(index)
            for value_date in {record.get("announcement_date"), record.get("action_date")}:
                dated_index.setdefault((name, amount, value_date), set()).add(index)

    def candidate_indexes(record: dict) -> set[int]:
        award, company = record["award"], record["company"]
        candidates: set[int] = set()
        for field in ("contract_number", "award_id"):
            value = str(award.get(field) or "").upper()
            candidates.update(strong_index.get((field, value), set()))
        uei = str(company.get("uei") or "").upper()
        candidates.update(uei_index.get((uei, award.get("amount"), record.get("action_date")), set()))
        name = normalize_name(company.get("canonical_name"))
        amount = award.get("amount")
        for value_date in {record.get("announcement_date"), record.get("action_date")}:
            candidates.update(dated_index.get((name, amount, value_date), set()))
        candidates.update(fuzzy_index.get((name, amount), set()))
        return candidates

    for record in records:
        existing_index = next((index for index in candidate_indexes(record) if _same(output[index], record)), None)
        if existing_index is not None:
            output[existing_index] = merge_records(output[existing_index], record)
            add_indexes(output[existing_index], existing_index)
            merged += 1
        else:
            output.append(deepcopy(record))
            add_indexes(output[-1], len(output) - 1)
    return output, merged
