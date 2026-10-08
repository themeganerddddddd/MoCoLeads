from pipeline.normalize import normalize_record, parse_numeric_amount


COMPANY = {
    "company_id": "example", "canonical_name": "Example Technologies", "legal_name": "Example Technologies Inc.",
    "aliases_list": ["Example Tech"], "uei": "", "ultimate_parent": "", "hq_city": "Rockville", "hq_state": "MD",
    "hq_county": "Montgomery County", "hq_verified": True, "hq_status": "verified", "hq_confidence": 1,
}


def test_amount_parsing_and_null():
    assert parse_numeric_amount("$4.2M") == 4_200_000
    assert parse_numeric_amount("875,000") == 875_000
    assert parse_numeric_amount(None) is None
    assert parse_numeric_amount("not disclosed") is None


def test_normalization_preserves_source_url_and_nulls():
    url = "https://example.gov/announcement/123"
    record = normalize_record({"recipient_name": "Example Tech", "amount": None, "source_name": "Agency", "source_url": url, "description": "Software support", "announcement_date": "2026-10-07"}, [COMPANY], "2026-10-07T12:00:00Z")
    assert record["source"]["source_url"] == url
    assert record["sources"][0]["source_url"] == url
    assert record["award"]["amount"] is None
    assert record["location"]["place_of_performance"] is None


def test_unknown_official_moco_recipient_is_visible_local_entity():
    record = normalize_record({
        "recipient_name": "New Montgomery Vendor LLC",
        "recipient_location": {"city_name": "Rockville", "state_code": "MD", "county_code": "031"},
        "amount": 1000,
        "source_name": "USAspending",
        "source_url": "https://www.usaspending.gov/award/example/",
        "action_date": "2026-10-07",
    }, [], "2026-10-08T12:00:00Z")
    assert record["company"]["hq_status"] == "local_entity"
    assert record["company"]["moco_basis"] == "federal_recipient_address"
    assert record["company"]["moco_confidence"] == 0.95
    assert record["match"]["method"] == "federal_recipient_address"


def test_company_and_federal_contacts_remain_separate_and_provenanced():
    company = {
        **COMPANY,
        "contact_name": "Contract Sales",
        "contact_email": "sales@example.com",
        "contact_phone": "301-555-0100",
        "contact_type": "federal_contracting",
        "contact_source": "https://www.gsaelibrary.gsa.gov/example",
        "contact_verified_date": "2026-10-08",
    }
    record = normalize_record({
        "recipient_name": "Example Tech",
        "source_name": "Agency",
        "source_url": "https://agency.gov/award",
        "announcement_date": "2026-10-08",
        "government_contact_name": "Jane Contracting Officer",
        "government_contact_email": "jane@agency.gov",
        "government_contact_office": "Acquisition Office",
        "government_contact_source_name": "Agency announcement",
        "government_contact_source_url": "https://agency.gov/award",
    }, [company], "2026-10-08T12:00:00Z")
    assert record["contacts"]["company"]["email"] == "sales@example.com"
    assert record["contacts"]["company"]["source_name"] == "GSA eLibrary"
    assert record["contacts"]["federal"]["email"] == "jane@agency.gov"
    assert record["contacts"]["federal"]["source_name"] == "Agency announcement"
