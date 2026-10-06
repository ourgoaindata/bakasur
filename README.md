<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo/bakasur-logo-dark.svg">
    <img src="assets/logo/bakasur-logo.svg" alt="Bakasur" width="360">
  </picture>
</p>

# Bakasur — Goa Gazette 39A Extractor

Watch an inbox folder for Goa Official Gazette PDFs, parse each once with Docling, extract Section 39A change-of-zone tables, append rows to Google Sheets, and email a digest.

## Setup

```bash
cd bakasur
uv sync --extra dev
```

Configure optional integrations in `.env`:

```env
GOOGLE_SERVICE_ACCOUNT_FILE=credentials/service_account.json
GOOGLE_SHEET_ID=...
LLM_PROVIDER=heuristic   # or ollama, openai_compat
EMAIL_ENABLED=false
```

## Usage

Drop a PDF into `data/inbox/`, then:

```bash
uv run bakasur run --once
uv run bakasur watch          # continuous polling
uv run bakasur status
uv run bakasur parse fixtures/your.pdf
uv run bakasur spike-parse fixtures/your.pdf --page-range 1-5
uv run bakasur extract-39a <gazette_id>
uv run bakasur chunk-rag <gazette_id>
uv run bakasur to-md any/file.pdf            # writes any/file.md; -o - for stdout
```

`to-md` converts any file Docling reads (PDF, images, docx, pptx, xlsx, html, ...) to Markdown,
OCRing scans with RapidOCR. Paginated inputs get a `[Page N]` marker before each page's content,
numbered as in the source file, so quotes can be checked against the original.

## How extraction works

See [docs/extraction-pipeline.md](docs/extraction-pipeline.md) for how 39A tables are stitched
across pages, how columns are mapped (heuristic first, optional local LLM), how continuation rows
are merged, and when records are held in the review queue instead of written to the sheet.

## Artifacts

Each gazette is stored under `data/gazettes/{gazette_id}/`:

- `docling.json` — canonical DoclingDocument (RAG-ready)
- `pages/*.txt` — per-page text
- `tables/*.json` — structured tables
- `meta.json` — metadata and timings

## Tests

```bash
uv run pytest
```
