"""
Shared clone-generation logic used by both POST /generate/clone
(app/api/routes_generate.py) and the /chat `clone_document` tool
(app/core/rag_chain.py), so there's exactly one implementation instead of
two copies that could drift apart.
"""
import os
import uuid

from app.config import settings
from app.core.doc_generation.clone_docx import generate_docx_clone
from app.core.doc_generation.clone_pdf import generate_pdf_clone
from app.core.doc_generation.clone_pptx import generate_pptx_clone
from app.core.doc_generation.clone_xlsx import generate_xlsx_clone
from app.core.doc_generation.document_blocks import extract_document_blocks
from app.db import metadata_store

GENERATED_DIR = os.path.join(os.path.dirname(settings.metadata_db_path), "..", "generated_documents")

_CLONE_GENERATORS = {
    "pdf": (generate_pdf_clone, ".pdf"),
    "docx": (generate_docx_clone, ".docx"),
    "pptx": (generate_pptx_clone, ".pptx"),
    "xlsx": (generate_xlsx_clone, ".xlsx"),
}


class CloneError(Exception):
    """Raised for any expected failure in the clone pipeline — callers turn
    this into an HTTPException (routes_generate.py) or a tool-result error
    dict (rag_chain.py) as appropriate for their context."""


def find_document_by_filename(filename_query: str) -> dict | None:
    """
    Case-insensitive match against ingested documents' filenames — used
    when the caller (e.g. the LLM via chat) only knows a filename, not a
    document_id. Tries an exact match first, then a substring match, so
    "resume.pdf" doesn't accidentally match "resume_old.pdf" ahead of an
    actual exact "resume.pdf".
    """
    query = filename_query.strip().lower()
    if not query:
        return None
    docs = metadata_store.list_documents()
    for d in docs:
        if d["filename"].lower() == query:
            return d
    for d in docs:
        if query in d["filename"].lower() or d["filename"].lower() in query:
            return d
    return None


def run_clone(document_id: str, format: str, title: str | None = None) -> tuple[str, str]:
    """
    Runs the full clone pipeline: re-parse the original uploaded file into
    ordered blocks, render it in the requested format. Returns
    (output_path_on_disk, suggested_download_filename). Raises CloneError
    for any expected failure.
    """
    if format not in _CLONE_GENERATORS:
        raise CloneError(f"Unsupported format: {format}")

    doc = metadata_store.get_document(document_id)
    if not doc:
        raise CloneError("document_id not found")

    # Reconstructs the exact path routes_documents.py saved the upload to
    # at ingest time (`{doc_id}_{filename}`) — the original file is never
    # deleted after ingestion.
    source_path = os.path.join(settings.upload_dir, f"{document_id}_{doc['filename']}")
    if not os.path.isfile(source_path):
        raise CloneError("Original uploaded file not found on disk")

    try:
        blocks = extract_document_blocks(source_path)
    except Exception as e:
        raise CloneError(f"Failed to parse source document: {e}")

    if not blocks:
        raise CloneError("No content could be extracted from the source document")

    resolved_title = title or doc["filename"]
    generator_fn, ext = _CLONE_GENERATORS[format]

    os.makedirs(GENERATED_DIR, exist_ok=True)
    out_path = os.path.join(GENERATED_DIR, f"{uuid.uuid4()}{ext}")
    try:
        generator_fn(resolved_title, blocks, out_path)
    except Exception as e:
        raise CloneError(f"Clone generation failed: {e}")

    safe_title = "".join(c for c in resolved_title if c not in '\\/:*?"<>|')
    download_filename = f"{safe_title}_clone{ext}"
    return out_path, download_filename
