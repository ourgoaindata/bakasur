"""
One folder per converted document: the source, docling.json, per-page text, tables as JSON,
Markdown and meta.json. Use cases read these back instead of reconverting.
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
from docling_core.types.doc import (
    DocItemLabel,
    DoclingDocument,
    ImageRefMode,
    TableItem,
    TextItem,
)

from bakasur.core.export.markdown import TRAVERSE_PICTURES

if TYPE_CHECKING:
    from bakasur.core.convert.orientation import Orientation

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
    """``root/<doc_id>/``; the caller picks the id and adds its own fields to meta.json."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def doc_dir(self, doc_id: str) -> Path:
        path = self.root / doc_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(
        self,
        doc_id: str,
        source: Path,
        doc: DoclingDocument,
        *,
        sha256: str,
        timings: dict[str, Any] | None = None,
        scanned_pages: dict[int, bool] | None = None,
        page_orientation: list[Orientation] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """
        Write every artifact for ``doc``. ``metadata`` holds the use case's own fields
        (an id key, issue details, ...), written at the top level of meta.json.
        """
        gdir = self.doc_dir(doc_id)
        raw = gdir / f"raw{source.suffix.lower()}"
        if not raw.exists():
            raw.write_bytes(source.read_bytes())

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

        meta = {
            **(metadata or {}),
            "source_filename": source.name,
            "sha256": sha256,
            "page_count": doc.num_pages(),
            "extra": {
                "docling_version": importlib_metadata.version("docling"),
                "docling_core_version": importlib_metadata.version("docling-core"),
                "timings": timings or {},
                "scanned_pages": scanned_pages or {},
                # Only image-based pages are checked; uncertain ones need a look by hand.
                "page_orientation": [o.to_dict() for o in page_orientation or []],
            },
        }
        (gdir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return gdir

    def load_doc(self, doc_id: str) -> DoclingDocument:
        path = self.doc_dir(doc_id) / "docling.json"
        return DoclingDocument.load_from_json(path)

    def load_meta(self, doc_id: str) -> dict[str, Any]:
        path = self.doc_dir(doc_id) / "meta.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def load_page_texts(self, doc_id: str) -> dict[int, str]:
        pages_dir = self.doc_dir(doc_id) / "pages"
        out: dict[int, str] = {}
        for path in sorted(pages_dir.glob("*.txt")):
            page_no = int(path.stem)
            out[page_no] = path.read_text(encoding="utf-8")
        return out

    def load_tables(self, doc_id: str) -> list[dict[str, Any]]:
        tables_dir = self.doc_dir(doc_id) / "tables"
        tables: list[dict[str, Any]] = []
        for path in sorted(tables_dir.glob("t*.json")):
            tables.append(json.loads(path.read_text(encoding="utf-8")))
        return tables

    def exists(self, doc_id: str) -> bool:
        return (self.doc_dir(doc_id) / "docling.json").exists()
