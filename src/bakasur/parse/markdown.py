"""Convert any Docling-supported file to Markdown, one at a time or a folder in a batch."""

from __future__ import annotations

import multiprocessing
import shutil
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any, Literal

from docling_core.types.doc import DoclingDocument

from bakasur.config import Settings
from bakasur.core.convert import Orientation, OrientationDetector, build_converter, convert
from bakasur.parse.artifacts import TRAVERSE_PICTURES


def page_marker(page_no: int) -> str:
    return f"[Page {page_no}]"


def orientation_note(o: Orientation) -> str:
    """
    A note under the page marker. A page turned with confidence gets an HTML comment, so it
    stays out of the rendered text; an uncertain one gets a visible line asking for a check.
    """
    if not o.confident:
        return f"> **Orientation uncertain:** page {o.describe()}. Check it against the PDF."
    return f"<!-- bakasur: page {o.describe()} before OCR -->"


def document_to_markdown(
    doc: DoclingDocument, orientations: Iterable[Orientation] = ()
) -> str:
    """
    Markdown with a page marker ahead of each page's content, numbered as in the source
    file, so text quoted from the Markdown can be checked against the original.
    Formats without pages (docx, html, ...) are exported without markers. Pages that were
    turned upright, or whose orientation is uncertain, get a note under their marker.
    """
    if not doc.pages:
        return doc.export_to_markdown(traverse_pictures=TRAVERSE_PICTURES)
    notes = {o.page_no: orientation_note(o) for o in orientations if o.rotation or not o.confident}
    sections = []
    for page_no in sorted(doc.pages):
        body = doc.export_to_markdown(page_no=page_no, traverse_pictures=TRAVERSE_PICTURES)
        head = page_marker(page_no)
        if page_no in notes:
            head += f"\n\n{notes[page_no]}"
        sections.append(f"{head}\n\n{body}".rstrip())
    return "\n\n---\n\n".join(sections) + "\n"


def convert_file(
    converter: Any,
    path: Path,
    cfg: Settings,
    *,
    page_range: tuple[int, int] | None = None,
    detector: OrientationDetector | None = None,
) -> tuple[str, list[Orientation]]:
    """Markdown for one file, plus what the orientation check found on its scanned pages."""
    converted = convert(path, cfg, converter=converter, page_range=page_range, detector=detector)
    return document_to_markdown(converted.document, converted.orientations), converted.orientations


def convert_to_markdown(
    path: Path,
    cfg: Settings,
    *,
    force_ocr: bool = False,
    page_range: tuple[int, int] | None = None,
) -> str:
    return convert_to_markdown_with_orientation(
        path, cfg, force_ocr=force_ocr, page_range=page_range
    )[0]


def convert_to_markdown_with_orientation(
    path: Path,
    cfg: Settings,
    *,
    force_ocr: bool = False,
    page_range: tuple[int, int] | None = None,
) -> tuple[str, list[Orientation]]:
    converter = build_converter(cfg, force_ocr=force_ocr)
    return convert_file(converter, path, cfg, page_range=page_range)


@dataclass
class BatchResult:
    path: Path
    status: Literal["converted", "skipped", "failed"]
    seconds: float = 0.0
    chars: int = 0
    error: str | None = None
    orientations: list[Orientation] = field(default_factory=list)

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
    conn: Connection, make_converter: Callable[..., Any], cfg: Settings, force_ocr: bool
) -> None:
    converter = make_converter(cfg, force_ocr=force_ocr)
    detector = OrientationDetector(cfg.rapidocr_backend)  # models load on first scanned page
    while (path := conn.recv()) is not None:
        try:
            markdown, orientations = convert_file(converter, path, cfg, detector=detector)
            conn.send((markdown, orientations, None))
        except Exception as exc:
            conn.send((None, [], f"{type(exc).__name__}: {exc}"))


class _Worker:
    """
    A child process that builds the converter once and converts files on request.
    Docling intermittently segfaults on some scans (MoM 029 crashed 2 of 3 runs), which
    no try/except can catch; in a child the crash costs one file, not the whole batch.
    """

    def __init__(self, make_converter: Callable[..., Any], cfg: Settings, force_ocr: bool):
        ctx = multiprocessing.get_context("spawn")  # fork is unsafe with torch on macOS
        self.conn, child = ctx.Pipe()
        self.proc = ctx.Process(
            target=_worker_main, args=(child, make_converter, cfg, force_ocr), daemon=True
        )
        self.proc.start()
        child.close()  # so recv() raises EOFError when the child dies

    def convert(self, path: Path) -> tuple[str, list[Orientation]]:
        try:
            self.conn.send(path)
            markdown, orientations, error = self.conn.recv()
        except (EOFError, BrokenPipeError, ConnectionResetError):
            self.proc.join()
            code = self.proc.exitcode
            how = f"signal {-code}" if code is not None and code < 0 else f"exit code {code}"
            raise WorkerCrashed(f"converter process died ({how})") from None
        if error:
            raise RuntimeError(error)
        return markdown, orientations

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
    cfg: Settings,
    *,
    force_ocr: bool = False,
    overwrite: bool = False,
    on_result: Callable[[BatchResult], None] | None = None,
) -> list[BatchResult]:
    """
    Convert each file to ``out_dir/<stem>/<stem>.md``, copying the source next to it.
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
                            markdown, orientations = worker.convert(path)
                            break
                        except WorkerCrashed:
                            worker.close()
                            worker = None
                            if attempt == 2:
                                raise
                    # Rename into place so an interrupted run never leaves a partial file
                    # that the next run would mistake for a finished one.
                    tmp_path = md_path.with_name(md_path.name + ".tmp")
                    tmp_path.write_text(markdown, encoding="utf-8")
                    tmp_path.replace(md_path)
                    result = BatchResult(
                        path,
                        "converted",
                        seconds=time.monotonic() - started,
                        chars=len(markdown),
                        orientations=orientations,
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
