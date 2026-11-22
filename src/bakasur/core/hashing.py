"""Content hashes and stable ids for source files."""

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
    return slug[:max_len] or "document"


def doc_id_from_path(path: Path, sha256: str) -> str:
    """``<slugified stem>_<first 12 hex of the file's sha256>``: readable and unique."""
    return f"{slugify(path.stem)}_{sha256[:12]}"
