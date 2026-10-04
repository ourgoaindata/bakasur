"""Shared utilities."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slugify(text: str, max_len: int = 80) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", text.strip())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:max_len] or "gazette"


def parse_filename_metadata(filename: str) -> dict[str, str | None]:
    """Best-effort metadata from a gazette PDF filename."""
    meta: dict[str, str | None] = {
        "series": None,
        "issue_no": None,
        "gazette_date": None,
    }
    m = re.search(r"SIII[-_]?OG(\d+)", filename, re.I)
    if m:
        meta["issue_no"] = m.group(1)
        meta["series"] = "SIII"
    m = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
    if m:
        meta["gazette_date"] = m.group(1)
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})", filename)
    if m and not meta["gazette_date"]:
        meta["gazette_date"] = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return meta


def gazette_id_from_path(path: Path, sha256: str) -> str:
    stem = slugify(path.stem)
    return f"{stem}_{sha256[:12]}"
