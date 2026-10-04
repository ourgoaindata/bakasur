"""Area parsing with Indian digit grouping."""

from __future__ import annotations

import re
from typing import Any


INDIAN_NUM_RE = re.compile(r"[\d,]+")
PARTLY_RE = re.compile(
    r"Partly\s+([^(\[]+?)\s*\((\d+)m2\)",
    re.I,
)


def parse_indian_int(text: str | None) -> int | None:
    if not text:
        return None
    m = INDIAN_NUM_RE.search(text.replace(" ", ""))
    if not m:
        return None
    digits = m.group(0).replace(",", "")
    if not digits.isdigit():
        return None
    return int(digits)


def parse_area_breakdown(text: str | None) -> list[dict[str, Any]]:
    if not text:
        return []
    parts: list[dict[str, Any]] = []
    for m in PARTLY_RE.finditer(text):
        parts.append({"use": m.group(1).strip(), "sqm": int(m.group(2))})
    return parts


def extract_total_area(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"Total\s+Area\s*\(([^)]+)\)", text, re.I)
    if m:
        return parse_indian_int(m.group(1))
    return parse_indian_int(text)
