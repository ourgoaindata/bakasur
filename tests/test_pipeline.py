"""End-to-end pipeline test with inbox folder."""

import shutil
from pathlib import Path

import pytest

from bakasur.config import Settings
from bakasur.inbox.watcher import InboxWatcher

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DIGITAL = FIXTURES / (
    "2026-08-20_SIII-OG21_39A(59)-19th Aug 2026_(two 39As - new + new ndz).pdf"
)


@pytest.mark.slow
def test_inbox_pipeline_on_digital_fixture(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    cfg = Settings(
        data_dir=tmp_path,
        inbox_dir=inbox,
        processed_dir=tmp_path / "processed",
        failed_dir=tmp_path / "failed",
        gazettes_dir=tmp_path / "gazettes",
        out_dir=tmp_path / "out",
        db_path=tmp_path / "test.db",
        preprocess_scans=False,
        email_enabled=False,
    )
    dest = inbox / "test_gazette.pdf"
    shutil.copy(DIGITAL, dest)

    watcher = InboxWatcher(cfg)
    results = watcher.process_once()
    assert len(results) == 1
    assert results[0]["status"] in {"completed", "failed"}
    if results[0]["status"] == "completed":
        assert results[0].get("rows", 0) >= 0
        assert (tmp_path / "processed" / "test_gazette.pdf").exists()
