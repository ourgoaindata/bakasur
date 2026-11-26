"""
Non-Latin script on scanned pages: find Devanagari, judge what an Indic OCR made of it.

The GCZMA minutes carry Marathi/Konkani (Devanagari) only inside scanned images, mostly
occupant names copied from Form I & XIV records (MoM 518, p. 70). No PDF in the set uses an
Indic font or Unicode Devanagari in its text layer, so the text layer says nothing and
RapidOCR (Latin/Chinese models) drops these names or turns them into a few junk letters.

Detection is by shape, without OCR. A Devanagari word hangs from a flat headline (the
shirorekha) that runs the full width of the word, so after binarising the page each word is
one connected blob with a near-solid row across its top and stems hanging below. Latin text
almost never looks like that: its letters are separate blobs, and fused serif pairs ("rm")
are too short (the 2.3x width floor) or lack a full-width top row. Underlined words are
ruled out because their solid row is at the bottom. On the 579 GCZMA minutes (28,350 pages)
every page with two or more such words held Devanagari, checked by eye.

After an Indic OCR has read a flagged page, ``judge`` decides whether the read is usable:

- too little Devanagari came back: the script is not one the reader knows, so the page is
  flagged as unrecognised;
- Devanagari came back but almost without vowel signs: the source itself is garbled,
  English names typed in a Devanagari font ("फनतरहडस", MoM 415 p. 69). Real Marathi names
  carry a vowel sign on roughly half their letters (0.25-0.8 on the GCZMA pages); these
  garbled ones carry almost none (0.00-0.05).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pypdfium2 as pdfium

RENDER_DPI = 150
# Blob size, in pixels at RENDER_DPI, that a word of body text can have.
MIN_HEIGHT, MAX_HEIGHT = 12, 60
MIN_ASPECT, MAX_ASPECT = 2.3, 14.0
# A page with at least this many Devanagari-shaped words is routed to the Indic reader.
MIN_WORDS = 2
# Fewer Devanagari letters than this in the Indic read and the script was not recognised.
MIN_READ_LETTERS = 3
# Vowel signs per Devanagari letter below this, over at least GARBLE_MIN_LETTERS letters,
# means the source text is garbled.
GARBLE_SIGN_RATIO = 0.15
GARBLE_MIN_LETTERS = 8

_LETTER = re.compile(r"[ऄ-हक़-ॡॲ-ॿ]")
_SIGN = re.compile(r"[ँ-ःऺ-ॏॕ-ॗॢॣ]")

Status = Literal["indic_ocr", "garbled_source", "unrecognised", "not_read"]


@dataclass(frozen=True)
class PageScript:
    """
    What was found on one page with Devanagari-shaped words. ``status``:

    - ``indic_ocr``: read by the Indic reader; its text replaces Docling's for the page.
    - ``garbled_source``: read, but the Devanagari is garbled in the PDF itself.
    - ``unrecognised``: the Indic reader returned no Devanagari, so it is another script.
    - ``not_read``: no Indic reader was run (off, or it failed to load).
    """

    page_no: int
    devanagari_words: int
    status: Status
    markdown: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out.pop("markdown")
        return {k: v for k, v in out.items() if v is not None}

    def describe(self) -> str:
        return {
            "indic_ocr": "Devanagari, read with IndicOCR",
            "garbled_source": "Devanagari that is garbled in the source PDF",
            "unrecognised": "a non-Latin script IndicOCR could not read",
            "not_read": "Devanagari that was not read" + (f" ({self.error})" if self.error else ""),
        }[self.status]


def _is_devanagari_word(blob: np.ndarray) -> bool:
    h, w = blob.shape
    rows = blob.mean(axis=1)
    top = int(np.argmax(rows[: max(2, int(h * 0.45))]))
    if rows[top] < 0.8:
        return False
    # The headline must run (almost) unbroken across the whole word.
    line = blob[max(0, top - 1) : top + 2].any(axis=0)
    run = longest = 0
    for ink in line:
        run = run + 1 if ink else 0
        longest = max(longest, run)
    if longest < 0.85 * w:
        return False
    below = blob[top + 2 :]
    if below.shape[0] < h * 0.4:
        return False
    # At least two stems hang from it, and nothing solid sits at the bottom (an underline).
    lower = below[below.shape[0] // 3 :]
    stems = np.diff(np.r_[0, (lower.mean(axis=0) > 0.5).astype(int)]) == 1
    return int(stems.sum()) >= 2 and rows[int(h * 0.6) :].max() < 0.6


def count_devanagari_words(image) -> int:
    """Devanagari-shaped words on a page image (PIL), rendered at about RENDER_DPI."""
    import cv2

    gray = np.asarray(image.convert("L"))
    ink = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15
    )
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    words = 0
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        if MIN_HEIGHT <= h <= MAX_HEIGHT and MIN_ASPECT * h <= w <= MAX_ASPECT * h:
            if _is_devanagari_word(labels[y : y + h, x : x + w] == i):
                words += 1
    return words


def pages_with_images(pdf_path: Path) -> set[int]:
    """1-based numbers of the pages that hold any image; only those can carry Devanagari
    when, as in the GCZMA minutes, no Indic font is embedded."""
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        return {
            i + 1
            for i in range(len(doc))
            if next(doc[i].get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE], max_depth=3), None)
        }
    finally:
        doc.close()


def render_page(pdf_path: Path, page_no: int, dpi: int):
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        return doc[page_no - 1].render(scale=dpi / 72).to_pil()
    finally:
        doc.close()


def find_devanagari_pages(
    pdf_path: Path, pages: set[int] | None = None, min_words: int = MIN_WORDS
) -> dict[int, int]:
    """
    Page number -> Devanagari-shaped word count, for each page with at least ``min_words``.
    ``pages`` limits the check (default: every page that holds an image).
    """
    check = pages_with_images(pdf_path) if pages is None else pages
    found = {}
    for page_no in sorted(check):
        words = count_devanagari_words(render_page(pdf_path, page_no, RENDER_DPI))
        if words >= min_words:
            found[page_no] = words
    return found


def judge(text: str) -> Status:
    """Whether an Indic OCR read of a flagged page is usable (see the module docstring)."""
    letters = len(_LETTER.findall(text))
    if letters < MIN_READ_LETTERS:
        return "unrecognised"
    signs = len(_SIGN.findall(text))
    if letters >= GARBLE_MIN_LETTERS and signs / letters < GARBLE_SIGN_RATIO:
        return "garbled_source"
    return "indic_ocr"
