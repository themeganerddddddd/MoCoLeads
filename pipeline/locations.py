from __future__ import annotations

import re


def format_location(value) -> str | None:
    if not value:
        return None
    if isinstance(value, str):
        return " ".join(value.split()) or None
    if isinstance(value, dict):
        preferred = ["city_name", "city", "county_name", "state_code", "state", "country_name", "country"]
        parts = []
        for key in preferred:
            val = value.get(key)
            if val and str(val) not in parts:
                parts.append(str(val))
        return ", ".join(parts) if parts else ", ".join(str(x) for x in value.values() if x)
    return str(value)


def parse_work_locations(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return list(dict.fromkeys(filter(None, (format_location(v) for v in value))))
    text = format_location(value)
    if not text:
        return []
    pieces = re.split(r"\s*;\s*|\s+and\s+(?=[A-Z])", text)
    return list(dict.fromkeys(x.strip(" ,") for x in pieces if x.strip(" ,")))
