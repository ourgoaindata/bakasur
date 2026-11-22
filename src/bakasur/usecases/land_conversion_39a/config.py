"""Settings for the Section 39A land-conversion use case."""

from pathlib import Path

from pydantic import Field

from bakasur.core.config import CoreSettings


class Settings(CoreSettings):
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
            r"^OFFICIAL\s+GAZETTE\s*[-—–]?\s*GOVT",  # OCR sometimes drops the dash
            r"^SERIES\s+[IVX]+\s+No\.?\s*\d+",
            r"^\d{1,2}\s*(ST|ND|RD|TH)\s+[A-Z]+,?\s+\d{4}$",
            r"^\d{1,5}$",
            r"^Suggestions\s+are\s+welcomed\s+on\s+e-?mail\b",  # footer on every page
            r"^TABLE$",  # the table's caption, which Docling can place after the table
        ]
    )

    # Google Sheets
    google_sheet_id: str = Field(default="")
    sheet_tab_rows: str = Field(default="rows_as_printed")
    sheet_tab_plots: str = Field(default="plots_exploded")
    sheet_tab_review: str = Field(default="review_queue")

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
