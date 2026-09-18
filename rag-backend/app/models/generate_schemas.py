"""
Request/response schemas for POST /generate/document and POST /generate/clone.

Kept in its own file (not merged into app/models/schemas.py) so it can be
dropped in without touching the existing schema file — import it from
routes_generate.py, or move its contents into schemas.py, whichever you
prefer.
"""
from typing import Literal

from pydantic import BaseModel


class ChartSpec(BaseModel):
    type: Literal["bar", "line", "pie", "scatter"] = "bar"
    group_by_column: str
    value_column: str
    aggregate: Literal["sum", "avg", "count"] = "sum"


class SectionSpec(BaseModel):
    """One user-defined section. Provide this list to skip LLM auto-planning."""
    heading: str
    narrative: str | None = None
    table_name: str | None = None  # from excel_tables.table_name
    chart: ChartSpec | None = None


class GenerateDocumentRequest(BaseModel):
    document_id: str
    format: Literal["pdf", "docx", "pptx", "xlsx"]
    title: str | None = None
    llm_model: str | None = None
    # None => auto-plan one section per ingested table via the LLM.
    # Provided => use these sections as-is (still resolves chart/table data).
    sections: list[SectionSpec] | None = None


class CloneDocumentRequest(BaseModel):
    """
    "Recreate this uploaded document as a template" — re-parses the
    original uploaded file (any format chunking.py/Docling can read: pdf,
    docx, pptx, images, ...) into structured blocks and rebuilds it in the
    requested format. See app/core/doc_generation/document_blocks.py.
    """
    document_id: str
    format: Literal["pdf", "docx", "pptx", "xlsx"]
    title: str | None = None
