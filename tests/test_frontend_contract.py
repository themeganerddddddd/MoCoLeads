from pathlib import Path


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
