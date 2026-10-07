from pathlib import Path

from collectors.war_contracts import (
    OCT_6_FIXTURE_URL,
    discover_announcements,
    parse_article,
    parse_contract_date,
    parse_contract_paragraph,
    split_article_into_award_units,
)
from pipeline.deduplicate import deduplicate
from pipeline.normalize import normalize_record

FIXTURES = Path(__file__).parent / "fixtures"
OCT_6_HTML = (FIXTURES / "war_oct_6_2026.html").read_text(encoding="utf-8")
INDEX_HTML = (FIXTURES / "war_contracts_index.html").read_text(encoding="utf-8")


def oct_6_records():
    return parse_article(OCT_6_HTML, OCT_6_FIXTURE_URL, "2026-10-06", "Contracts for Oct. 6, 2026")


def by_company(name):
    return next(record for record in oct_6_records() if record["company_name"] == name)


def test_contract_index_link_discovery():
    records = discover_announcements(INDEX_HTML)
    assert len(records) == 2
    assert records[0] == {
        "title": "Contracts for Oct. 6, 2026",
        "announcement_date": "2026-10-06",
        "url": OCT_6_FIXTURE_URL,
    }


def test_announcement_date_from_title():
    assert parse_contract_date("Contracts for Oct. 6, 2026") == "2026-10-06"
    assert parse_contract_date("Contracts for September 29, 2026") == "2026-09-29"
    assert parse_contract_date("Not a contract title") is None


def test_service_heading_assignment():
    paragraph = "Acme Systems LLC, Huntsville, Alabama, was awarded a $42,500,000 contract for radar integration."
    html = f"<article><h2>ARMY</h2><p>{paragraph}</p><h2>NAVY</h2><p>{paragraph}</p></article>"
    units = split_article_into_award_units(html, {"announcement_date": "2026-10-06", "url": OCT_6_FIXTURE_URL})
    assert [unit["service"] for unit in units] == ["Army", "Navy"]


def test_standard_award():
    text = "Example Technologies Inc., Rockville, Maryland, was awarded a $42,500,000 contract for artificial intelligence integration. Work will be performed in Dayton, Ohio, and is expected to be completed by Oct. 7, 2028. The 99th Contracting Squadron, Nellis AFB, Nevada, is the contracting activity (FA0000-26-C-0001)."
    record = parse_contract_paragraph(text, source_url=OCT_6_FIXTURE_URL, announcement_date="2026-10-06", agency="Air Force")
    assert record["company_name"] == "Example Technologies Inc."
    assert record["announced_contractor_location"] == "Rockville, Maryland"
    assert record["award_amount"] == 42_500_000
    assert record["description"] == "artificial intelligence integration"


def test_idiq_ceiling_vs_obligation():
    weldin = by_company("Weldin Construction LLC")
    assert weldin["award_amount"] == 185_000_000
    assert weldin["ceiling_value"] == 185_000_000
    assert weldin["obligated_amount"] == 2_089_542
    assert weldin["contract_type"] == "IDIQ"


def test_modification():
    aegis = by_company("Aegis Aerospace Inc.")
    assert aegis["action_type"] == "Modification"
    assert aegis["award_amount"] == 9_359_118
    assert aegis["modification_number"] == "P00001"


def test_modification_vs_contract_number():
    aegis = by_company("Aegis Aerospace Inc.")
    assert aegis["modification_number"] == "P00001"
    assert aegis["contract_number"] == "FA8809-26-F-B003"


def test_cumulative_contract_value():
    aegis = by_company("Aegis Aerospace Inc.")
    assert aegis["previous_cumulative_value"] == 24_964_741
    assert aegis["cumulative_value"] == 34_323_859


def test_multiple_work_locations():
    weldin = by_company("Weldin Construction LLC")
    assert weldin["work_locations"] == [
        "Nellis Air Force Base",
        "Creech AFB",
        "Nevada Test and Training Range",
    ]


def test_completion_date():
    weldin = by_company("Weldin Construction LLC")
    assert weldin["expected_completion_date"] == "2031-09-29"
    collins = by_company("Collins Aerospace")
    assert collins["expected_completion_date"] is None
    assert collins["expected_completion_text"] == "September 2036"


def test_funding_amount():
    weldin = by_company("Weldin Construction LLC")
    assert weldin["funding"] == [{"fiscal_year": 2026, "type": "operations and maintenance", "amount": 2_089_542}]


def test_contracting_activity():
    weldin = by_company("Weldin Construction LLC")
    assert weldin["contracting_activity"] == "99th Contracting Squadron, Nellis AFB, Nevada"


def test_explicit_award_date():
    assert by_company("Weldin Construction LLC")["award_date"] == "2026-09-30"
    assert by_company("Aegis Aerospace Inc.")["award_date"] is None


def test_announcement_date_preserved():
    assert all(record["announcement_date"] == "2026-10-06" for record in oct_6_records())
    assert by_company("Weldin Construction LLC")["action_date"] == "2026-09-30"


def test_source_url_preserved():
    assert all(record["source_url"] == OCT_6_FIXTURE_URL for record in oct_6_records())


def test_multiple_awards_one_article():
    records = oct_6_records()
    assert len(records) == 3
    assert {record["company_name"] for record in records} == {"Weldin Construction LLC", "Aegis Aerospace Inc.", "Collins Aerospace"}
    assert all(record["service"] == "Air Force" for record in records)


def test_war_record_usaspending_merge():
    company = {
        "company_id": "aegis", "canonical_name": "Aegis Aerospace", "legal_name": "Aegis Aerospace Inc.",
        "aliases_list": ["Aegis Aerospace Inc."], "uei": "UEI123", "ultimate_parent": "", "hq_city": "Rockville",
        "hq_state": "MD", "hq_county": "Montgomery County", "hq_verified": True, "hq_status": "verified",
        "hq_confidence": 1.0,
    }
    war = normalize_record(by_company("Aegis Aerospace Inc."), [company], "2026-10-07T12:00:00Z")
    usa = normalize_record({
        "recipient_name": "Aegis Aerospace Inc.", "recipient_uei": "UEI123", "amount": 1,
        "announcement_date": "2026-10-06", "action_date": "2026-10-06", "contract_number": "FA8809-26-F-B003",
        "award_id": "FA8809-26-F-B003", "description": "Structured transaction", "source_name": "USAspending",
        "source_type": "structured_award", "source_url": "https://www.usaspending.gov/award/example/",
    }, [company], "2026-10-07T12:00:00Z")
    merged, count = deduplicate([usa, war])
    assert count == 1
    assert merged[0]["award"]["amount"] == 9_359_118
    assert merged[0]["award"]["modification_number"] == "P00001"
    assert {source["source_url"] for source in merged[0]["sources"]} == {
        OCT_6_FIXTURE_URL,
        "https://www.usaspending.gov/award/example/",
    }
    assert merged[0]["source"]["source_url"] == OCT_6_FIXTURE_URL
    assert [source["name"] for source in merged[0]["sources"] if source["primary"]] == ["War.gov"]
