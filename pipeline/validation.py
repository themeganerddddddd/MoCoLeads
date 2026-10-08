from __future__ import annotations

from datetime import date
from urllib.parse import urlparse


class ValidationError(ValueError):
    pass


def validate_records(records: list[dict]) -> None:
    errors: list[str] = []
    ids: set[str] = set()
    strong_keys: set[tuple] = set()
    for index, record in enumerate(records):
        prefix = f"record {index}"
        rid = record.get("id")
        if not rid or rid in ids:
            errors.append(f"{prefix}: missing or duplicate id")
        ids.add(rid)
        for field in ("announcement_date", "action_date"):
            if record.get(field):
                try:
                    date.fromisoformat(record[field])
                except (ValueError, TypeError):
                    errors.append(f"{prefix}: invalid {field}")
        if not record.get("company", {}).get("canonical_name"):
            errors.append(f"{prefix}: company name required")
        amount = record.get("award", {}).get("amount")
        if amount is not None and (isinstance(amount, bool) or not isinstance(amount, (int, float))):
            errors.append(f"{prefix}: amount must be numeric or null")
        source = record.get("source", {})
        url = source.get("source_url")
        if not source.get("name") or not url or urlparse(url).scheme not in {"http", "https"}:
            errors.append(f"{prefix}: valid source required")
        county = record.get("company", {}).get("hq_county")
        if county and county != "Montgomery County":
            errors.append(f"{prefix}: invalid HQ county")
        company_data = record.get("company", {})
        if company_data.get("hq_status") == "local_entity" and not company_data.get("moco_basis"):
            errors.append(f"{prefix}: local entity requires Montgomery County basis")
        contacts = record.get("contacts") or {}
        for contact_kind in ("company", "government"):
            contact = contacts.get(contact_kind)
            if not contact:
                continue
            if (contact.get("email") or contact.get("phone")) and (
                not contact.get("source_name") or not contact.get("source_url")
                or urlparse(contact.get("source_url")).scheme not in {"http", "https"}
            ):
                errors.append(f"{prefix}: {contact_kind} contact requires public source provenance")
        award = record.get("award", {})
        key = (str(award.get("contract_number") or "").upper(), str(award.get("award_id") or "").upper())
        if key != ("", "") and key in strong_keys:
            errors.append(f"{prefix}: obvious duplicate contract identifier")
        strong_keys.add(key)
    if errors:
        raise ValidationError("\n".join(errors[:20]))
