"""Append records to tabs of one Google Sheet with a service account."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsClient:
    def __init__(self, service_account_file: Path | None, sheet_id: str) -> None:
        self.service_account_file = service_account_file
        self.sheet_id = sheet_id
        self._client: gspread.Client | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.sheet_id and self.service_account_file)

    def _get_client(self) -> gspread.Client:
        if self._client is None:
            if not self.service_account_file:
                raise RuntimeError("google_service_account_file is not configured")
            creds = Credentials.from_service_account_file(
                str(self.service_account_file),
                scopes=SCOPES,
            )
            self._client = gspread.authorize(creds)
        return self._client

    def _ensure_worksheet(self, title: str, headers: list[str]) -> gspread.Worksheet:
        sh = self._get_client().open_by_key(self.sheet_id)
        try:
            ws = sh.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=title, rows=1000, cols=len(headers))
            ws.append_row(headers)
        if not ws.row_values(1):
            ws.append_row(headers)
        return ws

    def append_records(self, tab: str, records: list[dict[str, Any]]) -> None:
        """Append dicts as rows; a new tab gets the first record's keys as its header."""
        if not records:
            return
        headers = list(records[0].keys())
        ws = self._ensure_worksheet(tab, headers)
        ws.append_rows([[d.get(h) for h in headers] for d in records])
