# `[Page N]` markers can be early for paragraphs that cross a page break

Found while spot-checking the GCZMA minutes converted with `to-md-batch`.

**Fixed (2026-11-26):** `split_across_pages` ([pagesplit.py](../../src/bakasur/core/export/pagesplit.py))
cuts such items at their page breaks before export. Docling does keep every page's provenance
and char span on the merged item; it is docling-core's Markdown serializer that files an item
under `prov[0].page_no` only. Re-converted MoM 001, 002 and 162: no page ends with text from
the next page any more, the empty pages are filled, and the total text is unchanged. Existing
outputs need re-converting to pick this up.

## What happens

`document_to_markdown` ([markdown.py](../../src/bakasur/core/export/markdown.py)) exports each page
with `doc.export_to_markdown(page_no=N)` and puts a `[Page N]` marker before it. When a
paragraph runs across a page break, Docling merges it into one text item, and the whole item
is exported under the page where it **starts**. The pages it continues onto come out empty or
short, and their text sits under an earlier marker.

No text is lost, but a quote's `[Page N]` can be one or more pages earlier than where it
actually appears in the PDF.

## Examples

- `MoM 162 (2017-10-31)`: pages 22–23 are full pages of text in the PDF but are empty in the
  Markdown. Their text ("Show Cause Notice bearing no", "Hotel Shaurya thereby",
  "Floor Space Index", ...) is under `[Page 21]`, whose section is ~13 KB.
- `MoM 002 (1999-11-12)`: the short paragraph at the top of page 24 ("... forthcoming dry
  season ...") is under `[Page 23]`; `[Page 24]` is empty.

Of 23,642 pages across the first 500 converted files, 95 came out near-empty; the ones checked
were either genuinely blank (e.g. `MoM 035` p5) or this case.

## Why

docling-core's page filter (`iterate_items(page_nrs=...)`) includes an item if **any** of its
`prov` entries is on the page, so a merged item that kept every page's provenance would
appear under each page. Since the continuation pages come out empty, the merged item
evidently carries only its first page's provenance. Worth confirming against a saved
`docling.json` for one of the examples above.

## Fix direction

Split cross-page text items at page boundaries before exporting (using the per-page
provenance / char spans if Docling keeps them), or emit a marker inline where the text crosses
a page (e.g. `[Page 22]` mid-paragraph). Either way, add a test with a paragraph spanning two
pages. Re-converting existing outputs would be needed to pick up the fix.
