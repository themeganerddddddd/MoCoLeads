from __future__ import annotations

import os


def collect(days=7):
    if not os.getenv("SAM_API_KEY"):
        print("SAM.gov: SAM_API_KEY is not set; optional enrichment skipped")
        return []
    # Entity enrichment is intentionally opt-in. Never serialize the key or send it to the browser.
    print("SAM.gov: key detected; entity enrichment hook is enabled (no opportunity records collected in V1)")
    return []
