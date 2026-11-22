"""Read the TCP Board's decision: recommended area and a short comment for the master sheet."""

from __future__ import annotations

import re

from bakasur.normalize.area import parse_area

# "an area of 1985m2 from Cultivable land with Irrigation Command Area to Settlement zone"
AREA_CLAUSE_RE = re.compile(
    r"an\s+area\s+of\s+(\d[\d,]*(?:\.\d+)?)\s*(?:m2|m²|sq\.?\s*m(?:ts?)?\.?)\s+"
    r"from\s+(.+?)\s+to\s+(.+?)"
    r"(?=\s*(?:,|\band\s+an\s+area\b|\bbeing\b|\bsubject\b|\.\s|\.?$))",
    re.I,
)
GRADIENT_RE = re.compile(r"permissible\s+gradient", re.I)
LOW_LYING_RE = re.compile(r"\bnot\s+low\s+lying(?:\s+paddy\s+field)?", re.I)
SUBJECT_TO_RE = re.compile(r"subject\s+to\s+(?:the\s+)?comments?\s+(?:from|of)\s+(?:the\s+)?(.+?)\s*\.?\s*$", re.I)
PLAIN_RE = re.compile(r"^\s*recommended\s+for\s+change\s+of\s+zone\s*\.?\s*$", re.I)
NOT_RECOMMENDED_RE = re.compile(r"\bnot\s+recommended\b", re.I)
_DEPARTMENTS = [
    (re.compile(r"Water\s+Resources?\s+Department", re.I), "WRD"),
    (re.compile(r"Forest\s+Department", re.I), "Forest Dept"),
    (re.compile(r"Goa\s+Coastal\s+Zone\s+Management\s+Authority", re.I), "GCZMA"),
]


def format_area(value: int | float | None) -> str:
    """1777 -> "1,777 sqm", 199.56 -> "199.56 sqm", as the master sheet writes areas."""
    if value is None:
        return ""
    text = f"{value:,}" if isinstance(value, int) else f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{text} sqm"


def area_clauses(decision: str | None) -> list[tuple[int | float, str, str]]:
    return [
        (parse_area(area), src.strip(), dst.strip(" ."))
        for area, src, dst in AREA_CLAUSE_RE.findall(decision or "")
    ]


def recommended_area(decision: str | None, area_proposed: int | float | None) -> int | float | None:
    """The areas the decision lists, summed; the whole proposed area when it lists none."""
    if NOT_RECOMMENDED_RE.search(decision or ""):
        return None
    areas = [area for area, _, _ in area_clauses(decision)]
    if not areas:
        return area_proposed
    total = sum(areas)
    return round(total, 2) if isinstance(total, float) else total


def tcp_comments(decision: str | None) -> str:
    """One line per area changed, then the conditions: gradient, low lying, other departments."""
    decision = re.sub(r"\s+", " ", decision or "").strip()
    lines = [f"{format_area(area)} from {src} to {dst}" for area, src, dst in area_clauses(decision)]
    if GRADIENT_RE.search(decision):
        lines.append("For being within permissible gradient")
    if m := LOW_LYING_RE.search(decision):
        lines.append(f"Being {m.group(0).lower()}")
    if m := SUBJECT_TO_RE.search(decision):
        departments = m.group(1)
        for rx, short in _DEPARTMENTS:
            departments = rx.sub(short, departments)
        lines.append(f"Subject to comments from {departments}")
    if not lines and decision and not PLAIN_RE.match(decision):
        lines.append(decision)
    return "\n".join(lines)
