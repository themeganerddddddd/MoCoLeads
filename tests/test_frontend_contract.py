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
  {{market_relationship:'moco_company', company:{{canonical_name:'Local Co'}}, award:{{amount:100,agency:'A'}}, classification:{{primary:'Defense'}}, location:{{}}, source:{{}}}},
  {{market_relationship:'moco_company_working_in_moco', company:{{canonical_name:'Both Co'}}, award:{{amount:200,agency:'B'}}, classification:{{primary:'Research'}}, location:{{}}, source:{{}}}},
  {{market_relationship:'outside_company_working_in_moco', company:{{canonical_name:'Outside Co'}}, award:{{amount:300,agency:'C'}}, classification:{{primary:'Defense'}}, location:{{recipient_location:'McLean, VA',place_of_performance:'Bethesda, MD'}}, source:{{source_url:'https://example.gov'}}}}
];
const local = view.recordsForView(records, 'moco');
const work = view.recordsForView(records, 'work');
console.log(JSON.stringify({{local:view.summarize(local,['Defense']),work:view.summarize(work,['Defense']),exports:view.exportRows(work)}}));
"""
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    assert payload["local"] == {"awards": 2, "value": 300, "companies": 2, "techShare": 50}
    assert payload["work"] == {"awards": 1, "value": 300, "companies": 1, "techShare": 100}
    assert payload["exports"][0]["Company Location"] == "McLean, VA"
    assert payload["exports"][0]["MoCo Work Location"] == "Bethesda, MD"
