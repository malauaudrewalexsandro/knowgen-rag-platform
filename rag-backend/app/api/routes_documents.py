import os
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile, Form

from app.config import settings
from app.core import embeddings, excel_ingest, vectorstore, vlm
from app.db import metadata_store
from app.models.schemas import DocumentSummary, IngestResponse

router = APIRouter(prefix="/documents", tags=["documents"])

SPREADSHEET_EXTENSIONS = {".xlsx", ".xls", ".csv"}


@router.post("/ingest", response_model=IngestResponse)
async def ingest_document(
    file: UploadFile = File(...),
    embedding_model: str | None = Form(None),
    vlm_enabled: bool = Form(False),
    vlm_model: str | None = Form(None),
):
    embedding_model = embedding_model or settings.default_embedding_model
    vlm_model = vlm_model or settings.default_vlm_model

    os.makedirs(settings.upload_dir, exist_ok=True)
    doc_id = str(uuid.uuid4())
    save_path = os.path.join(settings.upload_dir, f"{doc_id}_{file.filename}")
    with open(save_path, "wb") as f:
        f.write(await file.read())

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext in SPREADSHEET_EXTENSIONS:
        return _ingest_spreadsheet(save_path, doc_id, file.filename, embedding_model)

    # Deferred import: docling/torch are heavy and only needed for this
    # (non-spreadsheet) path, so the Excel/CSV route above works even in an
    # environment that hasn't installed them yet.
    from app.core import chunking

    try:
        doc = chunking.convert_document(save_path)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse document: {e}")

    text_chunks = chunking.chunk_text(doc)
    table_chunks = chunking.extract_tables(doc)
    image_chunks = chunking.extract_images(doc) if vlm_enabled else []

    # Embed everything with the SAME model (so it lands in one collection),
    # but tables/images first go through VLM enrichment when enabled so
    # what actually gets embedded is text-searchable.
    texts_to_embed: list[str] = [c.text for c in text_chunks]
    texts_to_embed += [c.markdown for c in table_chunks]
    image_descriptions: list[str] = []
    if vlm_enabled:
        for img in image_chunks:
            image_descriptions.append(vlm.describe_image(img, model=vlm_model))
        texts_to_embed += image_descriptions

    embedded = embeddings.embed_batch(texts_to_embed, model=embedding_model)
    if not embedded:
        raise HTTPException(status_code=422, detail="Document produced no embeddable content")

    dims = embedded[0].dims
    collection = vectorstore.get_collection(embedding_model, dims)
    collection_key = collection.key

    metadata_store.init_db()
    metadata_store.record_document(
        doc_id=doc_id, filename=file.filename, embedding_model=embedding_model,
        embedding_dims=dims, collection_key=collection_key,
        vlm_enabled=vlm_enabled, vlm_model=vlm_model if vlm_enabled else None,
    )

    cursor = 0
    for c in text_chunks:
        vec_id = collection.add(embedded[cursor].vector, {
            "document_id": doc_id, "chunk_type": "text", "content": c.text, "page": c.page,
        })
        metadata_store.record_chunk(str(uuid.uuid4()), doc_id, vec_id, "text", c.page, c.text)
        cursor += 1

    for c in table_chunks:
        vec_id = collection.add(embedded[cursor].vector, {
            "document_id": doc_id, "chunk_type": "table", "content": c.markdown, "page": c.page,
        })
        metadata_store.record_chunk(str(uuid.uuid4()), doc_id, vec_id, "table", c.page, c.markdown)
        cursor += 1

    if vlm_enabled:
        for img, desc in zip(image_chunks, image_descriptions):
            vec_id = collection.add(embedded[cursor].vector, {
                "document_id": doc_id, "chunk_type": "image", "content": desc, "page": img.page,
            })
            metadata_store.record_chunk(str(uuid.uuid4()), doc_id, vec_id, "image", img.page, desc)
            cursor += 1

    collection.save()

    return IngestResponse(
        document_id=doc_id, filename=file.filename, collection_key=collection_key,
        text_chunks=len(text_chunks), table_chunks=len(table_chunks),
        image_chunks=len(image_chunks) if vlm_enabled else 0,
    )


def _ingest_spreadsheet(save_path: str, doc_id: str, filename: str, embedding_model: str) -> IngestResponse:
    """
    Excel/CSV path (see app/core/excel_ingest.py for the rationale): each
    sheet becomes a real SQLite table for exact SQL retrieval, and only a
    compact schema summary per table gets embedded so the table is
    discoverable by /chat's semantic search without ever embedding raw rows.
    """
    try:
        tables = excel_ingest.ingest_excel(save_path, workbook_label=filename)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse spreadsheet: {e}")

    if not tables:
        raise HTTPException(status_code=422, detail="Spreadsheet produced no non-empty sheets/tables")

    summaries = [excel_ingest.build_schema_summary(t) for t in tables]
    embedded = embeddings.embed_batch(summaries, model=embedding_model)
    if not embedded:
        raise HTTPException(status_code=422, detail="Spreadsheet produced no embeddable content")

    dims = embedded[0].dims
    collection = vectorstore.get_collection(embedding_model, dims)
    collection_key = collection.key

    metadata_store.init_db()
    metadata_store.record_document(
        doc_id=doc_id, filename=filename, embedding_model=embedding_model,
        embedding_dims=dims, collection_key=collection_key,
        vlm_enabled=False, vlm_model=None,
    )

    for table_meta, summary, emb in zip(tables, summaries, embedded):
        vec_id = collection.add(emb.vector, {
            "document_id": doc_id,
            "chunk_type": "table_schema",
            "content": summary,
            "page": None,
            "table_name": table_meta["table_name"],
        })
        metadata_store.record_chunk(
            str(uuid.uuid4()), doc_id, vec_id, "table_schema", None, summary,
            extra={"table_name": table_meta["table_name"], "row_count": table_meta["row_count"]},
        )
        metadata_store.record_excel_table(
            table_name=table_meta["table_name"], document_id=doc_id,
            sheet_name=table_meta["sheet_name"], columns=table_meta["columns"],
            dtypes=table_meta["dtypes"], row_count=table_meta["row_count"],
        )

    collection.save()

    return IngestResponse(
        document_id=doc_id, filename=filename, collection_key=collection_key,
        text_chunks=0, table_chunks=0, image_chunks=0, excel_tables=len(tables),
    )


@router.get("", response_model=list[DocumentSummary])
def list_documents():
    metadata_store.init_db()
    docs = metadata_store.list_documents()
    excel_counts = metadata_store.count_excel_tables_by_document()
    return [
        DocumentSummary(
            id=d["id"], filename=d["filename"], embedding_model=d["embedding_model"],
            embedding_dims=d["embedding_dims"], collection_key=d["collection_key"],
            vlm_enabled=bool(d["vlm_enabled"]), created_at=d["created_at"],
            excel_tables=excel_counts.get(d["id"], 0),
        )
        for d in docs
    ]


@router.get("/collections")
def list_collections():
    return {"collections": vectorstore.list_collections()}
