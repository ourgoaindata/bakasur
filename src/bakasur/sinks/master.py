"""Rows in the layout of the "Substantive Objections" tab of the 39A master sheet.

Columns the team fills by hand (letters, signatories, screenshots, coordinates, plan,
inspection notes) are left blank.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, timedelta

from bakasur.models import ApplicationRow, GazetteInfo
from bakasur.normalize.decision import format_area, recommended_area, tcp_comments
from bakasur.normalize.survey import leading_survey_number, split_survey
from bakasur.normalize.villages import VillageInfo, VillageLookup
from bakasur.normalize.zones import overlays, zone_codes

MASTER_HEADER = [
    "Sr No",
    "Taluka",
    "Rev Village",
    "S. No.",
    "Sub -Div",
    "Name of Applicant",
    "Old Zone (Primary)",
    "Old Zone -2 (eco zone)",
    "New Zone",
    "VP",
    "AC",
    "Area requested",
    "Area recommended",
    "Deadline",
    "Objection Letter",
    "Signed by?",
    "Screen Shot of Zoning",
    "Gazette link",
    "Gaz Date",
    "Co ordinates",
    "Total Plot Area",
    "TCP Comments",
    "Plan",
    "",
    "",
    "Notes from Online Inspection",
    "Notes from TCP File Inspection ",
    "Map Survey No",
]
# Suggestions may be sent within thirty days of publication.
OBJECTION_PERIOD = timedelta(days=30)
NOTIFICATION_NO_RE = re.compile(r"39A\s*/\s*Notification\s*\(([^)]+)\)\s*/\s*TCP\s*/\s*(\d{4})\s*/\s*(\d+)", re.I)


def _sheet_date(d: date | None) -> str:
    """6-August-26, as the master sheet shows gazette dates."""
    return f"{d.day}-{d:%B}-{d:%y}" if d else ""


def gazette_reference(gazette: GazetteInfo, notification_no: str | None, signed: date | None) -> str:
    """'SIII No 28\\n39A/(77)/2026/1114\\ndtd 7-Oct-2026', as in the "Gazette link" column."""
    lines = []
    if gazette.issue_no:
        lines.append(f"S{gazette.series or 'III'} No {gazette.issue_no}")
    if notification_no:
        m = NOTIFICATION_NO_RE.search(notification_no)
        lines.append(f"39A/({m.group(1)})/{m.group(2)}/{m.group(3)}" if m else notification_no)
    if signed:
        lines.append(f"dtd {signed.day}-{signed:%b}-{signed.year}")
    return "\n".join(lines)


def _agreed(values: Iterable[str | None]) -> str:
    """The value every candidate panchayat shares, or "" when they differ."""
    distinct = set(values)
    return (distinct.pop() or "") if len(distinct) == 1 else ""


def master_row(sr: int, row: ApplicationRow, gazette: GazetteInfo, villages: list[VillageInfo]) -> list[str]:
    survey, qualifier = split_survey(row.survey_raw)
    settlement = _agreed(v.settlement_code for v in villages) or None
    deadline = gazette.published + OBJECTION_PERIOD if gazette.published else None
    return [
        str(sr),
        row.taluka or "",
        row.village or "",
        survey,
        qualifier,
        row.applicant or "",
        ", ".join(zone_codes(row.existing_use, settlement)),
        ", ".join(overlays(row.existing_use)),
        ", ".join(zone_codes(row.proposed_use, settlement)),
        _agreed(v.vp_name for v in villages),
        _agreed(v.constituency for v in villages),
        format_area(row.area_proposed_sqm),
        format_area(recommended_area(row.decision, row.area_proposed_sqm)),
        _sheet_date(deadline),
        "",
        "",
        "",
        gazette_reference(gazette, row.notification_no, row.notification_date),
        _sheet_date(gazette.published),
        "",
        format_area(row.total_area_sqm),
        tcp_comments(row.decision),
        *[""] * 6,
    ]


def master_rows(rows: list[ApplicationRow], gazette: GazetteInfo, lookup: VillageLookup) -> list[list[str]]:
    """Sr No restarts at 1 for each file."""
    out = []
    for sr, row in enumerate(rows, start=1):
        survey, _ = split_survey(row.survey_raw)
        villages = lookup.find(row.village, row.taluka, leading_survey_number(survey))
        out.append(master_row(sr, row, gazette, villages))
    return out
