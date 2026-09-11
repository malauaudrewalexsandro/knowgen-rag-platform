"""
Lightweight metadata DB (SQLite, zero setup) tracking, per requirement:
  - which embedding model + dims each knowledge-base document was embedded
    with (so we know which TurboVec collection its chunks live in)
  - whether VLM (image/table) analysis was enabled for that document
  - chunk-level records (type: text | table | image) for retrieval to know
    what it's pulling back
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_dims INTEGER NOT NULL,
    collection_key TEXT NOT NULL,
    vlm_enabled INTEGER NOT NULL DEFAULT 0,
    vlm_model TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    vector_id TEXT NOT NULL,
    chunk_type TEXT NOT NULL,   -- text | table | image
    page INTEGER,
    content_preview TEXT,
    extra_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);

CREATE TABLE IF NOT EXISTS excel_tables (
    table_name TEXT PRIMARY KEY,   -- actual SQLite table name in excel_data.sqlite3
    document_id TEXT NOT NULL REFERENCES documents(id),
    sheet_name TEXT NOT NULL,
    columns_json TEXT NOT NULL,
    dtypes_json TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_excel_tables_document_id ON excel_tables(document_id);
"""


@contextmanager
def get_conn():
    os.makedirs(os.path.dirname(settings.metadata_db_path), exist_ok=True)
    conn = sqlite3.connect(settings.metadata_db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_document(doc_id: str, filename: str, embedding_model: str, embedding_dims: int,
                     collection_key: str, vlm_enabled: bool, vlm_model: str | None):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO documents
               (id, filename, embedding_model, embedding_dims, collection_key,
                vlm_enabled, vlm_model, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (doc_id, filename, embedding_model, embedding_dims, collection_key,
             int(vlm_enabled), vlm_model, _now()),
        )


def record_chunk(chunk_id: str, document_id: str, vector_id: str, chunk_type: str,
                  page: int | None, content_preview: str, extra: dict | None = None):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO chunks
               (id, document_id, vector_id, chunk_type, page, content_preview, extra_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (chunk_id, document_id, vector_id, chunk_type, page,
             content_preview[:300], json.dumps(extra or {}), _now()),
        )


def get_document(doc_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return dict(row) if row else None


def list_documents() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def documents_by_collection(collection_key: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM documents WHERE collection_key = ?", (collection_key,)
        ).fetchall()
        return [dict(r) for r in rows]


def record_excel_table(table_name: str, document_id: str, sheet_name: str,
                        columns: list[str], dtypes: dict, row_count: int):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO excel_tables
               (table_name, document_id, sheet_name, columns_json, dtypes_json,
                row_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (table_name, document_id, sheet_name, json.dumps(columns),
             json.dumps(dtypes), row_count, _now()),
        )


def get_excel_table(table_name: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM excel_tables WHERE table_name = ?", (table_name,)
        ).fetchone()
        return dict(row) if row else None


def excel_tables_by_document(document_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM excel_tables WHERE document_id = ?", (document_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def count_excel_tables_by_document() -> dict[str, int]:
    """document_id -> number of tables ingested from it (for the doc list UI)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT document_id, COUNT(*) AS n FROM excel_tables GROUP BY document_id"
        ).fetchall()
        return {r["document_id"]: r["n"] for r in rows}
