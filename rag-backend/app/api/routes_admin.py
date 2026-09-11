from fastapi import APIRouter, HTTPException

from app.db import metadata_store

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/documents/{document_id}")
def get_document(document_id: str):
    doc = metadata_store.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/documents/{document_id}/excel-tables")
def get_document_excel_tables(document_id: str):
    doc = metadata_store.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return metadata_store.excel_tables_by_document(document_id)


@router.get("/health")
def health():
    return {"status": "ok"}
