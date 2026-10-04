from pathlib import Path

from bakasur.ledger import Ledger
from bakasur.models import GazetteStatus


def test_ledger_idempotency(tmp_path: Path):
    db = tmp_path / "test.db"
    ledger = Ledger(db)
    ledger.upsert_gazette("g1", "a.pdf", "/a.pdf", "sha1", GazetteStatus.PENDING)
    assert ledger.has_sha256("sha1")
    ledger.record_emitted_row("rowhash1", "g1", "n1", "1")
    assert ledger.is_row_emitted("rowhash1")
    assert not ledger.is_row_emitted("rowhash2")
