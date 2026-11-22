"""
Page orientation detection for scanned pages (OSD, without Tesseract).

Scans are often a portrait page holding a table printed sideways (MoM 274, page 38).
Docling reads such a page as it stands and the table comes out as gibberish, so each
scanned page is checked before conversion and turned upright when needed.

Two signals, both from RapidOCR, which is already used for OCR:

1. Line direction. Text detection alone (no recognition, low resolution) finds the text
   lines. On an upright or upside-down page nearly every elongated line box is wider than
   tall; on a page turned a quarter either way nearly every one is taller than wide.
2. Recognition score. The longest lines are cropped and read at the two remaining
   candidate angles; the angle that reads as more confident text wins. Recognition
   confidence alone cannot tell upright from sideways, because RapidOCR turns tall crops
   before reading them, so it is only used to choose within the pair from step 1.

Character shapes are not a separate signal: the recognition model is already a learned
character-shape classifier, so step 2 covers them.

When the signals disagree or are weak the result is marked uncertain, so the page can be
listed for a person to check:

- mixed line directions (neither clearly wide nor clearly tall): left as is;
- sideways, but the two directions read about equally well: the better-reading direction
  is still applied, since leaving a page known to be sideways guarantees a garbled read;
- upright vs upside down too close to call: left as is.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pypdfium2 as pdfium
from PIL import Image

# Rendering: detection is run at DET_DPI, line crops are read at REC_DPI.
DET_DPI = 75
REC_DPI = 150
# A box counts toward line direction only if its long side is this many times its short
# side; near-square boxes ("1", "-", stamps) say nothing about direction.
ELONGATION = 2.0
# Fewer elongated boxes than this and the page has too little text to judge.
MIN_LINES = 5
# Share of elongated boxes that are wide: at or above WIDE -> upright or upside down,
# at or below TALL -> sideways, in between -> mixed (uncertain).
WIDE = 0.7
TALL = 0.3
# How many of the longest lines are read to compare the two candidate angles.
SAMPLE_LINES = 20
# The better angle must score at least this many times the other to be certain.
MIN_SCORE_RATIO = 1.5
# Recognised text below this confidence does not count toward the score.
MIN_TEXT_SCORE = 0.5


@dataclass(frozen=True)
class Orientation:
    """
    How one page was found. ``rotation`` is the counter-clockwise turn, in degrees, that
    makes the page upright (0, 90, 180 or 270), and is what gets applied.
    """

    page_no: int
    rotation: int
    confident: bool
    reason: str
    lines: int = 0
    wide_share: float | None = None
    scores: dict[int, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["scores"] = {str(k): round(v, 1) for k, v in self.scores.items()}
        if self.wide_share is not None:
            out["wide_share"] = round(self.wide_share, 2)
        return out

    def describe(self) -> str:
        turn = f"rotated {self.rotation}° counter-clockwise" if self.rotation else "not rotated"
        status = "" if self.confident else "; orientation uncertain, check by hand"
        return f"{turn} ({self.reason}){status}"


def _engine_type(backend: str):
    from rapidocr import EngineType

    return EngineType(backend)


class OrientationDetector:
    """Builds the RapidOCR models once, on first use, and checks pages with them."""

    def __init__(self, backend: str = "torch"):
        self.backend = backend
        self._engine = None

    @property
    def engine(self):
        if self._engine is None:
            from rapidocr import RapidOCR

            engine = _engine_type(self.backend)
            self._engine = RapidOCR(
                params={
                    "Global.use_cls": False,
                    "Det.engine_type": engine,
                    "Rec.engine_type": engine,
                    "Cls.engine_type": engine,
                }
            )
        return self._engine

    def detect_page(self, page: pdfium.PdfPage, page_no: int) -> Orientation:
        image = page.render(scale=REC_DPI / 72.0).to_pil().convert("L")
        return self.detect_image(image, page_no)

    def detect_image(self, image: Image.Image, page_no: int = 1) -> Orientation:
        factor = DET_DPI / REC_DPI
        small = image.resize((max(1, round(image.width * factor)), max(1, round(image.height * factor))))
        det = self.engine(np.array(small.convert("RGB")), use_det=True, use_cls=False, use_rec=False)
        boxes = np.zeros((0, 4, 2)) if det.boxes is None else np.asarray(det.boxes, dtype=float)
        boxes = boxes / factor  # back to the coordinates of `image`

        widths = np.linalg.norm(boxes[:, 1] - boxes[:, 0], axis=1) if len(boxes) else np.zeros(0)
        heights = np.linalg.norm(boxes[:, 3] - boxes[:, 0], axis=1) if len(boxes) else np.zeros(0)
        long_side = np.maximum(widths, heights)
        short_side = np.maximum(np.minimum(widths, heights), 1e-6)
        elongated = long_side / short_side >= ELONGATION
        n_lines = int(elongated.sum())
        if n_lines < MIN_LINES:
            return Orientation(page_no, 0, True, "too little text to judge", lines=n_lines)

        wide_share = float((widths[elongated] > heights[elongated]).mean())
        if TALL < wide_share < WIDE:
            return Orientation(
                page_no, 0, False, "mixed line directions", lines=n_lines, wide_share=wide_share
            )

        candidates = (0, 180) if wide_share >= WIDE else (90, 270)
        order = np.argsort(-long_side * elongated)[: min(SAMPLE_LINES, n_lines)]
        crops = [_crop(image, boxes[i]) for i in order]
        scores = {angle: self._read_score(crops, angle) for angle in candidates}
        best, other = sorted(candidates, key=lambda a: scores[a], reverse=True)
        confident = scores[best] >= MIN_SCORE_RATIO * scores[other] and scores[best] > 0

        sideways = candidates == (90, 270)
        if confident:
            reason = "lines run vertically" if sideways else "lines run horizontally"
            if best == 180:
                reason += ", page is upside down"
            return Orientation(page_no, best, True, reason, n_lines, wide_share, scores)
        if sideways:
            return Orientation(
                page_no, best, False, "sideways, but the direction is unclear",
                n_lines, wide_share, scores,
            )
        return Orientation(
            page_no, 0, False, "upright vs upside down unclear", n_lines, wide_share, scores
        )

    def _read_score(self, crops: list[Image.Image], angle: int) -> float:
        total = 0.0
        for crop in crops:
            turned = crop.rotate(angle, expand=True) if angle else crop
            out = self.engine(np.array(turned.convert("RGB")), use_det=False, use_cls=False, use_rec=True)
            for text, score in zip(out.txts or (), out.scores or ()):
                if score >= MIN_TEXT_SCORE:
                    total += len(text.strip()) * float(score)
        return total


def _crop(image: Image.Image, box: np.ndarray, pad: int = 3) -> Image.Image:
    left, top = np.floor(box.min(axis=0)).astype(int) - pad
    right, bottom = np.ceil(box.max(axis=0)).astype(int) + pad
    return image.crop((max(0, left), max(0, top), min(image.width, right), min(image.height, bottom)))


def detect_orientations(
    pdf_path, page_indices: list[int], detector: OrientationDetector
) -> list[Orientation]:
    """Check the given zero-based pages; results carry one-based page numbers."""
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        return [detector.detect_page(doc[idx], idx + 1) for idx in page_indices]
    finally:
        doc.close()
