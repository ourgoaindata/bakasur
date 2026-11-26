"""Village and taluka parsing."""

from __future__ import annotations

import re

GOA_TALUKAS = {
    "bardez",
    "bicholim",
    "canacona",
    "dharbandora",
    "mormugao",
    "pernem",
    "ponda",
    "quepem",
    "salcete",
    "sanguem",
    "sattari",
    "tiswadi",
}


# A hyphenated name wrapped across lines comes out as "Salvador- do-Mundo".
WRAPPED_HYPHEN_RE = re.compile(r"(?<=\w)-\s+(?=\w)")


def split_village_taluka(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    value = WRAPPED_HYPHEN_RE.sub("-", value)
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if len(parts) >= 2:
        village = parts[0]
        taluka = parts[-1]
        return village, taluka
    if len(parts) == 1:
        lower = parts[0].lower()
        if lower in GOA_TALUKAS:
            return None, parts[0]
        return parts[0], None
    return None, None


def is_known_taluka(taluka: str | None) -> bool:
    if not taluka:
        return False
    return taluka.strip().lower() in GOA_TALUKAS
