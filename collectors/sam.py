from __future__ import annotations

import os

from .common import get

ENTITY_URL = "https://api.sam.gov/entity-information/v3/entities"
LAST_REPORT: dict = {}


def fetch_entities(ueis: list[str], api_key: str | None = None) -> list[dict]:
    """Fetch public entity registration/POC sections without logging the API key."""
    key = api_key or os.getenv("SAM_API_KEY")
    if not key:
        return []
    entities: list[dict] = []
    unique = list(dict.fromkeys(str(uei).strip().upper() for uei in ueis if uei))
    max_requests = max(1, int(os.getenv("MOCO_SAM_MAX_REQUESTS", "10")))
    for offset in range(0, min(len(unique), max_requests * 10), 10):
        batch = unique[offset:offset + 10]
        response = get(
            ENTITY_URL,
            params={"ueiSAM": "~".join(batch), "includeSections": "entityRegistration,pointsOfContact", "page": 0, "size": 10},
            headers={"X-Api-Key": key, "Accept": "application/json", "Content-Type": "application/json"},
        )
        payload = response.json()
        entities.extend(payload.get("entityData") or payload.get("results") or [])
    return entities


def collect(days=7):
    if not os.getenv("SAM_API_KEY"):
        print("SAM.gov: SAM_API_KEY is not set; optional enrichment skipped")
        LAST_REPORT.clear(); LAST_REPORT.update({"status": "skipped", "reason": "SAM_API_KEY not set", "records_retrieved": 0})
        return []
    print("SAM.gov: key detected; public entity contact enrichment enabled")
    LAST_REPORT.clear(); LAST_REPORT.update({"status": "success", "records_retrieved": 0, "mode": "entity_contact_enrichment"})
    return []


def get_last_report() -> dict:
    return dict(LAST_REPORT)
