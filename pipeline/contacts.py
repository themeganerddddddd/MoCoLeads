from __future__ import annotations

from typing import Iterable

CONTACT_QUALITIES = {"high", "medium", "generic"}
QUALITY_RANK = {"generic": 1, "medium": 2, "high": 3}


def _first(*values):
    return next((value for value in values if value not in (None, "", [])), None)


def _source_name(url: str | None) -> str:
    if not url:
        return "Public source"
    if "gsaelibrary.gsa.gov" in url:
        return "GSA eLibrary"
    if "sam.gov" in url:
        return "SAM.gov"
    return "Company website"


def registry_company_contact(company: dict | None) -> dict | None:
    """Build a public company contact, including name-only SAM POCs."""
    if not company:
        return None
    source_url = company.get("contact_source")
    name = company.get("contact_name")
    title = company.get("contact_title")
    email = company.get("contact_email")
    phone = company.get("contact_phone")
    if not source_url or not any((name, title, email, phone)):
        return None
    return {
        "name": name or None,
        "title": title or None,
        "email": email or None,
        "phone": phone or None,
        "contact_type": company.get("contact_type") or "unknown",
        "contact_quality": company.get("contact_quality") or ("high" if "gsaelibrary.gsa.gov" in source_url else "medium"),
        "source_name": _source_name(source_url),
        "source_url": source_url,
        "verified_date": company.get("contact_verified_date") or None,
    }


def map_grants_contact(payload: dict, source_url: str | None = None) -> dict | None:
    data = payload.get("data") or payload
    synopsis = data.get("synopsis") or data.get("opportunity") or data
    name = _first(synopsis.get("agencyContactName"), synopsis.get("contactName"))
    email = _first(synopsis.get("agencyContactEmail"), synopsis.get("contactEmail"))
    phone = _first(synopsis.get("agencyContactPhone"), synopsis.get("contactPhone"))
    office = _first(synopsis.get("agencyName"), synopsis.get("owningAgencyName"), synopsis.get("agency"))
    url = source_url or synopsis.get("source_url") or synopsis.get("opportunityLink")
    if not url or not any((name, email, phone, office)):
        return None
    return {
        "name": name, "title": None, "email": email, "phone": phone, "office": office,
        "contact_type": "grant_program_contact", "contact_quality": "high",
        "source_name": "Grants.gov", "source_url": url, "verified_date": None,
    }


def map_assistance_contact(payload: dict, source_url: str | None = None) -> dict | None:
    data = payload.get("data") or payload
    contacts = data.get("contacts") or data.get("contact") or []
    if isinstance(contacts, dict):
        contacts = contacts.get("headquarters") or contacts.get("regional") or [contacts]
    if not isinstance(contacts, list):
        contacts = []
    contact = next((item for item in contacts if isinstance(item, dict)), data)
    name = _first(contact.get("fullName"), contact.get("name"), contact.get("contactName"))
    email = _first(contact.get("email"), contact.get("emailAddress"))
    phone = _first(contact.get("phone"), contact.get("phoneNumber"))
    office = _first(contact.get("department"), contact.get("organization"), data.get("federalOrganization"), data.get("agency"))
    url = source_url or data.get("source_url") or data.get("samUrl")
    if not url or not any((name, email, phone, office)):
        return None
    return {
        "name": name, "title": _first(contact.get("title"), contact.get("position")), "email": email,
        "phone": phone, "office": office, "contact_type": "federal_program_contact",
        "contact_quality": "high", "source_name": "SAM.gov Assistance Listings",
        "source_url": url, "verified_date": None,
    }


def _poc_rows(entity: dict) -> Iterable[tuple[str, dict]]:
    sections = entity.get("entityData") or entity
    points = sections.get("pointsOfContact") or sections.get("points_of_contact") or {}
    if isinstance(points, list):
        for row in points:
            if isinstance(row, dict):
                yield str(row.get("type") or row.get("contactType") or "point_of_contact"), row
        return
    if isinstance(points, dict):
        for key, value in points.items():
            if isinstance(value, list):
                for row in value:
                    if isinstance(row, dict):
                        yield key, row
            elif isinstance(value, dict):
                yield key, value


def map_sam_entity_contact(entity: dict, source_url: str) -> dict | None:
    """Map SAM Entity Management POC names/titles without exposing restricted fields."""
    priority = ("government business", "electronic business", "sales", "past performance")
    candidates = list(_poc_rows(entity))
    candidates.sort(key=lambda item: next((i for i, label in enumerate(priority) if label in item[0].replace("_", " ").casefold()), len(priority)))
    for kind, row in candidates:
        name = _first(row.get("fullName"), row.get("name"), " ".join(filter(None, [row.get("firstName"), row.get("middleInitial"), row.get("lastName")])).strip())
        title = _first(row.get("title"), row.get("position"))
        if not (name or title):
            continue
        # SAM marks email/phone fields as CUI in Entity Management. They are never copied.
        normalized_kind = kind.replace("PointOfContact", "").replace("_", " ").strip().casefold().replace(" ", "_")
        return {
            "name": name or None, "title": title or None, "email": None, "phone": None,
            "contact_type": normalized_kind or "sam_entity_point_of_contact",
            "contact_quality": "medium", "source_name": "SAM.gov Entity Management",
            "source_url": source_url, "verified_date": None,
        }
    return None


def federal_contact_payload(raw: dict) -> dict | None:
    if raw.get("grants_contact_payload"):
        return map_grants_contact(raw["grants_contact_payload"], raw.get("source_url"))
    if raw.get("assistance_contact_payload"):
        return map_assistance_contact(raw["assistance_contact_payload"], raw.get("source_url"))
    values = {
        "name": _first(raw.get("federal_contact_name"), raw.get("government_contact_name")),
        "title": raw.get("federal_contact_title"),
        "email": _first(raw.get("federal_contact_email"), raw.get("government_contact_email")),
        "phone": _first(raw.get("federal_contact_phone"), raw.get("government_contact_phone")),
        "office": _first(raw.get("federal_contact_office"), raw.get("government_contact_office")),
        "contact_type": raw.get("federal_contact_type") or "award_contact",
        "contact_quality": raw.get("federal_contact_quality") or "high",
        "source_name": _first(raw.get("federal_contact_source_name"), raw.get("government_contact_source_name")),
        "source_url": _first(raw.get("federal_contact_source_url"), raw.get("government_contact_source_url")),
        "verified_date": raw.get("federal_contact_verified_date"),
    }
    return values if any(values.get(field) for field in ("name", "email", "phone", "office")) else None


def choose_better_contact(existing: dict | None, incoming: dict | None) -> dict | None:
    if not incoming:
        return existing
    if not existing:
        return incoming
    existing_score = QUALITY_RANK.get(existing.get("contact_quality"), 0) * 10 + sum(bool(existing.get(k)) for k in ("name", "email", "phone"))
    incoming_score = QUALITY_RANK.get(incoming.get("contact_quality"), 0) * 10 + sum(bool(incoming.get(k)) for k in ("name", "email", "phone"))
    return incoming if incoming_score > existing_score else existing
