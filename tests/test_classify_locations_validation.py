import pytest

from pipeline.classify import classify
from pipeline.locations import parse_work_locations
from pipeline.validation import ValidationError, validate_records


def test_contextual_defense_classification():
    record = {"award": {"agency": "Department of the Air Force", "description": "machine learning for sensor fusion", "subagency": None, "naics": None, "psc": None}}
    result = classify(record)
    assert result["primary"] == "Artificial Intelligence / Data"
    assert "Defense" in result["secondary"]


def test_naics_professional_services_classification():
    record = {"award": {"agency": "Department of Health and Human Services", "description": "Program evaluation", "subagency": None, "naics": "541611", "psc": "R410"}}
    assert classify(record)["primary"] == "Professional Services"


def test_multiple_locations():
    assert parse_work_locations("Dayton, Ohio; Huntsville, Alabama") == ["Dayton, Ohio", "Huntsville, Alabama"]


def test_validation_rejects_duplicate_ids():
    base = {"id": "same", "announcement_date": "2026-10-07", "action_date": None, "company": {"canonical_name": "Example", "hq_county": "Montgomery County"}, "award": {"amount": None}, "source": {"name": "Agency", "source_url": "https://agency.gov/a"}}
    with pytest.raises(ValidationError):
        validate_records([base, dict(base)])
