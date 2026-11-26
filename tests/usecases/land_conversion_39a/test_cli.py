"""The 39A sub-app, and the old top-level names kept for existing scripts."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from bakasur.cli import app


@pytest.mark.parametrize("args", [["39a", "status"], ["status"]])
def test_status_under_new_and_old_names(args, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ledger.db"))
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "Gazettes" in result.output


def test_old_names_are_hidden_from_help():
    result = CliRunner().invoke(app, ["--help"])
    assert "39a" in result.output and "mom" in result.output
    assert "export-master" not in result.output
