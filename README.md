<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo/bakasur-logo-dark.svg">
    <img src="assets/logo/bakasur-logo.svg" alt="Bakasur" width="360">
  </picture>
</p>


Parse Goa government documents with Docling. A shared core converts PDFs, scans and office
files (OCR, sideways-page correction, Markdown with page markers, artifact folders); each
document type is a use case built on it:

- **39A land conversions** (`bakasur 39a ...`): watch an inbox folder for Official Gazette PDFs,
  parse each once, extract Section 39A change-of-zone tables, append rows to Google Sheets, and
  email a digest.
- **GCZMA minutes** (`bakasur mom ...`): convert the Coastal Zone Management Authority's Minutes
  of Meetings to Markdown.

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

Any document:

```bash
uv run bakasur to-md any/file.pdf            # writes any/file.md; -o - for stdout
uv run bakasur to-md-batch in_dir -o out_dir # out_dir/<name>/<name>.pdf + <name>.md for each *.pdf
uv run bakasur chunk-rag data/gazettes/<id>  # an artifact folder or its docling.json
uv run bakasur spike-parse fixtures/your.pdf --page-range 1-5
```

39A land conversions. Drop a PDF into `data/inbox/`, then:

```bash
uv run bakasur 39a run --once
uv run bakasur 39a watch          # continuous polling
uv run bakasur 39a status
uv run bakasur 39a parse fixtures/your.pdf
uv run bakasur 39a extract <gazette_id>
uv run bakasur 39a export-master <gazette_id>   # data/out/<gazette_id>.master.csv
uv run bakasur 39a sync-sheets
```

The pre-reorganisation names (`bakasur run`, `status`, `parse`, `extract-39a`, `export-master`,
`sync-sheets`, `watch`) still work but are hidden from `--help`.

GCZMA minutes:

```bash
uv run bakasur mom convert mom_pdfs/ -o mom_md/   # every MoM*.pdf, like to-md-batch
```

`to-md` converts any file Docling reads (PDF, images, docx, pptx, xlsx, html, ...) to Markdown,
OCRing scans (RapidOCR by default; `OCR_ENGINE=ocrmac` for Apple Vision). Paginated inputs get
a `[Page N]` marker before each page's content, numbered as in the source file, so quotes can be
checked against the original. A paragraph that runs over a page break is split at the break, so its
continuation sits under the next page's marker rather than the page it started on.

`to-md-batch` does the same for every file matching `--glob` (default `*.pdf`) in a folder,
loading the models once. Each file gets its own `<out_dir>/<name>/` folder holding a copy of the
source and its Markdown. Finished files are skipped on a re-run (`--overwrite` redoes them), a
failing file doesn't stop the batch, and progress is also appended to `<out_dir>/_batch.log`.

Before OCR, every image-based PDF page (including scans that carry their own OCR text layer)
is checked for orientation, and pages scanned sideways or upside down are turned upright, so a
table printed landscape on a portrait page is read properly. Detection uses RapidOCR: the
direction of the detected text lines says upright vs sideways, and reading the longest lines at
the candidate angles picks the direction. Turned pages get an HTML comment under their
`[Page N]` marker. Pages the check is unsure about get a visible
`> **Orientation uncertain:**` line and are listed on stderr, in `_batch.log`, and in the
artifact `meta.json` (`page_orientation`), for a check by hand. Set `FIX_ORIENTATION=false` to
turn the check off. See [orientation.py](src/bakasur/core/convert/orientation.py) for the thresholds.

`to-md` and `to-md-batch` also look for Devanagari (Marathi/Konkani) on image pages, which
RapidOCR cannot read: in the GCZMA minutes, occupant names from Form I & XIV come out blank or as
junk letters. The check is by shape, without OCR (Devanagari words hang from a flat headline), and
a flagged page is read with [IndicOCR](https://huggingface.co/bodhan-ai/indic-ocr), whose text
replaces Docling's for that page. Each flagged page gets a note under its `[Page N]` marker, a line
in `_batch.log`, and an entry in `<name>.meta.json` next to the Markdown:

- read with IndicOCR: an HTML comment;
- `> **Garbled Devanagari:**`: the PDF itself holds English typed in a Devanagari font;
- `> **Unrecognised script:**`: IndicOCR returned no Devanagari, so it is some other script;
- `> **Devanagari not read:**`: IndicOCR is off or failed to load; Docling's text is kept.

IndicOCR is gated: accept its licence on Hugging Face and run `hf auth login` (the first flagged
page downloads 1.9 GB), or set `INDIC_OCR_PATH` to a downloaded snapshot. It takes about 40 s a
page on Apple Silicon. `INDIC_OCR_DEVICE` picks where it runs (`auto`, the default, or `cuda`,
`mps`, `cpu`). `INDIC_OCR=false` only flags the pages; `DETECT_SCRIPTS=false` skips the
check. See [script.py](src/bakasur/core/convert/script.py).

Each run also writes `data/out/run_*.master.csv`: the run's change-of-zone rows in the column
layout of the "Substantive Objections" tab of the 39A master sheet. `export-master` writes the
same file for a gazette already in the artifact store, even if the ledger has it as processed.
See [docs/master-csv.md](docs/master-csv.md) for where each column comes from.

## Project layout

```
src/bakasur/
  cli.py                 # root CLI: core commands + one sub-app per use case
  core/                  # never imports from usecases/ (tests/test_boundaries.py checks)
    convert/             # the one Docling converter; orientation, scan prep, page info
    export/              # Markdown with page markers; folder batches in a worker process
    store/               # artifact folders: docling.json, pages, tables, meta.json
    rag/  llm/  notify/  sinks/   # chunking, LLM JSON calls, SMTP, Google Sheets
    config.py            # CoreSettings: OCR, LLM endpoint, Google credentials, SMTP
    cli.py               # to-md, to-md-batch, chunk-rag, spike-parse
  usecases/
    land_conversion_39a/ # 39A: anchors, tables, column mapping, normalisation, ledger, pipeline
    gczma_mom/           # GCZMA minutes
```

To add a document type, create `usecases/<name>/` with a `cli.py` exposing a `typer.Typer` app,
subclass `CoreSettings` in its own `config.py` if it needs settings, and add the app to
`USE_CASES` in [`cli.py`](src/bakasur/cli.py). Use cases import only from `bakasur.core` and
themselves.

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
