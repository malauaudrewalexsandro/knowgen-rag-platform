"""
Document ingestion via Docling: parses PDF/DOCX/PPTX/images into a
structure-aware `DoclingDocument`, then produces three kinds of chunks:

  - text chunks   (HybridChunker — respects headings/sections, not just
                    fixed character windows, so context/layout survives)
  - table chunks  (kept as markdown so row/column relationships aren't
                    flattened away by naive text extraction)
  - image chunks  (raw crops handed to core/vlm.py for description, only
                    when VLM analysis is toggled on for the document)

NOTE: Docling's API has moved fairly quickly across versions — if
`DocumentConverter` / `HybridChunker` / item attribute names below don't
match what `pip install docling` resolves to, check docling's current docs;
this file is the single place that needs updating.

WINDOWS NOTE: `torch` MUST be imported before `docling` here. Docling's
import chain pulls in several C-extension packages (docling_parse,
deepsearch_glm, opencv, rtree, ...) before it gets to importing torch
internally (via easyocr). On Windows, if one of those loads first, it can
lock in a conflicting DLL and torch's own DLL init then fails with
`OSError: [WinError 1114] ... c10.dll ...`. Importing torch first avoids
the conflict entirely. Do not reorder these two imports.
"""
import torch  # noqa: F401  (import order matters on Windows — see note above)

from dataclasses import dataclass, field

from docling.document_converter import DocumentConverter
try:
    # Newer docling versions re-export HybridChunker here.
    from docling.chunking import HybridChunker
except ImportError:
    # Older docling (e.g. 2.5.x) doesn't have that re-export — the real
    # implementation always lives in docling_core, so fall back to it.
    from docling_core.transforms.chunker.hybrid_chunker import HybridChunker


@dataclass
class TextChunk:
    text: str
    page: int | None
    chunk_type: str = "text"
    extra: dict = field(default_factory=dict)


@dataclass
class TableChunk:
    markdown: str
    page: int | None
    chunk_type: str = "table"
    extra: dict = field(default_factory=dict)


@dataclass
class ImageChunk:
    image_bytes: bytes
    page: int | None
    mime_type: str = "image/png"
    chunk_type: str = "image"
    extra: dict = field(default_factory=dict)


_converter = DocumentConverter()


def convert_document(file_path: str):
    """Parse a source file (pdf/docx/pptx/image/...) into a DoclingDocument."""
    result = _converter.convert(file_path)
    return result.document


def chunk_text(doc, tokenizer_model: str = "sentence-transformers/all-MiniLM-L6-v2",
               max_tokens: int = 512) -> list[TextChunk]:
    """
    HybridChunker splits on document structure first (headings, paragraphs)
    and only falls back to token-window splitting for oversized sections —
    this is what keeps retrieved context coherent instead of mid-sentence.
    """
    chunker = HybridChunker(tokenizer=tokenizer_model, max_tokens=max_tokens)
    chunks = []
    for chunk in chunker.chunk(doc):
        page = None
        if getattr(chunk, "meta", None) and getattr(chunk.meta, "doc_items", None):
            first_item = chunk.meta.doc_items[0]
            prov = getattr(first_item, "prov", None)
            if prov:
                page = prov[0].page_no
        chunks.append(TextChunk(text=chunk.text, page=page, extra={"headings": getattr(chunk.meta, "headings", [])}))
    return chunks


def extract_tables(doc) -> list[TableChunk]:
    """Every table in the document, serialized to markdown to preserve structure."""
    out = []
    for table in getattr(doc, "tables", []):
        try:
            md = table.export_to_markdown(doc=doc)
        except Exception:
            md = str(table)
        page = None
        if getattr(table, "prov", None):
            page = table.prov[0].page_no
        out.append(TableChunk(markdown=md, page=page))
    return out


def extract_images(doc, page_image_scale: float = 2.0) -> list[ImageChunk]:
    """
    Crops of figures/pictures in the document, for VLM description. Requires
    Docling's page-image generation to be enabled on the converter/pipeline
    options (see docs) so `picture.get_image(doc)` has pixels to crop from.
    """
    out = []
    for picture in getattr(doc, "pictures", []):
        try:
            pil_image = picture.get_image(doc)
        except Exception:
            continue
        if pil_image is None:
            continue
        import io
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        page = None
        if getattr(picture, "prov", None):
            page = picture.prov[0].page_no
        out.append(ImageChunk(image_bytes=buf.getvalue(), page=page))
    return out
