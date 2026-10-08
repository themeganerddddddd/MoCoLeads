from pathlib import Path

from collectors.diu import discover_announcements, parse_article


FIXTURES = Path(__file__).parent / "fixtures"


def test_diu_html_index_discovers_relevant_official_article():
    announcements = discover_announcements((FIXTURES / "diu_latest.html").read_text(encoding="utf-8"))
    assert announcements == [{
        "title": "DIU Selects Three Companies to Provide Solutions to the Challenges of Contested Logistics",
        "announcement_date": "2024-08-21",
        "url": "https://www.diu.mil/latest/diu-selects-three-companies-to-provide-solutions-to-the-challenges-of",
    }]


def test_diu_selection_article_emits_one_record_per_company_with_nullable_amount():
    url = "https://www.diu.mil/latest/diu-selects-three-companies-to-provide-solutions-to-the-challenges-of"
    records = parse_article((FIXTURES / "diu_selection.html").read_text(encoding="utf-8"), url)
    assert [record["recipient_name"] for record in records] == ["Auterion", "ModalAI", "Neros"]
    assert all(record["announcement_date"] == "2024-08-21" for record in records)
    assert all(record["amount"] is None for record in records)
    assert all(record["source_url"] == url for record in records)
    assert all(record["award_type"] == "Prototype / Selection" for record in records)
