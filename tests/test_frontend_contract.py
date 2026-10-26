from pathlib import Path
import json
import subprocess


ROOT = Path(__file__).parents[1]


def test_default_presence_filter_includes_local_entities():
    html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    assert '<option value="local" selected>Include local legal entities</option>' in html
    assert 'new Set(["verified", "strong", "local_entity"])' in javascript
    assert 'hq === "local" ? qualifiedStatuses.has(hqStatus)' in javascript


def test_load_failure_has_diagnostics_and_retry_control():
    html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    assert 'id="load-diagnostics-list"' in html
    assert 'id="retry-load"' in html
    assert '"#retry-load"' in javascript


def test_tabs_metrics_and_exports_use_independent_record_sets():
    module = ROOT / "site" / "view-model.js"
    script = f"""
const view = require({json.dumps(str(module))});
const records = [
  {{announcement_date:'2026-09-30', market_relationship:'moco_company', company:{{canonical_name:'Hidden Small Co'}}, award:{{amount:9999,agency:'A'}}, classification:{{primary:'Defense'}}, location:{{}}, source:{{}}}},
  {{announcement_date:'2026-10-01', market_relationship:'moco_company', company:{{canonical_name:'Local Co'}}, award:{{amount:10000,agency:'A'}}, classification:{{primary:'Defense'}}, location:{{}}, source:{{}}}},
  {{announcement_date:'2026-10-02', market_relationship:'moco_company_working_in_moco', company:{{canonical_name:'Both Co'}}, award:{{amount:20000,agency:'B'}}, classification:{{primary:'Research'}}, location:{{place_of_performance:'Rockville, MD'}}, source:{{}}}},
  {{announcement_date:'2026-10-03', market_relationship:'outside_company_working_in_moco', company:{{canonical_name:'Outside Co'}}, award:{{amount:30000,agency:'C',subagency:'C Office'}}, classification:{{primary:'Defense'}}, location:{{recipient_location:'McLean, VA',place_of_performance:'Bethesda, MD'}}, source:{{source_url:'https://example.gov'}}}}
];
const local = view.recordsForView(records, 'moco');
const work = view.recordsForView(records, 'work');
console.log(JSON.stringify({{local:view.summarize(local,['Defense']),work:view.summarize(work,['Defense']),october:view.recordsForMonth([...local,...work],2026,10).length,internalExports:view.exportRows(local,'moco'),externalExports:view.exportRows(work,'work')}}));
"""
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    assert payload["local"] == {"awards": 2, "value": 30000, "companies": 2, "techShare": 50}
    assert payload["work"] == {"awards": 1, "value": 30000, "companies": 1, "techShare": 100}
    assert payload["october"] == 3
    assert list(payload["internalExports"][0]) == ["Date", "Company", "Amount", "Agency", "Category", "What It Was For", "Work Location", "Contract #", "Source"]
    assert payload["externalExports"][0]["Company Location"] == "McLean, VA"
    assert payload["externalExports"][0]["Agency"] == "C Office"
    assert payload["externalExports"][0]["MoCo Work Location"] == "Bethesda, MD"
    assert "Market Relationship" not in payload["externalExports"][0]


def test_monthly_export_controls_and_daily_schedule_are_present():
    html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "update-contracts.yml").read_text(encoding="utf-8")
    assert "External Companies in MoCo" in html
    assert 'id="export-month"' in html
    assert 'id="export-year"' in html
    assert 'id="download-month"' in html
    assert '<option value="10000" selected>$10K and above</option>' in html
    assert "recordsForMonth(viewRecords()" in javascript
    assert 'cron: "17 11 * * *"' in workflow
