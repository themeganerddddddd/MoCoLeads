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
