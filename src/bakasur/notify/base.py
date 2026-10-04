"""Notifier protocol."""

from __future__ import annotations

from typing import Protocol

from bakasur.models import ApplicationRow, ValidationIssue


class Notifier(Protocol):
    def send_digest(
        self,
        gazette_id: str,
        rows: list[ApplicationRow],
        review: list[ValidationIssue],
        *,
        extracted: int,
        sheet_url: str | None = None,
        sheets_pending: int = 0,
        sheets_error: str | None = None,
    ) -> None: ...

    def send_failure(self, gazette_id: str, error: str) -> None: ...
