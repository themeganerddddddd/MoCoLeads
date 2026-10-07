from __future__ import annotations

import re

CATEGORY_RULES = [
    ("Quantum", ["quantum", "qubit"]),
    ("Microelectronics / Semiconductor", ["semiconductor", "microelectronics", "integrated circuit", "chip fabrication"]),
    ("Autonomous Systems / Drones", ["autonomous", "unmanned", " uas ", "drone", "robotic vehicle"]),
    ("Space / Satellite", ["satellite", "spacecraft", "space force", "orbital", "launch vehicle"]),
    ("Cybersecurity", ["cybersecurity", "cyber security", "zero trust", "threat detection", "information assurance"]),
    ("Artificial Intelligence / Data", ["artificial intelligence", "machine learning", "generative ai", "data analytics", "neural network"]),
    ("Advanced Communications", ["radio frequency", " rf ", "communications", "5g", "c4isr", "command and control", "networking"]),
    ("Software / IT", ["software", "cloud", "information technology", "it services", "data center", "devsecops"]),
    ("Life Sciences / Biodefense", ["biodefense", "vaccine", "biomedical", "pharmaceutical", "clinical", "biological"]),
    ("Advanced Manufacturing", ["additive manufacturing", "advanced manufacturing", "digital manufacturing"]),
]
DEFENSE_TERMS = ["department of defense", "department of the air force", "department of the army", "department of the navy", "darpa", "missile", "radar", "electronic warfare", "warfighter"]


def classify(record: dict) -> dict:
    award = record.get("award", record)
    text = " ".join(str(x or "") for x in [award.get("agency"), award.get("subagency"), award.get("description"), award.get("naics"), award.get("psc"), record.get("title")]).casefold()
    matches = []
    for category, terms in CATEGORY_RULES:
        if any(term.strip() in text if len(term.strip()) > 2 else term in text for term in terms):
            matches.append(category)
    naics = str(award.get("naics") or "")
    psc = str(award.get("psc") or "").upper()
    if (naics.startswith("54151") or psc.startswith(("D3", "DA"))) and "Software / IT" not in matches:
        matches.append("Software / IT")
    if naics.startswith(("336414", "336415", "336419")) and "Space / Satellite" not in matches:
        matches.append("Space / Satellite")
    if naics.startswith("33441") and "Microelectronics / Semiconductor" not in matches:
        matches.append("Microelectronics / Semiconductor")
    if naics.startswith("517") and "Advanced Communications" not in matches:
        matches.append("Advanced Communications")
    is_defense = any(term in text for term in DEFENSE_TERMS)
    if matches:
        primary = matches[0]
        if is_defense and primary not in {"Space / Satellite", "Cybersecurity", "Artificial Intelligence / Data", "Autonomous Systems / Drones"}:
            primary = "Defense Technology"
    elif is_defense:
        primary = "Defense"
    elif naics.startswith("5416") or psc.startswith("R4") or any(term in text for term in ["consulting", "professional services", "management support"]):
        primary = "Professional Services"
    else:
        primary = "Other"
    secondary = [x for x in matches if x != primary]
    if is_defense and primary not in {"Defense", "Defense Technology"}:
        secondary.insert(0, "Defense")
    return {"primary": primary, "secondary": list(dict.fromkeys(secondary))}
