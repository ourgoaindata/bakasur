"""
Convert a folder of files to Markdown in a worker process that loads the models once and
survives native crashes.
"""

from __future__ import annotations

import json
import multiprocessing
import shutil
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any, Literal

from bakasur.core.config import CoreSettings
from bakasur.core.convert import (
    Orientation,
    OrientationDetector,
    PageScript,
    build_converter,
    build_indic_reader,
)
from bakasur.core.export.markdown import MarkdownResult, convert_file


@dataclass
class BatchResult:
    path: Path
    status: Literal["converted", "skipped", "failed"]
    seconds: float = 0.0
    chars: int = 0
    error: str | None = None
    orientations: list[Orientation] = field(default_factory=list)
    scripts: list[PageScript] = field(default_factory=list)

    def script_summary(self) -> str:
        """e.g. 'IndicOCR p70; garbled Devanagari p48', or '' when nothing to say."""
        labels = {
            "indic_ocr": "IndicOCR",
            "garbled_source": "garbled Devanagari",
            "unrecognised": "unrecognised script",
            "not_read": "Devanagari not read",
        }
        parts = []
        for status, label in labels.items():
            pages = [s.page_no for s in self.scripts if s.status == status]
            if pages:
                parts.append(label + " " + ", ".join(f"p{n}" for n in pages))
        return "; ".join(parts)

    def orientation_summary(self) -> str:
        """e.g. 'rotated p38; orientation uncertain p12, p14', or '' when nothing to say."""
        parts = []
        rotated = [o.page_no for o in self.orientations if o.rotation and o.confident]
        uncertain = [o.page_no for o in self.orientations if not o.confident]
        if rotated:
            parts.append("rotated " + ", ".join(f"p{n}" for n in rotated))
        if uncertain:
            parts.append("orientation uncertain " + ", ".join(f"p{n}" for n in uncertain))
        return "; ".join(parts)


class WorkerCrashed(RuntimeError):
    """The conversion process died, e.g. a segfault in native OCR/layout code."""


def _worker_main(
    conn: Connection, make_converter: Callable[..., Any], cfg: CoreSettings, force_ocr: bool
) -> None:
    converter = make_converter(cfg, force_ocr=force_ocr)
    detector = OrientationDetector(cfg.rapidocr_backend)  # models load on first scanned page
    reader = build_indic_reader(cfg)  # loads on the first page with Devanagari
    while (path := conn.recv()) is not None:
        try:
            result = convert_file(converter, path, cfg, detector=detector, indic_reader=reader)
            conn.send((result, None))
        except Exception as exc:
            conn.send((None, f"{type(exc).__name__}: {exc}"))


class _Worker:
    """
    A child process that builds the converter once and converts files on request.
    Docling intermittently segfaults on some scans (MoM 029 crashed 2 of 3 runs), which
    no try/except can catch; in a child the crash costs one file, not the whole batch.
    """

    def __init__(self, make_converter: Callable[..., Any], cfg: CoreSettings, force_ocr: bool):
        ctx = multiprocessing.get_context("spawn")  # fork is unsafe with torch on macOS
        self.conn, child = ctx.Pipe()
        self.proc = ctx.Process(
            target=_worker_main, args=(child, make_converter, cfg, force_ocr), daemon=True
        )
        self.proc.start()
        child.close()  # so recv() raises EOFError when the child dies

    def convert(self, path: Path) -> MarkdownResult:
        try:
            self.conn.send(path)
            result, error = self.conn.recv()
        except (EOFError, BrokenPipeError, ConnectionResetError):
            self.proc.join()
            code = self.proc.exitcode
            how = f"signal {-code}" if code is not None and code < 0 else f"exit code {code}"
            raise WorkerCrashed(f"converter process died ({how})") from None
        if error:
            raise RuntimeError(error)
        return result

    def close(self) -> None:
        if self.proc.is_alive():
            try:
                self.conn.send(None)
            except OSError:
                pass
            self.proc.join(timeout=10)
            if self.proc.is_alive():
                self.proc.kill()
        self.conn.close()


def convert_directory(
    files: Iterable[Path],
    out_dir: Path,
    cfg: CoreSettings,
    *,
    force_ocr: bool = False,
    overwrite: bool = False,
    on_result: Callable[[BatchResult], None] | None = None,
) -> list[BatchResult]:
    """
    Convert each file to ``out_dir/<stem>/<stem>.md``, copying the source next to it, with
    ``<stem>.meta.json`` beside it listing pages turned upright and pages with Devanagari.
    The converter (and its models) is built once, in a worker process; a file that already
    has a non-empty Markdown is skipped unless ``overwrite``, so an interrupted run can be
    resumed. A file that fails is reported and does not stop the rest. If the worker
    crashes, a fresh one retries the file once before it is reported as failed.
    """
    # Looked up at call time so tests can swap in a stub factory.
    make_converter = build_converter
    worker: _Worker | None = None
    results: list[BatchResult] = []
    try:
        for path in files:
            folder = out_dir / path.stem
            md_path = folder / f"{path.stem}.md"
            started = time.monotonic()
            try:
                if not overwrite and md_path.exists() and md_path.stat().st_size > 0:
                    result = BatchResult(path, "skipped")
                else:
                    folder.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, folder / path.name)
                    for attempt in (1, 2):
                        worker = worker or _Worker(make_converter, cfg, force_ocr)
                        try:
                            converted = worker.convert(path)
                            break
                        except WorkerCrashed:
                            worker.close()
                            worker = None
                            if attempt == 2:
                                raise
                    # Rename into place so an interrupted run never leaves a partial file
                    # that the next run would mistake for a finished one.
                    # The meta goes first, so a finished Markdown always has its meta.
                    meta_path = folder / f"{path.stem}.meta.json"
                    meta = json.dumps(converted.meta(), ensure_ascii=False, indent=2)
                    meta_path.write_text(meta + "\n", encoding="utf-8")
                    tmp_path = md_path.with_name(md_path.name + ".tmp")
                    tmp_path.write_text(converted.markdown, encoding="utf-8")
                    tmp_path.replace(md_path)
                    result = BatchResult(
                        path,
                        "converted",
                        seconds=time.monotonic() - started,
                        chars=len(converted.markdown),
                        orientations=converted.orientations,
                        scripts=converted.scripts,
                    )
            except Exception as exc:  # one bad file must not stop a long batch
                result = BatchResult(
                    path,
                    "failed",
                    seconds=time.monotonic() - started,
                    error=f"{type(exc).__name__}: {exc}",
                )
            results.append(result)
            if on_result:
                on_result(result)
    finally:
        if worker:
            worker.close()
    return results
