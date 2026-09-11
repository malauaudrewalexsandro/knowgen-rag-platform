"""
VLM analysis is a per-document toggle (per requirement). When ON, every
image/table chunk gets a text description from a vision model, and that
description is what actually gets embedded + stored — so retrieval can
surface "the image that shows X" even though the vector index only stores
text vectors.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.llm import analyze_image
from app.config import settings

if TYPE_CHECKING:
    # Deferred: chunking pulls in docling/torch, which only need to be
    # installed/importable when VLM (or non-spreadsheet ingestion) is
    # actually used — not just to import this module.
    from app.core.chunking import ImageChunk, TableChunk

IMAGE_PROMPT = (
    "Describe this image factually and in detail: what it shows, any labels, "
    "numbers, charts, or diagrams. This description will be used for document "
    "search, so be specific rather than general."
)

TABLE_VLM_PROMPT = (
    "This is a table extracted from a document. Summarize its structure and "
    "key data points in a few sentences, in addition to the raw table below."
)


def describe_image(chunk: ImageChunk, model: str | None = None) -> str:
    model = model or settings.default_vlm_model
    return analyze_image(chunk.image_bytes, IMAGE_PROMPT, model=model)


def enrich_table_with_vlm(chunk: TableChunk, table_image_bytes: bytes | None,
                           model: str | None = None) -> str:
    """
    Tables are already captured as markdown (core/chunking.py). VLM here is
    optional extra context — useful when a table's visual layout (merged
    cells, embedded charts) loses meaning in plain markdown.
    """
    if table_image_bytes is None:
        return chunk.markdown
    model = model or settings.default_vlm_model
    summary = analyze_image(table_image_bytes, TABLE_VLM_PROMPT, model=model)
    return f"{summary}\n\n{chunk.markdown}"
