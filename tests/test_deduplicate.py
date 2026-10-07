from copy import deepcopy

from pipeline.deduplicate import deduplicate


def record(source_type, source_url, description, *, award_id=None):
    return {
        "id": source_type, "announcement_date": "2026-10-07", "action_date": "2026-10-07",
        "company": {"canonical_name": "Example Tech", "uei": "UEI1"},
        "award": {"amount": 42_000_000, "contract_number": "FA-123", "award_id": award_id, "description": description, "naics": None, "psc": None, "subagency": None},
        "location": {"place_of_performance": None, "work_locations": []}, "classification": {"primary": "Other", "secondary": []},
        "source": {"name": "Test", "source_type": source_type, "source_url": source_url},
        "sources": [{"name": "Test", "source_type": source_type, "source_url": source_url}],
    }


def test_deduplication_merges_and_retains_all_source_urls():
    announcement = record("announcement", "https://war.gov/article/1", "Human-readable award description")
    structured = record("structured_award", "https://usaspending.gov/award/1", "Structured description", award_id="CONT_AWD_1")
    output, merged = deduplicate([structured, announcement])
    assert merged == 1 and len(output) == 1
    assert {s["source_url"] for s in output[0]["sources"]} == {"https://war.gov/article/1", "https://usaspending.gov/award/1"}
    assert output[0]["source"]["source_type"] == "announcement"
    assert output[0]["award"]["award_id"] == "CONT_AWD_1"


def test_historical_record_is_preserved_when_no_new_records():
    original = record("announcement", "https://agency.gov/old", "Historic record")
    output, merged = deduplicate([deepcopy(original)])
    assert output == [original]
    assert merged == 0
