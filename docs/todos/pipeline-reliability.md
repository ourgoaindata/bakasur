# Pipeline reliability gaps

Issues found while reviewing [`src/bakasur/usecases/land_conversion_39a/pipeline.py`](../../src/bakasur/usecases/land_conversion_39a/pipeline.py) and its
dependencies. None of these are fixed yet — this is a tracking doc.

## 1. Sticky failure: partial `ArtifactStore.write()` blocks all future retries

`ArtifactStore.write()` writes files in this order ([artifacts.py:75-167](../../src/bakasur/core/store/artifacts.py#L75)):

```
raw.<ext> -> docling.json -> pages/*.txt -> tables/*.json -> document.md -> meta.json
```

but `ArtifactStore.exists()` only checks for `docling.json`
([artifacts.py:192-193](../../src/bakasur/core/store/artifacts.py#L192)):

```python
def exists(self, doc_id: str) -> bool:
    return (self.doc_dir(doc_id) / "docling.json").exists()
```

If the process is killed/crashes between writing `docling.json` and finishing the rest
(e.g. `meta.json` never gets written), the artifact dir is left half-populated but still
reads as "already parsed."

On retry, `Pipeline.process_pdf` ([pipeline.py:128-144](../../src/bakasur/usecases/land_conversion_39a/pipeline.py#L128)) sees
`exists() == True`, skips re-parsing, and calls `store.load_meta()`, which raises
`FileNotFoundError`. The gazette is marked `FAILED` and the PDF moves to `failed_dir` — but
since `gazette_id` is derived from content hash, **re-running the same file (or any copy of
it) hits the exact same half-written artifact dir and fails identically, forever.** There is
no self-healing path; someone has to manually delete
`data/gazettes/<gazette_id>/` before the file can ever succeed.

**Fix direction:** make `write()` atomic (write to a temp dir and rename into place once
complete, or write a `_SUCCESS`/sentinel file last and have `exists()` check that instead of
`docling.json`).

## 2. Silent failure: Docling can under-extract with no error at all

`convert` ([converter.py](../../src/bakasur/core/convert/converter.py)) is a single
Docling call with no per-page success tracking. If OCR misses a page, a table isn't detected,
or a notification anchor isn't recognized, `write()` still completes cleanly and `meta.json`
still gets written — there's no check that what was extracted matches what's actually in the
source PDF.

Downstream, `extract_39a_from_artifacts` ([extract.py:36-71](../../src/bakasur/usecases/land_conversion_39a/extract.py#L36))
just finds fewer spans/rows in that case. No exception, no failure status.

The only partial safety net is the `sr_no` gap check in `validate_rows`
([validate.py:41-51](../../src/bakasur/usecases/land_conversion_39a/validate.py#L41)), and it's `severity="warning"`, so
`partition_rows` ([validate.py:56-62](../../src/bakasur/usecases/land_conversion_39a/validate.py#L56)) still treats those
rows as "good" — the run completes as `COMPLETED`, rows get ledger-recorded as emitted, and
the only trace is a warning line in the digest email that's easy to miss. If an entire
notification span is missed (anchor pattern didn't match at all), there's **no signal
whatsoever** — just a lower row count than the gazette actually contains.

**Fix direction:** add a sanity check comparing extracted page/table counts (or expected
notification count) against the source PDF before marking `COMPLETED`; consider promoting the
`sr_no` gap check to `severity="error"` so it blocks silently-incomplete rows instead of just
warning.

## 3. Sheets sink failures are swallowed entirely

In `process_pdf` ([pipeline.py:91-94](../../src/bakasur/usecases/land_conversion_39a/pipeline.py#L91)):

```python
try:
    self.sheets.append_rows(new_rows, new_plots, issues)
except Exception:
    pass
```

This is intentional (local files stay authoritative if Sheets has an outage), but right now
there's no logging, metric, or retry-queue for the swallowed exception — if Sheets silently
falls behind for days, nobody finds out until someone notices the sheet is stale. At minimum
this should log the exception; ideally it should track "rows pending Sheets sync" somewhere so
a later run can backfill.

## 4. Row-level dedup ledger has no reconciliation path

Rows are marked emitted in the ledger as soon as `append_rows` succeeds
([pipeline.py:151-176](../../src/bakasur/usecases/land_conversion_39a/pipeline.py#L151)), keyed by `row_hash`. If artifacts
are later found to be incomplete (per #1 or #2) and manually fixed/reparsed, there's no
tooling to figure out which previously-emitted rows were wrong/partial and need
correction — the ledger only prevents duplicates, it doesn't support "re-emit and reconcile."

**Fix direction:** at minimum, a way to query the ledger by `gazette_id` and manually void/
re-open a gazette's emitted rows when a reparse is forced.
