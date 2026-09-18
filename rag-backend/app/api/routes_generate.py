"""
POST /generate/document — turns an already-ingested Excel/CSV document
(see app/api/routes_documents.py's spreadsheet path) into a polished
PDF/DOCX/PPTX/XLSX report: narrative text + data table + chart per sheet.

POST /generate/clone — "recreate this uploaded document as a template":
re-parses the ORIGINAL uploaded file (any format Docling/chunking.py can
read — pdf, docx, pptx, images, ...) into ordered structural blocks and
rebuilds it in the requested output format. Shares its implementation
(app/core/doc_generation/clone_runner.py) with the /chat `clone_document`
tool in app/core/rag_chain.py.

GET /generate/chart/{filename} — serves a standalone chart PNG generated
via the /chat `generate_chart` tool, for inline display in the chat UI.

GET /generate/download/{filename} — generic download for any file already
produced into GENERATED_DIR (e.g. by the /chat `clone_document` tool),
with an optional nicer suggested filename via ?download_name=.

Two modes for /generate/document:
  - sections=None  -> LLM auto-plans one section per ingested table
    (app/core/doc_generation/content_planner.py).
  - sections=[...] -> caller supplies heading/narrative/chart per section;
    only the chart's aggregate SQL and the table preview get resolved here.
"""
import os
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import settings
from app.core.doc_generation import content_planner
from app.core.doc_generation.chart_builder import CHART_TMP_DIR
from app.core.doc_generation.clone_runner import GENERATED_DIR, CloneError, run_clone
from app.core.doc_generation.docx_generator import generate_docx
from app.core.doc_generation.pdf_generator import generate_pdf
from app.core.doc_generation.pptx_generator import generate_pptx
from app.core.doc_generation.xlsx_generator import generate_xlsx
from app.db import metadata_store
from app.models.generate_schemas import CloneDocumentRequest, GenerateDocumentRequest

router = APIRouter(prefix="/generate", tags=["generate"])

_GENERATORS = {
    "pdf": (generate_pdf, ".pdf", "application/pdf"),
    "docx": (generate_docx, ".docx",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "pptx": (generate_pptx, ".pptx",
             "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    "xlsx": (generate_xlsx, ".xlsx",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
}

_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _build_sections_from_request(req: GenerateDocumentRequest) -> list[dict]:
    sections = []
    for s in req.sections:
        chart_data = None
        if s.chart and s.table_name:
            chart_data = content_planner.resolve_chart_data(s.table_name, {
                "type": s.chart.type,
                "group_by_column": s.chart.group_by_column,
                "value_column": s.chart.value_column,
                "aggregate": s.chart.aggregate,
            })
        table_preview = content_planner.get_table_preview(s.table_name) if s.table_name else {}
        sections.append({
            "heading": s.heading,
            "narrative": s.narrative or "",
            "chart_data": chart_data,
            "table_preview": table_preview,
        })
    return sections


def _build_sections_auto(req: GenerateDocumentRequest) -> list[dict]:
    planned = content_planner.plan_sections(req.document_id, llm_model=req.llm_model)
    sections = []
    for p in planned:
        chart_data = content_planner.resolve_chart_data(p["table_name"], p["chart_plan"])
        table_preview = content_planner.get_table_preview(p["table_name"])
        sections.append({
            "heading": p["heading"],
            "narrative": p["narrative"],
            "chart_data": chart_data,
            "table_preview": table_preview,
        })
    return sections


@router.post("/document")
def generate_document(req: GenerateDocumentRequest):
    if req.format not in _GENERATORS:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {req.format}")

    doc = metadata_store.get_document(req.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="document_id not found")

    try:
        if req.sections:
            sections = _build_sections_from_request(req)
        else:
            sections = _build_sections_auto(req)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if not sections:
        raise HTTPException(status_code=422, detail="No sections to generate — no data available")

    spec = {"title": req.title or doc["filename"], "sections": sections}

    os.makedirs(GENERATED_DIR, exist_ok=True)
    generator_fn, ext, media_type = _GENERATORS[req.format]
    out_path = os.path.join(GENERATED_DIR, f"{uuid.uuid4()}{ext}")

    try:
        generator_fn(spec, out_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Document generation failed: {e}")

    safe_title = "".join(c for c in spec["title"] if c not in '\\/:*?"<>|')
    return FileResponse(out_path, media_type=media_type, filename=f"{safe_title}{ext}")


@router.post("/clone")
def clone_document(req: CloneDocumentRequest):
    try:
        out_path, download_filename = run_clone(req.document_id, req.format, req.title)
    except CloneError as e:
        message = str(e)
        status = 404 if "not found" in message.lower() else 422
        raise HTTPException(status_code=status, detail=message)

    return FileResponse(out_path, media_type=_MEDIA_TYPES[req.format], filename=download_filename)


@router.get("/chart/{filename}")
def get_chart(filename: str):
    # os.path.basename strips any directory components, so a filename like
    # "../../secrets.txt" can't escape CHART_TMP_DIR (path traversal guard).
    safe_name = os.path.basename(filename)
    path = os.path.join(CHART_TMP_DIR, safe_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Chart not found")
    return FileResponse(path, media_type="image/png")


@router.get("/download/{filename}")
def download_generated_file(filename: str, download_name: str | None = None):
    """
    Generic download for anything already produced into GENERATED_DIR —
    used by the /chat `clone_document` tool (app/core/rag_chain.py), which
    only has the server-assigned uuid filename and passes a nicer
    ?download_name= for the browser's Save As dialog.
    """
    safe_name = os.path.basename(filename)
    path = os.path.join(GENERATED_DIR, safe_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=download_name or safe_name)
