"""39A notification span detection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from bakasur.gazette.tables import body_text
from bakasur.models import NotificationSpan, TableVariant


NOTIFICATION_RE = re.compile(
    r"Notification\s+No\.?\s*([^\r\n]+)",
    re.I,
)


@dataclass
class AnchorConfig:
    anchor_patterns: list[str]
    span_end_patterns: list[str]
    running_text_patterns: list[str] = field(default_factory=list)


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def _prose(text: str) -> str:
    """Page text without markdown table rows, so table cells can't match anchors."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("|"))


def _variant_hint(text: str) -> TableVariant | None:
    if re.search(r"No Development Zone", text, re.I):
        return TableVariant.NDZ
    if re.search(r"change of zone|Section\s+39A", text, re.I):
        return TableVariant.CHANGE_OF_ZONE
    return None


def _first_and_last_tables(
    tables: list[dict[str, Any]],
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    first: dict[int, dict[str, Any]] = {}
    last: dict[int, dict[str, Any]] = {}
    for table in sorted(tables, key=lambda t: t.get("index") or 0):
        if table.get("page_no") is None:
            continue
        page = int(table["page_no"])
        first.setdefault(page, table)
        last[page] = table
    return first, last


def find_notification_spans(
    page_texts: dict[int, str],
    cfg: AnchorConfig,
    tables: list[dict[str, Any]] | None = None,
) -> list[NotificationSpan]:
    """Find 39A notification page spans from per-page text and table layout."""
    pages = sorted(page_texts.keys())
    prose = {p: _prose(page_texts[p]) for p in pages}
    first_table, last_table = _first_and_last_tables(tables or [])

    def table_ends_on(page: int, is_start: bool) -> bool:
        """The page's last table is followed by text, or doesn't carry on to the next page."""
        table = last_table.get(page)
        if table is None:
            return False
        after = table.get("text_after") or []
        # On the start page, a table followed by the anchor belongs to the previous notification.
        if is_start and any(_matches_any(t, cfg.anchor_patterns) for t in after):
            return False
        if body_text(after, cfg.running_text_patterns):
            return True
        nxt = first_table.get(page + 1)
        return nxt is None or bool(body_text(nxt.get("text_before"), cfg.running_text_patterns))

    def new_notification_after_end(page: int) -> bool:
        table = last_table.get(page)
        if table is not None:
            tail = "\n".join(table.get("text_after") or [])
        else:
            text = prose[page]
            ends = [m.end() for p in cfg.span_end_patterns if (m := re.search(p, text, re.I))]
            tail = text[min(ends) :] if ends else text
        return bool(NOTIFICATION_RE.search(tail))

    spans: list[NotificationSpan] = []
    i = 0
    while i < len(pages):
        page_no = pages[i]
        text = prose[page_no]
        if not _matches_any(text, cfg.anchor_patterns):
            i += 1
            continue

        start = page_no
        notification_no: str | None = None
        m = NOTIFICATION_RE.search(text)
        if m:
            notification_no = m.group(1).strip()

        variant = _variant_hint(page_texts[page_no])
        end = start
        j = i + 1
        if not table_ends_on(start, is_start=True):
            while j < len(pages):
                next_page = pages[j]
                next_text = prose[next_page]
                if _matches_any(next_text, cfg.span_end_patterns) and next_page > start + 1:
                    end = next_page
                    break
                if _matches_any(next_text, cfg.anchor_patterns) and next_page > start:
                    end = pages[j - 1]
                    break
                end = next_page
                if table_ends_on(next_page, is_start=False):
                    break
                j += 1

        spans.append(
            NotificationSpan(
                notification_no=notification_no,
                page_start=start,
                page_end=end,
                variant_hint=variant,
            )
        )
        # The closing page often repeats "Section 39A"; only rescan it if a new notification begins there.
        if j < len(pages) and pages[j] == end and not new_notification_after_end(end):
            j += 1
        i = j if j > i else i + 1

    return spans
