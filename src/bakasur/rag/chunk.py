"""RAG chunking from saved DoclingDocument artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from docling_core.transforms.chunker import HybridChunker
from docling_core.transforms.chunker.hierarchical_chunker import (
    ChunkingDocSerializer,
    ChunkingSerializerProvider,
)
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.transforms.serializer.markdown import MarkdownParams
from docling_core.types.doc import DoclingDocument
from transformers import AutoTokenizer


EMBED_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"


class OcrChunkingSerializerProvider(ChunkingSerializerProvider):
    def get_serializer(self, doc: DoclingDocument) -> ChunkingDocSerializer:
        return ChunkingDocSerializer(
            doc=doc,
            params=MarkdownParams(
                traverse_pictures=True,
                image_placeholder="",
                escape_underscores=False,
                escape_html=False,
            ),
        )


@dataclass
class RagChunk:
    text: str
    embed_text: str
    pages: list[int]
    headings: list[str]


def load_docling_json(path: Path) -> DoclingDocument:
    return DoclingDocument.load_from_json(path)


def build_chunker(max_tokens: int = 512) -> HybridChunker:
    tokenizer = HuggingFaceTokenizer(
        tokenizer=AutoTokenizer.from_pretrained(EMBED_MODEL_ID),
        max_tokens=max_tokens,
    )
    return HybridChunker(
        tokenizer=tokenizer,
        merge_peers=True,
        serializer_provider=OcrChunkingSerializerProvider(),
    )


def chunk_document(doc: DoclingDocument, max_tokens: int = 512) -> Iterator[RagChunk]:
    chunker = build_chunker(max_tokens=max_tokens)
    for chunk in chunker.chunk(dl_doc=doc):
        pages = sorted({p.page_no for it in chunk.meta.doc_items for p in it.prov})
        yield RagChunk(
            text=chunk.text,
            embed_text=chunker.contextualize(chunk=chunk),
            pages=pages,
            headings=list(chunk.meta.headings or []),
        )


def chunk_from_artifact(docling_json: Path, max_tokens: int = 512) -> list[RagChunk]:
    doc = load_docling_json(docling_json)
    return list(chunk_document(doc, max_tokens=max_tokens))
