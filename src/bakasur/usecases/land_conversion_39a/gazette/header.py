"""Gazette masthead (series, issue, publication date) and notification signing dates."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from bakasur.usecases.land_conversion_39a.models import GazetteInfo, NotificationSpan

SERIES_RE = re.compile(r"SERIES\s+(I{1,3})\s+No\.?\s*(\d+)", re.I)
# "Panaji, 08th October, 2026 (Asvina 16, 1948)"; OCR sometimes reads 0 as O.
_DATE = r"Panaji,\s*([0-9O]{1,2})\s*(?:st|nd|rd|th)?\s+([A-Za-z]+),?\s*(\d{4})"
PUBLISHED_RE = re.compile(_DATE + r"\s*\(", re.I)
# The signature line closing a notification: "Panaji, 7th October, 2026."
SIGNED_RE = re.compile(_DATE + r"\s*\.", re.I)


def _to_date(day: str, month: str, year: str) -> date | None:
    try:
        return datetime.strptime(f"{day.upper().replace('O', '0')} {month[:3]} {year}", "%d %b %Y").date()
    except ValueError:
        return None


def _iso_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def gazette_info(page_texts: dict[int, str], meta: dict[str, Any]) -> GazetteInfo:
    """Read the masthead from page 1, falling back to what the filename gave."""
    first = page_texts[min(page_texts)] if page_texts else ""
    # The masthead can also carry a stray "SERIES I No. 28" line, so prefer the highest series.
    series_hits = SERIES_RE.findall(first)
    series, issue = max(series_hits, key=lambda hit: len(hit[0])) if series_hits else (None, None)
    series = series.upper() if series else None
    m = PUBLISHED_RE.search(first)
    published = _to_date(*m.groups()) if m else None
    return GazetteInfo(
        series=series or (meta.get("series") or "").upper().removeprefix("S") or None,
        issue_no=issue or meta.get("issue_no"),
        published=published or _iso_date(meta.get("gazette_date")),
    )


def notification_date(page_texts: dict[int, str], span: NotificationSpan) -> date | None:
    """The first signing date after the notification's number, on its pages or the next."""
    text = "\n".join(
        page_texts[p] for p in sorted(page_texts) if span.page_start <= p <= span.page_end + 1
    )
    start = text.find(span.notification_no) if span.notification_no else -1
    m = SIGNED_RE.search(text, max(start, 0))
    return _to_date(*m.groups()) if m else None
