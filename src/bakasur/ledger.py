"""SQLite ledger for idempotent processing."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from bakasur.config import TIMEZONE
from bakasur.models import ApplicationRow, GazetteStatus, PlotRow

SCHEMA = """
CREATE TABLE IF NOT EXISTS gazettes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gazette_id TEXT NOT NULL UNIQUE,
    source_filename TEXT NOT NULL,
    pdf_path TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    artifact_dir TEXT,
    page_count INTEGER,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gazette_id TEXT NOT NULL,
    notification_no TEXT,
    page_start INTEGER NOT NULL,
    page_end INTEGER NOT NULL,
    variant TEXT,
    FOREIGN KEY (gazette_id) REFERENCES gazettes(gazette_id)
);

CREATE TABLE IF NOT EXISTS emitted_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    row_hash TEXT NOT NULL UNIQUE,
    gazette_id TEXT NOT NULL,
    notification_no TEXT,
    sr_no TEXT,
    emitted_at TEXT NOT NULL
);

-- Records waiting to be appended to Google Sheets; deleted once Sheets accepts them.
CREATE TABLE IF NOT EXISTS sheets_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gazettes_status ON gazettes(status);
CREATE INDEX IF NOT EXISTS idx_gazettes_sha256 ON gazettes(sha256);
CREATE INDEX IF NOT EXISTS idx_emitted_rows_hash ON emitted_rows(row_hash);
"""


class Ledger:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(TIMEZONE).isoformat()

    def has_sha256(self, sha256: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM gazettes WHERE sha256 = ?", (sha256,)
            ).fetchone()
            return row is not None

    def get_by_sha256(self, sha256: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM gazettes WHERE sha256 = ?", (sha256,)
            ).fetchone()

    def upsert_gazette(
        self,
        gazette_id: str,
        source_filename: str,
        pdf_path: str,
        sha256: str,
        status: GazetteStatus = GazetteStatus.PENDING,
    ) -> None:
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gazettes (
                    gazette_id, source_filename, pdf_path, sha256, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sha256) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    pdf_path = excluded.pdf_path
                """,
                (
                    gazette_id,
                    source_filename,
                    pdf_path,
                    sha256,
                    status.value,
                    now,
                    now,
                ),
            )
            conn.commit()

    def update_status(
        self,
        gazette_id: str,
        status: GazetteStatus,
        *,
        artifact_dir: str | None = None,
        page_count: int | None = None,
        error_message: str | None = None,
    ) -> None:
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE gazettes SET
                    status = ?,
                    artifact_dir = COALESCE(?, artifact_dir),
                    page_count = COALESCE(?, page_count),
                    error_message = ?,
                    updated_at = ?
                WHERE gazette_id = ?
                """,
                (
                    status.value,
                    artifact_dir,
                    page_count,
                    error_message,
                    now,
                    gazette_id,
                ),
            )
            conn.commit()

    def reset_stale_processing(self) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE gazettes SET status = ?, error_message = ?, updated_at = ?
                WHERE status = ?
                """,
                (
                    GazetteStatus.FAILED.value,
                    "Interrupted while processing",
                    self._now(),
                    GazetteStatus.PROCESSING.value,
                ),
            )
            conn.commit()
            return cur.rowcount

    def record_notification(
        self,
        gazette_id: str,
        notification_no: str | None,
        page_start: int,
        page_end: int,
        variant: str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO notifications (
                    gazette_id, notification_no, page_start, page_end, variant
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (gazette_id, notification_no, page_start, page_end, variant),
            )
            conn.commit()

    def is_row_emitted(self, row_hash: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM emitted_rows WHERE row_hash = ?", (row_hash,)
            ).fetchone()
            return row is not None

    def record_emitted_row(
        self,
        row_hash: str,
        gazette_id: str,
        notification_no: str | None,
        sr_no: str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO emitted_rows (
                    row_hash, gazette_id, notification_no, sr_no, emitted_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (row_hash, gazette_id, notification_no, sr_no, self._now()),
            )
            conn.commit()

    def record_emitted(
        self,
        items: Sequence[ApplicationRow | PlotRow],
        sheets_outbox: Sequence[tuple[str, dict[str, Any]]] = (),
    ) -> None:
        """Mark rows/plots as emitted and queue their Sheets records in one transaction."""
        now = self._now()
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO emitted_rows (
                    row_hash, gazette_id, notification_no, sr_no, emitted_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (i.row_hash, i.gazette_id, i.notification_no, i.sr_no, now)
                    for i in items
                ],
            )
            conn.executemany(
                "INSERT INTO sheets_outbox (kind, payload, created_at) VALUES (?, ?, ?)",
                [
                    (kind, json.dumps(payload, ensure_ascii=False), now)
                    for kind, payload in sheets_outbox
                ],
            )
            conn.commit()

    def pending_sheets(self) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return list(
                conn.execute(
                    "SELECT id, kind, payload FROM sheets_outbox ORDER BY id"
                ).fetchall()
            )

    def count_pending_sheets(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM sheets_outbox").fetchone()[0]

    def mark_sheets_done(self, ids: Sequence[int]) -> None:
        with self._connect() as conn:
            conn.executemany("DELETE FROM sheets_outbox WHERE id = ?", [(i,) for i in ids])
            conn.commit()

    def mark_sheets_failed(self, ids: Sequence[int], error: str) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                UPDATE sheets_outbox SET attempts = attempts + 1, last_error = ?
                WHERE id = ?
                """,
                [(error[:2000], i) for i in ids],
            )
            conn.commit()

    def list_gazettes(self, status: GazetteStatus | None = None) -> list[sqlite3.Row]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM gazettes WHERE status = ? ORDER BY created_at DESC",
                    (status.value,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM gazettes ORDER BY created_at DESC"
                ).fetchall()
            return list(rows)
