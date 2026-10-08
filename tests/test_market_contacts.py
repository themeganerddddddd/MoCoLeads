from pipeline.contacts import map_assistance_contact, map_grants_contact, map_sam_entity_contact
from pipeline.market import classify_market_relationship


def record(company_status, recipient, performance):
    return {
        "company": {"hq_status": company_status},
        "location": {"recipient_location": recipient, "place_of_performance": performance},
    }


def test_all_four_market_relationship_cases_are_distinct():
    moco = "Rockville, MD"
    outside = "Arlington, VA"
    assert classify_market_relationship(record("verified", moco, outside))["market_relationship"] == "moco_company"
    assert classify_market_relationship(record("not_moco", outside, moco))["market_relationship"] == "outside_company_working_in_moco"
    assert classify_market_relationship(record("verified", moco, moco))["market_relationship"] == "moco_company_working_in_moco"
    assert classify_market_relationship(record("not_moco", outside, outside))["market_relationship"] == "neither"


def test_structured_performance_evidence_survives_display_formatting():
    result = classify_market_relationship({
        "company": {"hq_status": "not_moco"},
        "location": {
            "recipient_location": "McLean, VA",
            "place_of_performance": "MD",
            "performance_moco_evidence": {"basis": "federal_place_of_performance", "confidence": 0.95},
        },
    })
    assert result["market_relationship"] == "outside_company_working_in_moco"


def test_grants_and_assistance_contacts_map_to_federal_provenance():
    grant = map_grants_contact({"data": {"synopsis": {
        "agencyContactName": "Grant Officer", "agencyContactEmail": "grants@example.gov", "agencyName": "Agency",
    }}}, "https://grants.gov/example")
    assistance = map_assistance_contact({
        "federalOrganization": "Agency", "contacts": {"headquarters": [{"fullName": "Program Lead", "phone": "202-555-0100"}]},
    }, "https://sam.gov/assistance/example")
    assert grant["contact_type"] == "grant_program_contact"
    assert grant["source_name"] == "Grants.gov"
    assert assistance["contact_type"] == "federal_program_contact"
    assert assistance["source_url"] == "https://sam.gov/assistance/example"


def test_sam_entity_poc_never_exposes_email_or_phone():
    contact = map_sam_entity_contact({"pointsOfContact": {"governmentBusinessPOC": {
        "firstName": "Public", "lastName": "Official", "title": "Contracts Director",
        "email": "restricted@example.com", "phone": "301-555-0199",
    }}}, "https://sam.gov/entity/ABC/coreData")
    assert contact["name"] == "Public Official"
    assert contact["title"] == "Contracts Director"
    assert contact["email"] is None
    assert contact["phone"] is None
    assert contact["contact_quality"] == "medium"
    assert contact["source_url"].startswith("https://sam.gov/")
