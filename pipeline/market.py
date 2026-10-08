from __future__ import annotations

from .company_matcher import QUALIFYING_STATUSES, moco_performance_evidence, moco_recipient_evidence

RELATIONSHIPS = {
    "moco_company",
    "outside_company_working_in_moco",
    "moco_company_working_in_moco",
    "neither",
}


def classify_market_relationship(record: dict) -> dict:
    """Classify recipient and performance geography independently."""
    company = record.get("company") or {}
    location = record.get("location") or {}
    recipient_in_moco = company.get("hq_status") in QUALIFYING_STATUSES or bool(
        location.get("recipient_moco_evidence") or moco_recipient_evidence(location.get("recipient_location"))
    )
    performance_in_moco = bool(
        location.get("performance_moco_evidence") or moco_performance_evidence(location.get("place_of_performance"))
    )
    if recipient_in_moco and performance_in_moco:
        relationship = "moco_company_working_in_moco"
    elif recipient_in_moco:
        relationship = "moco_company"
    elif performance_in_moco:
        relationship = "outside_company_working_in_moco"
    else:
        relationship = "neither"
    return {
        "market_relationship": relationship,
        "recipient_in_moco": recipient_in_moco,
        "performance_in_moco": performance_in_moco,
    }


def apply_market_relationship(record: dict) -> dict:
    record.update(classify_market_relationship(record))
    return record
