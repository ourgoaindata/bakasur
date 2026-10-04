"""Validation gates and confidence scoring."""

from __future__ import annotations

import re

from bakasur.models import ApplicationRow, ValidationIssue
from bakasur.normalize.place import is_known_taluka


def _parse_sr_no(sr_no: str | None) -> int | None:
    if not sr_no:
        return None
    m = re.search(r"\d+", sr_no)
    return int(m.group(0)) if m else None


def validate_rows(rows: list[ApplicationRow]) -> list[ValidationIssue]:
    # A gazette can carry several notifications, each with its own sr_no sequence.
    by_notification: dict[str | None, list[ApplicationRow]] = {}
    for row in rows:
        by_notification.setdefault(row.notification_no, []).append(row)

    issues: list[ValidationIssue] = []
    for notification_no, group in by_notification.items():
        issues.extend(_validate_notification(notification_no, group))
    return issues


def _validate_notification(
    notification_no: str | None, rows: list[ApplicationRow]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen_sr: set[int] = set()

    for row in rows:
        if row.review_reason:
            issues.append(ValidationIssue(row=row, reason=row.review_reason))
        if not row.survey_raw:
            issues.append(ValidationIssue(row=row, reason="Missing survey numbers"))
        if row.taluka and not is_known_taluka(row.taluka):
            issues.append(
                ValidationIssue(
                    row=row,
                    reason=f"Unknown taluka: {row.taluka}",
                    severity="warning",
                )
            )
        sr = _parse_sr_no(row.sr_no)
        if sr is not None:
            if sr in seen_sr:
                issues.append(
                    ValidationIssue(row=row, reason=f"Duplicate sr_no {sr}")
                )
            seen_sr.add(sr)

    nums = sorted(seen_sr)
    for i in range(1, len(nums)):
        if nums[i] != nums[i - 1] + 1:
            issues.append(
                ValidationIssue(
                    row=None,
                    reason=(
                        f"Non-monotonic sr_no sequence gap between {nums[i-1]} and {nums[i]}"
                        f" (notification {notification_no or 'unknown'})"
                    ),
                    severity="warning",
                )
            )
            break

    return issues


def partition_rows(
    rows: list[ApplicationRow],
) -> tuple[list[ApplicationRow], list[ValidationIssue]]:
    issues = validate_rows(rows)
    blocking = {id(i.row) for i in issues if i.severity == "error" and i.row}
    good = [r for r in rows if id(r) not in blocking]
    return good, issues
