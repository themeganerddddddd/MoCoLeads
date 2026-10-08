from datetime import date

from collectors import usaspending


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_usaspending_queries_known_entities_and_montgomery_county(monkeypatch):
    payloads = []

    def fake_post(url, json):
        payloads.append(json)
        route = "county" if "recipient_locations" in json["filters"] else "known"
        item = {
            "Award ID": f"AWARD-{route}",
            "Recipient Name": "Known Co" if route == "known" else "New Local Co",
            "Recipient UEI": None,
            "Action Date": "2026-10-07",
            "Transaction Amount": 100,
            "Awarding Agency": "Agency",
            "generated_internal_id": f"ID-{route}",
            "Recipient Location": {"state_code": "MD", "county_code": "031"},
        }
        return FakeResponse({"results": [item], "page_metadata": {"hasNext": False}})

    monkeypatch.setattr(usaspending, "post", fake_post)
    companies = [{
        "company_id": "known", "canonical_name": "Known Co", "legal_name": "Known Co LLC",
        "aliases_list": [], "hq_status": "verified",
    }, {
        "company_id": "excluded", "canonical_name": "Amentum Services Inc.",
        "legal_name": "Amentum Services Inc.", "aliases_list": [], "hq_status": "not_moco",
    }]
    records = usaspending.collect(companies, days=7, today=date(2026, 10, 8))
    assert len(payloads) == 2
    assert payloads[0]["filters"]["recipient_search_text"] == ["Known Co LLC"]
    assert payloads[1]["filters"]["recipient_locations"] == [{"country": "USA", "state": "MD", "county": "031"}]
    assert payloads[1]["filters"]["time_period"] == [{"start_date": "2026-10-01", "end_date": "2026-10-08"}]
    assert {record["discovery_route"] for record in records} == {"known_company", "county_recipient"}
    assert usaspending.get_last_report() == {
        "status": "success",
        "records_retrieved": 2,
        "known_company_matches": 1,
        "county_discovery_matches": 1,
        "new_entities_discovered": 1,
    }


def test_usaspending_prefers_uei_for_known_entity_search(monkeypatch):
    payloads = []

    def fake_post(url, json):
        payloads.append(json)
        return FakeResponse({"results": [], "page_metadata": {"hasNext": False}})

    monkeypatch.setattr(usaspending, "post", fake_post)
    usaspending.collect([{
        "company_id": "known", "canonical_name": "Known Co", "legal_name": "Known Co LLC",
        "aliases_list": [], "uei": "ABC123UEI", "hq_status": "verified",
    }], days=7, today=date(2026, 10, 8))
    assert payloads[0]["filters"]["recipient_search_text"] == ["ABC123UEI"]
