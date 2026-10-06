from docling.datamodel.pipeline_options import OcrMacOptions, RapidOcrOptions

from bakasur.config import Settings
from bakasur.parse.runner import build_ocr_options


def test_default_engine_is_rapidocr_without_line_classifier():
    opts = build_ocr_options(Settings())
    assert isinstance(opts, RapidOcrOptions)
    assert opts.use_cls is False


def test_ocrmac_is_still_selectable():
    assert isinstance(build_ocr_options(Settings(ocr_engine="ocrmac")), OcrMacOptions)
