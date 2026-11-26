"""Core never depends on a use case, and use cases never depend on each other."""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "bakasur"
USE_CASES = sorted(p.name for p in (SRC / "usecases").iterdir() if (p / "__init__.py").exists())


def _bakasur_imports(package: Path) -> dict[str, set[str]]:
    """file -> every bakasur module it imports, including inside functions."""
    out: dict[str, set[str]] = {}
    for path in package.rglob("*.py"):
        names: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module)
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
        out[str(path.relative_to(SRC))] = {n for n in names if n.split(".")[0] == "bakasur"}
    return out


def test_core_imports_only_core():
    leaks = {
        f: sorted(m for m in mods if not m.startswith("bakasur.core"))
        for f, mods in _bakasur_imports(SRC / "core").items()
    }
    assert {f: m for f, m in leaks.items() if m} == {}


@pytest.mark.parametrize("use_case", USE_CASES)
def test_use_case_imports_only_core_and_itself(use_case):
    own = f"bakasur.usecases.{use_case}"
    leaks = {
        f: sorted(m for m in mods if not (m.startswith("bakasur.core") or m.startswith(own)))
        for f, mods in _bakasur_imports(SRC / "usecases" / use_case).items()
    }
    assert {f: m for f, m in leaks.items() if m} == {}


def test_every_use_case_is_on_the_cli():
    from bakasur.cli import USE_CASES as registered

    modules = {app.registered_commands[0].callback.__module__.split(".")[2] for app in registered.values()}
    assert modules == set(USE_CASES)
