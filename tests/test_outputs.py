"""Sheets outbox retries and email notifications."""

from pathlib import Path

import pytest

import bakasur.pipeline as pipeline_mod
from bakasur.config import Settings
from bakasur.models import ApplicationRow, GazetteStatus, TableVariant, ValidationIssue
from bakasur.notify.email import EmailNotifier
from bakasur.pipeline import Pipeline
from bakasur.sinks.sheets import SheetsSink


def _row(sr_no: str, survey: str | None = "74/1") -> ApplicationRow:
    row = ApplicationRow(
        gazette_id="g1",
        source_filename="g1.pdf",
        notification_no="N1",
        table_variant=TableVariant.CHANGE_OF_ZONE,
        sr_no=sr_no,
        applicant="A",
        survey_raw=survey,
        village="Guirdolim",
        taluka="Salcete",
        existing_use=None,
        total_area_sqm=None,
        proposed_use=None,
        area_proposed_sqm=None,
        decision="Recommended",
        page_from=1,
        page_to=1,
    )
    row.row_hash = f"hash-{sr_no}-{survey}"
    return row


class FakeSheets:
    enabled = True
    to_records = staticmethod(SheetsSink.to_records)

    def __init__(self) -> None:
        self.fail = False
        self.appended: dict[str, list[dict]] = {}

    def append_records(self, kind: str, records: list[dict]) -> None:
        if self.fail:
            raise ConnectionError("sheets down")
        self.appended.setdefault(kind, []).extend(records)


@pytest.fixture
def pipeline(tmp_path: Path, monkeypatch) -> Pipeline:
    cfg = Settings(
        data_dir=tmp_path,
        inbox_dir=tmp_path / "inbox",
        processed_dir=tmp_path / "processed",
        failed_dir=tmp_path / "failed",
        gazettes_dir=tmp_path / "gazettes",
        out_dir=tmp_path / "out",
        db_path=tmp_path / "test.db",
        email_enabled=False,
    )
    p = Pipeline(cfg)
    p.sheets = FakeSheets()
    # Skip PDF parsing: pretend artifacts exist and stub extraction.
    p.store.exists = lambda gid: True
    p.store.load_meta = lambda gid: {"page_count": 1}
    monkeypatch.setattr(pipeline_mod, "extract_39a_from_artifacts", lambda *a: ([], []))
    return p


def _drop_pdf(p: Pipeline, name: str = "g.pdf") -> Path:
    p.cfg.inbox_dir.mkdir(parents=True, exist_ok=True)
    pdf = p.cfg.inbox_dir / name
    pdf.write_bytes(name.encode())
    return pdf


def _set_rows(monkeypatch, rows: list[ApplicationRow]) -> None:
    monkeypatch.setattr(pipeline_mod, "extract_39a_from_artifacts", lambda *a: (rows, []))


def test_sheets_failure_queues_rows_and_retries(pipeline, monkeypatch):
    _set_rows(monkeypatch, [_row("1."), _row("2.")])
    pipeline.sheets.fail = True

    result = pipeline.process_pdf(_drop_pdf(pipeline))

    assert result["status"] == "completed"
    assert result["sheets_pending"] == 4  # 2 rows + 2 plots
    assert pipeline.sheets.appended == {}

    pipeline.sheets.fail = False
    sync = pipeline.sync_sheets()
    assert sync == {"pushed": 4, "pending": 0, "error": None}
    assert len(pipeline.sheets.appended["rows"]) == 2
    assert len(pipeline.sheets.appended["plots"]) == 2


def test_sheets_success_leaves_nothing_queued(pipeline, monkeypatch):
    _set_rows(monkeypatch, [_row("1.")])
    result = pipeline.process_pdf(_drop_pdf(pipeline))
    assert result["sheets_pending"] == 0
    assert pipeline.ledger.count_pending_sheets() == 0
    assert len(pipeline.sheets.appended["rows"]) == 1


def test_email_failure_does_not_fail_gazette(pipeline, monkeypatch):
    _set_rows(monkeypatch, [_row("1.")])

    def boom(*a, **k):
        raise OSError("smtp down")

    pipeline.email.send_digest = boom
    pipeline.email.send_failure = boom
    pdf = _drop_pdf(pipeline)

    result = pipeline.process_pdf(pdf)

    assert result["status"] == "completed"
    assert (pipeline.cfg.processed_dir / pdf.name).exists()
    gazette = pipeline.ledger.list_gazettes()[0]
    assert gazette["status"] == GazetteStatus.COMPLETED.value


def test_failure_email_error_does_not_crash(pipeline, monkeypatch):
    def broken(*a):
        raise ValueError("extract broke")

    monkeypatch.setattr(pipeline_mod, "extract_39a_from_artifacts", broken)
    pipeline.email.send_failure = lambda *a: (_ for _ in ()).throw(OSError("smtp down"))

    result = pipeline.process_pdf(_drop_pdf(pipeline))
    assert result["status"] == "failed"


def _capture(notifier: EmailNotifier) -> list[tuple[str, str]]:
    sent: list[tuple[str, str]] = []
    notifier._send = lambda subject, body: sent.append((subject, body))
    return sent


def test_digest_sent_when_all_rows_rejected():
    notifier = EmailNotifier(Settings(email_enabled=False))
    sent = _capture(notifier)
    bad = _row("3.", survey=None)
    notifier.send_digest(
        "g1", [], [ValidationIssue(row=bad, reason="Missing survey numbers")], extracted=1
    )
    assert len(sent) == 1
    subject, body = sent[0]
    assert "need review" in subject
    assert "Missing survey numbers" in body
    assert "Sr. 3." in body


def test_digest_sent_when_nothing_extracted():
    notifier = EmailNotifier(Settings(email_enabled=False))
    sent = _capture(notifier)
    notifier.send_digest("g1", [], [], extracted=0)
    assert len(sent) == 1
    assert "no rows found" in sent[0][0]


def test_no_digest_when_nothing_new():
    notifier = EmailNotifier(Settings(email_enabled=False))
    sent = _capture(notifier)
    notifier.send_digest("g1", [], [], extracted=5)
    assert sent == []


def test_digest_mentions_sheets_failure():
    notifier = EmailNotifier(Settings(email_enabled=False))
    sent = _capture(notifier)
    notifier.send_digest(
        "g1", [_row("1.")], [], extracted=1, sheets_pending=2, sheets_error="ConnectionError()"
    )
    assert "Google Sheets upload failed" in sent[0][1]
