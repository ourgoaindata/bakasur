"""
IndicOCR (Bodhan AI / AI4Bharat, https://huggingface.co/bodhan-ai/indic-ocr) for pages that
carry Devanagari, which RapidOCR cannot read.

A layout model finds and orders the blocks, a 0.8B vision-language model transcribes each
one, and the page comes back as Markdown (tables as HTML). It reads English and the 22
scheduled Indian languages on one page, so a mostly-English page with a few Marathi names
(MoM 518, p. 70) is read whole. On an M1 Pro it takes about 40 s a page on the GPU (MPS),
which is why only pages flagged by ``script.find_devanagari_pages`` are sent to it.

The model is gated: accept its licence on Hugging Face and log in (``hf auth login``), or
point ``INDIC_OCR_PATH`` at a downloaded snapshot. Its code ships inside the snapshot, so
nothing extra is installed; it needs transformers>=5.7 and torchvision, which Docling's VLM
extra already brings.
"""

from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ID = "bodhan-ai/indic-ocr"
# Rendering for the reader. Its layout model resizes internally; 200 dpi keeps small
# Devanagari matras legible in the block crops.
RENDER_DPI = 200


def _device(name: str) -> str:
    if name != "auto":
        return name
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def clean_markdown(text: str) -> str:
    """The plain-transformers decoder leaves SentencePiece space marks (U+2581) in place."""
    return text.replace("▁", " ").strip()


class IndicReader:
    """Loads IndicOCR on first use, then reads page images to Markdown."""

    def __init__(self, path: Path | None = None, device: str = "auto"):
        self.path = path
        self.device = device
        self._parser: Any = None

    def _load(self) -> Any:
        if self._parser is None:
            if self.path is not None:
                snapshot = Path(self.path)
            else:
                from huggingface_hub import snapshot_download

                snapshot = Path(snapshot_download(REPO_ID))
            if str(snapshot) not in sys.path:
                sys.path.insert(0, str(snapshot))  # the model's code ships in the snapshot
            from indic_ocr import IndicOCR

            device = _device(self.device)
            logger.info("loading IndicOCR from %s on %s", snapshot, device)
            self._parser = IndicOCR.from_pretrained(snapshot, device=device)
        return self._parser

    def read(self, image) -> str:
        """Markdown for one page image (PIL)."""
        parser = self._load()
        with tempfile.TemporaryDirectory(prefix="bakasur-indic-") as tmp:
            png = Path(tmp) / "page.png"  # the parser takes a path, not an image
            image.convert("RGB").save(png)
            page = parser.parse(str(png))
        return clean_markdown(page["markdown"])
