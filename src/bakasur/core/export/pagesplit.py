"""Split text that runs across a page break into one piece per page."""

from __future__ import annotations

from docling_core.types.doc import DoclingDocument, ProvenanceItem, TextItem


def _page_pieces(item: TextItem) -> list[tuple[int, str, list[ProvenanceItem]]] | None:
    """
    The item's text cut at its page breaks, as (page_no, text, provs) in reading order, or
    None if it sits on one page or its provenance cannot be trusted to say where to cut.
    """
    provs = item.prov
    if len(provs) < 2 or len({p.page_no for p in provs}) < 2:
        return None
    text = item.text
    groups: list[tuple[int, list]] = []  # consecutive provs on the same page
    prev_end = 0
    for prov in provs:
        start, end = prov.charspan
        # Spans must run forward, without overlap, inside the text; pages must not go back.
        if not prev_end <= start <= end <= len(text):
            return None
        if groups and prov.page_no < groups[-1][0]:
            return None
        if groups and prov.page_no == groups[-1][0]:
            groups[-1][1].append(prov)
        else:
            groups.append((prov.page_no, [prov]))
        prev_end = end
    # The spans should cover the text, give or take the joining spaces between them.
    covered = sum(p.charspan[1] - p.charspan[0] for p in provs)
    if covered < len(text) - len(provs):
        return None
    out = []
    for page, page_provs in groups:
        start, end = page_provs[0].charspan[0], page_provs[-1].charspan[1]
        piece = text[start:end].strip()
        if not piece:
            return None
        out.append((page, piece, page_provs))
    return out


def split_across_pages(doc: DoclingDocument) -> DoclingDocument:
    """
    A copy of ``doc`` in which each text item that continues onto later pages is cut at the
    page breaks, so per-page export puts every part under the page it is printed on.
    Docling merges a paragraph that crosses a page break into one item, and the Markdown
    serializer files an item under its first provenance page only, so the continuation
    otherwise lands a page (or more) early.

    Only childless text items whose character spans line up cleanly are cut; anything else
    (tables, items with nested children, inconsistent provenance) is left as it was.
    """
    doc = doc.model_copy(deep=True)
    for item in list(doc.texts):
        if item.children:
            continue
        pieces = _page_pieces(item)
        if not pieces:
            continue
        sibling = item
        for i, (_, piece, provs) in enumerate(pieces):
            spans = [(p.charspan[0], p.charspan[1]) for p in provs]
            offset = spans[0][0]
            new_provs = [
                p.model_copy(update={"charspan": (s - offset, e - offset)})
                for p, (s, e) in zip(provs, spans)
            ]
            if i == 0:
                item.text = item.orig = piece
                item.prov = new_provs
                continue
            part = item.model_copy(
                deep=True, update={"text": piece, "orig": piece, "prov": new_provs, "children": []}
            )
            doc.insert_item_after_sibling(new_item=part, sibling=sibling)
            sibling = part
    return doc
