from pathlib import Path

from pipeline.company_matcher import (
    is_possible_moco_address,
    load_registry,
    match_company,
    moco_recipient_evidence,
    normalize_name,
    qualify_record,
)


REGISTRY = Path(__file__).parents[1] / "companies" / "moco_companies.csv"


def test_company_alias_normalization_ignores_punctuation_and_suffixes():
    assert normalize_name("LOCKHEED-MARTIN Corp.") == normalize_name("Lockheed Martin Corporation")


def test_uei_precedes_name_matching():
    companies = [{"company_id": "x", "canonical_name": "Example", "legal_name": "Example LLC", "aliases_list": [], "uei": "ABC123"}]
    company, method = match_company({"recipient_name": "Wrong Name", "recipient_uei": "abc123"}, companies)
    assert company["company_id"] == "x"
    assert method == "uei"


def test_montgomery_county_address_is_qualified_local_entity_evidence():
    assert is_possible_moco_address("123 Main Street, Rockville, MD 20850")
    assert not is_possible_moco_address("123 Main Street, Arlington, VA 22201")


def test_recipient_county_and_fips_evidence_is_recognized():
    county = moco_recipient_evidence({"state_code": "MD", "county_code": "031", "city_name": "Unknown"})
    full_fips = moco_recipient_evidence({"state": "24", "location_fips": "24031"})
    assert county["basis"] == "federal_recipient_address"
    assert county["confidence"] == 0.95
    assert full_fips["basis"] == "federal_recipient_address"


def test_place_of_performance_never_qualifies_unknown_recipient():
    company, method, evidence = qualify_record(
        {
            "recipient_name": "Unknown Virginia Company",
            "recipient_location": "Arlington, VA",
            "place_of_performance": "Rockville, MD",
        },
        [],
    )
    assert company is None
    assert method is None
    assert evidence is None


def test_bae_rockville_entities_are_local_and_amentum_is_not_moco():
    companies = load_registry(REGISTRY)
    bae_tss, _, bae_evidence = qualify_record(
        {"recipient_name": "BAE Systems Technology Solutions and Services Inc."}, companies
    )
    bae_inc, _, bae_inc_evidence = qualify_record({"recipient_name": "BAE Systems Inc."}, companies)
    amentum, method, amentum_evidence = qualify_record(
        {"recipient_name": "Amentum Services Inc.", "recipient_location": "Germantown, Maryland"}, companies
    )
    assert bae_tss["company_id"] == "bae-systems-tss"
    assert bae_tss["ultimate_parent"] == "BAE Systems plc"
    assert bae_evidence["basis"] == "verified_local_legal_entity"
    assert bae_inc["company_id"] == "bae-systems-inc-rockville"
    assert bae_inc_evidence["basis"] == "verified_local_legal_entity"
    assert amentum["hq_status"] == "not_moco"
    assert method == "registry_conflict"
    assert amentum_evidence is None
