"""Artifact store writer and reader."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd
from docling_core.types.doc import (
    DocItemLabel,
    DoclingDocument,
    ImageRefMode,
    TableItem,
    TextItem,
)

from bakasur.models import GazetteMetadata
from bakasur.utils import parse_filename_metadata

TRAVERSE_PICTURES = True
_FURNITURE_LABELS = {DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER}


def _table_neighbour_text(doc: DoclingDocument) -> dict[str, tuple[list[str], list[str]]]:
    """Same-page body text between each table and the adjacent table or page edge."""
    by_page: dict[int, list[TableItem | TextItem]] = {}
    for item, _level in doc.iterate_items(with_groups=False):
        if not item.prov:
            continue
        is_text = (
            isinstance(item, TextItem)
            and item.label not in _FURNITURE_LABELS
            and item.text.strip()
        )
        if isinstance(item, TableItem) or is_text:
            by_page.setdefault(item.prov[0].page_no, []).append(item)

    out: dict[str, tuple[list[str], list[str]]] = {}
    for items in by_page.values():
        for k, item in enumerate(items):
            if not isinstance(item, TableItem):
                continue
            before: list[str] = []
            for prev in reversed(items[:k]):
                if isinstance(prev, TableItem):
                    break
                before.insert(0, prev.text)
            after: list[str] = []
            for nxt in items[k + 1 :]:
                if isinstance(nxt, TableItem):
                    break
                after.append(nxt.text)
            out[item.self_ref] = (before, after)
    return out


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def gazette_dir(self, gazette_id: str) -> Path:
        path = self.root / gazette_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(
        self,
        gazette_id: str,
        source_pdf: Path,
        doc: DoclingDocument,
        *,
        sha256: str,
        timings: dict[str, Any] | None = None,
        scanned_pages: dict[int, bool] | None = None,
    ) -> Path:
        gdir = self.gazette_dir(gazette_id)
        raw = gdir / "raw.pdf"
        if not raw.exists():
            raw.write_bytes(source_pdf.read_bytes())

        images_dir = gdir / "images"
        images_dir.mkdir(exist_ok=True)
        docling_json = gdir / "docling.json"
        doc.save_as_json(
            docling_json,
            artifacts_dir=images_dir,
            image_mode=ImageRefMode.REFERENCED,
        )

        pages_dir = gdir / "pages"
        pages_dir.mkdir(exist_ok=True)
        for page_no in sorted(doc.pages.keys()):
            text = doc.export_to_text(page_no=page_no, traverse_pictures=TRAVERSE_PICTURES)
            (pages_dir / f"{page_no:04d}.txt").write_text(text, encoding="utf-8")

        tables_dir = gdir / "tables"
        tables_dir.mkdir(exist_ok=True)
        neighbour_text = _table_neighbour_text(doc)
        for idx, table in enumerate(doc.tables):
            df = table.export_to_dataframe(doc=doc)
            # Docling moves column-header rows out of the data and into df.columns.
            header = None if isinstance(df.columns, pd.RangeIndex) else [str(c) for c in df.columns]
            text_before, text_after = neighbour_text.get(table.self_ref, ([], []))
            prov = table.prov[0] if table.prov else None
            payload = {
                "index": idx,
                "page_no": prov.page_no if prov else None,
                "bbox": {
                    "l": prov.bbox.l,
                    "t": prov.bbox.t,
                    "r": prov.bbox.r,
                    "b": prov.bbox.b,
                }
                if prov
                else None,
                "n_rows": int(df.shape[0]),
                "n_cols": int(df.shape[1]),
                "header": header,
                "grid": df.fillna("").astype(str).values.tolist(),
                "text_before": text_before,
                "text_after": text_after,
            }
            (tables_dir / f"t{idx:04d}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        md_path = gdir / "document.md"
        md_path.write_text(
            doc.export_to_markdown(traverse_pictures=TRAVERSE_PICTURES),
            encoding="utf-8",
        )

        fn_meta = parse_filename_metadata(source_pdf.name)
        meta = GazetteMetadata(
            gazette_id=gazette_id,
            source_filename=source_pdf.name,
            sha256=sha256,
            page_count=doc.num_pages(),
            series=fn_meta.get("series"),
            issue_no=fn_meta.get("issue_no"),
            gazette_date=fn_meta.get("gazette_date"),
            extra={
                "docling_version": importlib_metadata.version("docling"),
                "docling_core_version": importlib_metadata.version("docling-core"),
                "timings": timings or {},
                "scanned_pages": scanned_pages or {},
            },
        )
        (gdir / "meta.json").write_text(
            json.dumps(asdict(meta), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return gdir

    def load_doc(self, gazette_id: str) -> DoclingDocument:
        path = self.gazette_dir(gazette_id) / "docling.json"
        return DoclingDocument.load_from_json(path)

    def load_meta(self, gazette_id: str) -> dict[str, Any]:
        path = self.gazette_dir(gazette_id) / "meta.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def load_page_texts(self, gazette_id: str) -> dict[int, str]:
        pages_dir = self.gazette_dir(gazette_id) / "pages"
        out: dict[int, str] = {}
        for path in sorted(pages_dir.glob("*.txt")):
            page_no = int(path.stem)
            out[page_no] = path.read_text(encoding="utf-8")
        return out

    def load_tables(self, gazette_id: str) -> list[dict[str, Any]]:
        tables_dir = self.gazette_dir(gazette_id) / "tables"
        tables: list[dict[str, Any]] = []
        for path in sorted(tables_dir.glob("t*.json")):
            tables.append(json.loads(path.read_text(encoding="utf-8")))
        return tables

    def exists(self, gazette_id: str) -> bool:
        return (self.gazette_dir(gazette_id) / "docling.json").exists()
