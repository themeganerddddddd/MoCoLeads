from __future__ import annotations

from datetime import date
from pathlib import Path

import collectors.war_contracts as war
from pipeline.normalize import normalize_record


FIXTURES = Path(__file__).parent / "fixtures"
RSS_XML = (FIXTURES / "war_contracts_rss.xml").read_text(encoding="utf-8")
ARTICLE_HTML = (FIXTURES / "war_oct_6_2026.html").read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, status_code: int, text: str = "", payload: dict | None = None):
        self.status_code = status_code
        self.text = text
        self.ok = 200 <= status_code < 400
        self._payload = payload

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses: dict[str, FakeResponse]):
        self.responses = responses
        self.calls = []

    def get(self, url: str, **kwargs):
        self.calls.append(url)
        return self.responses[url]


def test_rss_discovery_title_date_and_exact_url():
    announcements = war.discover_announcements_from_rss(RSS_XML)
    assert len(announcements) == 2
    assert announcements[0]["title"] == "Contracts for Oct. 6, 2026"
    assert announcements[0]["announcement_date"] == "2026-10-06"
    assert announcements[0]["publication_date"] == "2026-10-06"
    assert announcements[0]["url"] == war.OCT_6_FIXTURE_URL


def test_html_discovery_falls_back_to_official_rss():
    rss_url = war.RSS_URL_TEMPLATE.format(max_entries=20)
    client = FakeSession({
        war.INDEX_URL: FakeResponse(403),
        rss_url: FakeResponse(200, RSS_XML),
    })
    report = {}
    announcements, method = war._discover_with_fallback(client, report)
    assert method == "rss"
    assert announcements[0]["url"] == war.OCT_6_FIXTURE_URL
    assert report == {"html_index_status": 403, "rss_status": 200}


def test_request_403_uses_browser_html_and_existing_parser(monkeypatch, tmp_path):
    rss_url = war.RSS_URL_TEMPLATE.format(max_entries=20)
    client = FakeSession({
        war.INDEX_URL: FakeResponse(403),
        rss_url: FakeResponse(200, RSS_XML),
        war.OCT_6_FIXTURE_URL: FakeResponse(403),
        "https://www.war.gov/News/Contracts/Contract/Article/4619000/contracts-for-oct-5-2026/": FakeResponse(200, "<article></article>"),
    })
    browser_calls = []

    def browser(url):
        browser_calls.append(url)
        return ARTICLE_HTML, 200

    monkeypatch.setattr(war, "_http_session", lambda: client)
    monkeypatch.setattr(war, "fetch_with_browser", browser)
    records = war.collect(days=7, today=date(2026, 10, 7), state_path=tmp_path / "state.json")

    assert browser_calls == [war.OCT_6_FIXTURE_URL]
    assert len(records) == 3
    assert {record["company_name"] for record in records} == {
        "Weldin Construction LLC", "Aegis Aerospace Inc.", "Collins Aerospace"
    }
    assert all(record["retrieval"] == {"discovery_method": "war_rss", "content_method": "browser"} for record in records)
    assert war.get_last_report()["status"] == "success"
    assert war.get_last_report()["browser_successes"] == 1


def test_structured_fallback_normalizes_and_preserves_provenance():
    announcement = {
        "title": "Contracts for Oct. 6, 2026",
        "announcement_date": "2026-10-06",
        "url": war.OCT_6_FIXTURE_URL,
    }
    award = {
        "award_key": "2026-10-06:FA8809-26-F-B003",
        "announced_on": "2026-10-06",
        "service": "Air Force",
        "contractor": "Aegis Aerospace Inc.",
        "contractor_location": "Houston, Texas",
        "amount": 9_359_118,
        "amount_is_ceiling": False,
        "shared_award": False,
        "contract_number": "FA8809-26-F-B003",
        "contract_types": ["firm-fixed-price"],
        "contracting_activity": "Space Systems Command",
        "completion_date": "October 2030",
        "description": "Support for satellite systems. Fiscal 2026 research funds in the amount of $2,000,000 are being obligated.",
        "url": war.OCT_6_FIXTURE_URL,
    }
    raw = war.normalize_structured_fallback(award, announcement, "rss")
    assert raw["source_url"] == war.OCT_6_FIXTURE_URL
    assert raw["obligated_amount"] == 2_000_000
    assert raw["retrieval"]["content_method"] == "pipeworx_fallback"
    assert raw["additional_sources"][0]["name"] == "Pipeworx"

    company = {
        "company_id": "aegis", "canonical_name": "Aegis Aerospace", "legal_name": "Aegis Aerospace Inc.",
        "aliases_list": ["Aegis Aerospace Inc."], "uei": "", "ultimate_parent": "", "hq_city": "Rockville",
        "hq_state": "MD", "hq_county": "Montgomery County", "hq_verified": True, "hq_status": "verified",
        "hq_confidence": 1.0,
    }
    normalized = normalize_record(raw, [company], "2026-10-07T12:00:00Z")
    assert normalized["source"]["source_url"] == war.OCT_6_FIXTURE_URL
    assert {source["name"] for source in normalized["sources"]} == {"War.gov", "Pipeworx"}
    assert normalized["retrieval"] == raw["retrieval"]


def test_fallback_associates_only_exact_official_war_url(monkeypatch):
    announcements = [
        {"title": "Contracts for Oct. 6, 2026", "announcement_date": "2026-10-06", "url": war.OCT_6_FIXTURE_URL},
        {"title": "Contracts for Oct. 6, 2026", "announcement_date": "2026-10-06", "url": "https://www.war.gov/other/"},
    ]
    award = {
        "award_key": "example", "announced_on": "2026-10-06", "service": "Air Force",
        "contractor": "Aegis Aerospace Inc.", "amount": 1, "description": "Satellite support",
        "url": war.OCT_6_FIXTURE_URL,
    }
    monkeypatch.setattr(war, "_pipeworx_recent", lambda: ([award], 200))
    records, status = war._structured_fallback(announcements, "rss")
    assert status == 200
    assert len(records) == 1
    assert records[0]["source_url"] == war.OCT_6_FIXTURE_URL


def test_collector_reports_structured_fallback_status(monkeypatch, tmp_path):
    client = FakeSession({
        war.INDEX_URL: FakeResponse(200, f'<a href="{war.OCT_6_FIXTURE_URL}">Contracts for Oct. 6, 2026</a>'),
        war.OCT_6_FIXTURE_URL: FakeResponse(403),
    })
    fallback_record = {
        "company_name": "Aegis Aerospace Inc.", "amount": 1, "source_url": war.OCT_6_FIXTURE_URL,
        "retrieval": {"discovery_method": "war_html_index", "content_method": "pipeworx_fallback"},
    }
    monkeypatch.setattr(war, "_http_session", lambda: client)
    monkeypatch.setattr(war, "fetch_with_browser", lambda url: (None, 403))
    monkeypatch.setattr(war, "_structured_fallback", lambda announcements, method: ([fallback_record], 200))

    records = war.collect(days=7, today=date(2026, 10, 7), state_path=tmp_path / "state.json")
    report = war.get_last_report()
    assert records == [fallback_record]
    assert report["status"] == "fallback"
    assert report["structured_fallback_status"] == 200
    assert report["structured_fallback_awards"] == 1
    assert report["unresolved_announcements"] == 0
