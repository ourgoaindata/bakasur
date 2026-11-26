"""What a gazette PDF's filename says about the issue."""

from __future__ import annotations

import re


def parse_filename_metadata(filename: str) -> dict[str, str | None]:
    """Best-effort metadata from a gazette PDF filename."""
    meta: dict[str, str | None] = {
        "series": None,
        "issue_no": None,
        "gazette_date": None,
    }
    m = re.search(r"SIII[-_]?OG(\d+)", filename, re.I)
    if m:
        meta["issue_no"] = m.group(1)
        meta["series"] = "SIII"
    m = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
    if m:
        meta["gazette_date"] = m.group(1)
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})", filename)
    if m and not meta["gazette_date"]:
        meta["gazette_date"] = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return meta
