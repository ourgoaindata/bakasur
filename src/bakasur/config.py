"""Application configuration."""

from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Paths
    data_dir: Path = Field(default=Path("data"))
    inbox_dir: Path = Field(default=Path("data/inbox"))
    processed_dir: Path = Field(default=Path("data/processed"))
    failed_dir: Path = Field(default=Path("data/failed"))
    gazettes_dir: Path = Field(default=Path("data/gazettes"))
    out_dir: Path = Field(default=Path("data/out"))
    db_path: Path = Field(default=Path("bakasur.db"))

    # Watcher
    poll_interval_seconds: float = Field(default=5.0)

    # Docling
    parse_batch_size: int = Field(default=20)
    ocr_scale: float = Field(default=4.0)
    preprocess_scans: bool = Field(default=True)
    profile_timings: bool = Field(default=False)

    # 39A anchors
    anchor_patterns: list[str] = Field(
        default=[
            r"Section\s+39A",
            r"39A/Notification",
            r"change of zone",
            r"No Development Zone",
        ]
    )
    span_end_patterns: list[str] = Field(
        default=[
            r"And whereas, in terms of sub-rule \(1\) of rule 4",
            r"Department of Town & Country Planning",
        ]
    )
    # Page furniture ignored when deciding whether text surrounds a table
    running_text_patterns: list[str] = Field(
        default=[
            r"^OFFICIAL\s+GAZETTE\s*[-—–]\s*GOVT",
            r"^SERIES\s+[IVX]+\s+No\.?\s*\d+",
            r"^\d{1,2}\s*(ST|ND|RD|TH)\s+[A-Z]+,?\s+\d{4}$",
            r"^\d{1,5}$",
        ]
    )

    # LLM
    llm_provider: str = Field(default="heuristic")  # heuristic | ollama | openai_compat
    llm_model: str = Field(default="llama3.2")
    ollama_base_url: str = Field(default="http://localhost:11434")
    openai_compat_base_url: str = Field(default="")
    openai_compat_api_key: str = Field(default="")

    # Google Sheets
    google_service_account_file: Path | None = Field(default=None)
    google_sheet_id: str = Field(default="")
    sheet_tab_rows: str = Field(default="rows_as_printed")
    sheet_tab_plots: str = Field(default="plots_exploded")
    sheet_tab_review: str = Field(default="review_queue")

    # Email
    email_enabled: bool = Field(default=False)
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    email_from: str = Field(default="")
    email_to: list[str] = Field(default_factory=list)

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.inbox_dir,
            self.processed_dir,
            self.failed_dir,
            self.gazettes_dir,
            self.out_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings()

TIMEZONE = ZoneInfo("Asia/Kolkata")
