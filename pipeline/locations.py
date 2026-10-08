from __future__ import annotations

import re


def format_location(value) -> str | None:
    if not value:
        return None
    if isinstance(value, str):
        return " ".join(value.split()) or None
    if isinstance(value, dict):
        city = value.get("city_name") or value.get("city")
        state = value.get("state_code") or value.get("state") or value.get("state_name")
        county = value.get("county_name") or value.get("county")
        county_code = str(value.get("county_code") or value.get("county_fips") or value.get("county_fips_code") or "").strip()
        if not county and county_code in {"031", "24031"} and str(state).casefold() in {"md", "maryland", "24"}:
            county = "Montgomery County"
        country = value.get("country_name") or value.get("country")
        parts = [str(item) for item in (city or county, state) if item]
        if country and str(country).casefold() not in {"usa", "united states", "united states of america"}:
            parts.append(str(country))
        return ", ".join(dict.fromkeys(parts)) if parts else ", ".join(str(x) for x in value.values() if x)
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
