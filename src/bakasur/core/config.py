"""
Settings every use case shares: OCR, the LLM endpoint, Google credentials and SMTP.

A use case subclasses ``CoreSettings`` to add its own fields (paths, patterns, sheet tabs),
so one ``.env`` file configures both and the env variable names stay the field names.
"""

from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

TIMEZONE = ZoneInfo("Asia/Kolkata")


class CoreSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Docling
    # rapidocr | ocrmac. On the 6 Aug 2026 gazette, RapidOCR kept every Sr. No. (ocrmac dropped
    # 9 of 33), read commas as commas and kept areas out of the land-use column; ~4x slower.
    ocr_engine: str = Field(default="rapidocr")
    rapidocr_backend: str = Field(default="torch")  # onnxruntime | openvino | paddle | torch
    ocr_scale: float = Field(default=4.0)
    # Otsu binarization of scanned pages. Off by default: on the 6 Aug 2026 gazette it made
    # OCR read commas as periods and pushed areas into the land-use column (194/253 vs 216/253).
    preprocess_scans: bool = Field(default=False)
    # Detect sideways / upside-down scanned pages and turn them upright before OCR. A table
    # printed sideways on a portrait page (MoM 274, p. 38) otherwise comes out as gibberish.
    fix_orientation: bool = Field(default=True)
    profile_timings: bool = Field(default=False)

    # LLM
    llm_provider: str = Field(default="heuristic")  # heuristic | ollama | openai_compat
    llm_model: str = Field(default="llama3.2")
    ollama_base_url: str = Field(default="http://localhost:11434")
    openai_compat_base_url: str = Field(default="")
    openai_compat_api_key: str = Field(default="")

    # Google
    google_service_account_file: Path | None = Field(default=None)

    # Email
    email_enabled: bool = Field(default=False)
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    email_from: str = Field(default="")
    email_to: list[str] = Field(default_factory=list)
