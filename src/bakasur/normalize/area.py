"""Area parsing with Indian digit grouping."""

from __future__ import annotations

import re
from typing import Any


PARTLY_RE = re.compile(
    r"Partly\s+([^(\[]+?)\s*\((\d+)m2\)",
    re.I,
)
AREA_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")  # Indian digit grouping: 13,80,498


def parse_area(text: str | None) -> int | float | None:
    """Area in m2, keeping decimals such as 199.56; whole numbers come back as int."""
    if not text:
        return None
    m = AREA_RE.search(text.replace(" ", ""))
    if not m:
        return None
    value = float(m.group(0).replace(",", ""))
    return int(value) if value.is_integer() else value


def parse_area_breakdown(text: str | None) -> list[dict[str, Any]]:
    if not text:
        return []
    parts: list[dict[str, Any]] = []
    for m in PARTLY_RE.finditer(text):
        parts.append({"use": m.group(1).strip(), "sqm": int(m.group(2))})
    return parts


def extract_total_area(text: str | None) -> int | float | None:
    if not text:
        return None
    m = re.search(r"Total\s+Area\s*\(([^)]+)\)", text, re.I)
    if m:
        return parse_area(m.group(1))
    return parse_area(text)
