# Instructions for future Codex sessions

- Preserve the canonical contract schema used in `data/contracts.json` and add fields compatibly.
- Never remove or replace specific federal source links with generic agency homepages.
- Preserve historical records when new collection runs complete; never overwrite history with only today's data.
- Keep company headquarters, recipient address, and place of performance as separate concepts.
- Do not promote a Montgomery County recipient address to a verified headquarters without independent evidence.
- Never expose API keys or other secrets in JavaScript, logs, generated data, fixtures, or commits.
- Run `python -m pytest` before committing substantive changes.
- Preserve relative asset and data paths so GitHub Pages project URLs continue to work.
- Keep collectors independent: one failing collector must be logged and must not stop the others.
- Prefer official federal APIs, feeds, and announcement pages over secondary reporting.
- Never fabricate missing amounts, locations, UEIs, descriptions, contract numbers, or dates. Use null.
- Retain all source URLs during normalization and deduplication.
