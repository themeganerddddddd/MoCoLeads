# Montgomery County Federal Contract Tracker

A production-oriented static dashboard for finding newly announced federal contracts awarded to companies headquartered in Montgomery County, Maryland. The tracker separates company headquarters from recipient offices and contract work locations, preserves the original federal source for every record, and keeps a historical archive across daily runs.

The browser application is plain HTML, CSS, and JavaScript. Collection and processing use Python. GitHub Actions updates the data daily and deploys the static site to GitHub Pages. No application server or database is required.

## Sources

- **War.gov contract announcements** — the primary same-day source for Department of Defense announcements. Records retain the individual announcement URL.
- **USAspending** — transaction-level contract data for known registry companies, queried with a rolling seven-day overlap. Records link to the federal award where a generated award ID is available.
- **NASA, DIU, and DARPA** — low-volume official feed collectors. These are intentionally independent and may report an unavailable status when an agency changes or removes its feed.
- **SBIR/STTR** — optional hook that currently reports unavailable without interrupting the run.
- **SAM.gov** — optional enrichment hook. It activates only when `SAM_API_KEY` is present and never exposes the secret to the site.

Agency sites change. Collector errors are recorded in `data/metadata.json`; successful collectors continue, and existing historical records remain intact.

### War.gov collection details

The War.gov collector starts at `https://www.war.gov/news/contracts/`, discovers anchors whose visible title matches `Contracts for [date]`, and follows the exact dated article URLs from those anchors. It splits each article by service heading and award paragraph before independently parsing contractor identity, announced contractor location, action amount, ceiling, obligation, cumulative value, modification number, contract number, work locations, completion date, funding, contracting activity, and explicit award date.

`data/war_processed.json` records seen and successfully processed announcement URLs. Normal daily runs use `WAR_LOOKBACK_DAYS=7`. For a deliberate first-run historical import, set `WAR_BOOTSTRAP_DAYS=365`. A newly discovered link is attempted even when it falls outside the ordinary overlap, while the initial discovery does not crawl the entire index unless bootstrap mode is explicitly enabled.

War.gov can return HTTP 403 to automated clients. Discovery therefore tries the official contracts index first and the official War.gov RSS feed second. Article retrieval tries the normal HTTP client and, only after a 403, one ordinary headless-browser load. If the article is still unavailable, the collector can recover structured fields through the Pipeworx DoD contract-announcements provider while keeping the exact official dated War.gov article URL as the primary source. The retrieval method and collector health are recorded in the generated data and metadata; no access control is bypassed.

Run the access and parser diagnostic with:

```bash
python -m collectors.war_contracts --debug
```

The diagnostic reports the live index status, discovery method, newest dated URL, normal article status, browser status, structured fallback status, and award count. It also runs the Oct. 6, 2026 parser regression against the saved fixture under `tests/fixtures/` when the reference article is unavailable.

## Daily update architecture

`scripts/update.py` runs this sequence:

```text
collect → normalize → company match → HQ status → classify
        → deduplicate → merge history → validate → sort → write JSON/CSV
```

Each collector runs in its own error boundary. Validation happens before production contract files are overwritten. Deduplication first uses contract/award identifiers, then UEI + amount + date, then normalized company + amount + date, with conservative description similarity as a final signal. Duplicate records are merged so announcement prose and work locations can coexist with USAspending identifiers and classification fields. Every distinct source URL is retained.

DoD announcement data can appear before structured data. War.gov records are therefore retained even if USAspending has not caught up; a later matching transaction enriches the historical announcement.

## Run locally

Python 3.11 or newer is recommended.

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/update.py
python -m pytest
python -m http.server 8000
```

Open `http://localhost:8000/site/`. The frontend detects that development path and loads `../data/`. GitHub Pages deployment puts `index.html` at the artifact root and loads `./data/`, so project Pages paths such as `https://USERNAME.github.io/moco-federal-contracts/` work without hardcoded root URLs.

## Publishing to GitHub

Suggested repository description:

> Daily tracker of federal contract awards to companies headquartered in Montgomery County, Maryland.

1. Create an empty public GitHub repository without a README, `.gitignore`, or license.
2. From this project directory, create the initial commit, add the new repository as `origin`, and push this repository to `main` (exact commands are included in the release-readiness handoff).
3. In **Settings → Actions → General → Workflow permissions**, select **Read and write permissions** so the daily data workflow can commit generated files.
4. Go to **Settings → Pages** and, under **Build and deployment**, select **GitHub Actions**.
5. Open **Actions** and run **Update federal contracts** manually once.
6. Verify that **Deploy dashboard to GitHub Pages** succeeds.
7. Open the published Pages URL shown by the deployment.

After this setup, the tracker checks for new awards automatically every day. Successful data commits to `main` trigger Pages deployment without a manual step.

`SAM_API_KEY` is optional. If you use it, add it only under **Settings → Secrets and variables → Actions** as a repository secret named `SAM_API_KEY`; never commit the key.

No license file is included; choose and add a license separately if and when you want to grant reuse rights.

## GitHub Pages deployment

The deployment workflow assembles `site/` plus the public data files into one static artifact and reports the public URL in the deployment summary. A push that changes `site/`, `data/`, or the deployment workflow triggers it.

The daily data workflow runs at **11:17 UTC** and also supports manual execution from the Actions tab. It commits generated data only when the staged files changed, using the `moco-contract-bot` identity. A resulting push to `main` triggers Pages deployment automatically.

Repository Actions need `contents: write` permission. If organization defaults block workflow writes, enable **Settings → Actions → General → Workflow permissions → Read and write permissions**.

## Company headquarters registry

`companies/moco_companies.csv` is a deliberately small sample, not a comprehensive business directory. Add or edit rows using these fields:

- `company_id`, `canonical_name`, `legal_name`, pipe-delimited `aliases`
- `ultimate_parent`, `uei`
- `hq_address`, `hq_city`, `hq_state`, `hq_zip`, `hq_county`
- `hq_verified`, `hq_status`, `hq_confidence`, `hq_source`
- `sector`, `website`, `notes`, `last_verified`

Use `verified`, `strong`, `probable`, `needs_review`, or `not_moco` for `hq_status`. Exact UEIs take precedence over normalized names. Name matching is case- and punctuation-insensitive, but intentionally conservative.

An unfamiliar recipient with an address that appears to be in Montgomery County is written to `data/company_candidates.csv` with `needs_review`. It is **not** displayed as a confirmed headquarters match. A human should verify the corporate headquarters through an authoritative source, add the company to the registry, and then rerun the pipeline.

## Optional SAM.gov key

For local use, set the key only in the environment:

```powershell
$env:SAM_API_KEY = "your-key"
python scripts/update.py
```

For GitHub Actions, create a repository secret named exactly `SAM_API_KEY` under **Settings → Secrets and variables → Actions**. Do not commit the key. V1 works without it and prints a clear skip message.

## Run an update manually

Locally, run `python scripts/update.py`. On GitHub, open **Actions → Update federal contracts → Run workflow**. The job installs dependencies, collects sources, validates JSON, runs the full test suite, and commits only changed data files.

For a one-time historical bootstrap, set `MOCO_LOOKBACK_DAYS` before running. Daily automation should keep the default seven-day overlap:

```powershell
$env:MOCO_LOOKBACK_DAYS = "365"
python scripts/update.py
```

## Canonical data fields

Each record contains:

- stable `id`, `announcement_date`, and `action_date`
- `company`: canonical/legal name, UEI, parent, headquarters, verification status and confidence
- `award`: numeric amount or null, display amount, agency/subagency, contract and award IDs, description, NAICS, PSC, type, completion and obligated funds when available
- `location`: recipient location, place of performance, and all stated work locations
- `classification`: one primary category and optional secondary categories
- `source`: the primary official source
- `sources`: every retained official source after deduplication
- `match`: registry match method and company ID for auditability

`data/contracts.json` is the historical frontend source, `latest.json` contains the newest 25 records, `contracts.csv` is the flat download, `companies.json` is the generated registry view, and `metadata.json` reports freshness and collector health.

## Classification

Classification considers agency, subagency, NAICS, PSC, description, and program/title text. Categories include Defense, Defense Technology, Space / Satellite, Cybersecurity, Artificial Intelligence / Data, Software / IT, Quantum, Microelectronics / Semiconductor, Advanced Communications, Autonomous Systems / Drones, Advanced Manufacturing, Life Sciences / Biodefense, Professional Services, and Other. Keyword signals are combined with agency context; missing information remains unknown rather than inferred.

## Known limitations

- The starter company registry is intentionally incomplete and needs ongoing human curation.
- A recipient address is evidence for candidate review, not proof of headquarters.
- Press announcements often omit UEI, NAICS, PSC, exact work locations, or award identifiers.
- USAspending can lag same-day announcements and transaction amounts may represent modifications rather than total potential contract value.
- NASA, DIU, DARPA, and SBIR publishing interfaces can change; their failure state is visible in metadata and on the dashboard.
- Automated classification is useful for discovery but should not replace review for policy or investment decisions.
- “Announced value” totals only disclosed numeric amounts. Headquarters in Montgomery County does not imply the work or spending occurs in Montgomery County.

## Tests and maintenance

Run `python -m pytest`. Tests cover alias normalization, UEI precedence, Montgomery County candidate detection, amount parsing, War.gov paragraph extraction, classification, multiple locations, null handling, deduplication, historical preservation, validation, and source URL retention through normalization and merges.
