"""
End-to-end test of the /documents/ingest -> /documents -> /admin excel-tables
flow through the real FastAPI app (TestClient), not just the bare functions.

Only the embedding call is mocked (fixed-size fake vectors) so the test
doesn't need network access or a downloaded sentence-transformers model —
everything else (routing, excel_ingest, the real on-disk SQLite table,
TurboVec index, metadata store) is exercised for real.
"""
import importlib

import pandas as pd
import pytest


@pytest.fixture
def client(tmp_storage, monkeypatch):
    from app.core import embeddings, vectorstore
    from app.api import routes_admin, routes_chat, routes_documents
    from app import main

    for mod in (vectorstore, embeddings, routes_documents, routes_admin, routes_chat, main):
        importlib.reload(mod)

    # Fixed fake embeddings: fast, deterministic, no network/model download.
    # TurboVec requires dim to be a positive multiple of 8 (real embedding
    # models satisfy this naturally, e.g. all-MiniLM-L6-v2 = 384).
    def fake_embed_batch(texts, model=None):
        from app.core.embeddings import EmbeddingResult
        return [EmbeddingResult(vector=[0.1] * 8, model=model or "test", dims=8)
                for _ in texts]

    monkeypatch.setattr(embeddings, "embed_batch", fake_embed_batch)
    monkeypatch.setattr(routes_documents, "embeddings", embeddings)

    from fastapi.testclient import TestClient
    return TestClient(main.app)


def _csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def test_ingest_csv_end_to_end(client):
    df = pd.DataFrame({
        "region": ["West", "East", "West", "North"],
        "revenue": [100, 250, 175, 90],
    })
    files = {"file": ("penjualan.csv", _csv_bytes(df), "text/csv")}

    resp = client.post("/documents/ingest", files=files)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["excel_tables"] == 1
    assert body["text_chunks"] == 0
    assert body["table_chunks"] == 0
    doc_id = body["document_id"]

    # Shows up in the document list with the table count surfaced.
    docs = client.get("/documents").json()
    assert any(d["id"] == doc_id and d["excel_tables"] == 1 for d in docs)

    # Admin endpoint exposes the underlying table metadata.
    tables = client.get(f"/admin/documents/{doc_id}/excel-tables").json()
    assert len(tables) == 1
    table_name = tables[0]["table_name"]
    assert tables[0]["row_count"] == 4
    assert "region" in tables[0]["columns_json"]

    # And the data really is queryable via the SQL tool against a real file.
    from app.core.sql_tool import run_readonly_query
    result = run_readonly_query(f"SELECT SUM(revenue) AS total FROM {table_name}")
    assert result["rows"][0]["total"] == 615


def test_ingest_xlsx_multi_sheet_end_to_end(client, tmp_path):
    sales = pd.DataFrame({"item": ["A", "B"], "qty": [3, 7]})
    hr = pd.DataFrame({"name": ["Sari", "Budi"], "dept": ["Eng", "Sales"]})
    path = tmp_path / "workbook.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        sales.to_excel(writer, sheet_name="Sales", index=False)
        hr.to_excel(writer, sheet_name="HR", index=False)

    with open(path, "rb") as f:
        resp = client.post(
            "/documents/ingest",
            files={"file": ("workbook.xlsx", f.read(),
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["excel_tables"] == 2


def test_ingest_rejects_empty_csv(client):
    files = {"file": ("empty.csv", b"", "text/csv")}
    resp = client.post("/documents/ingest", files=files)
    assert resp.status_code == 422


def test_documents_list_and_collections_endpoints_still_work(client):
    assert client.get("/documents").status_code == 200
    assert client.get("/documents/collections").status_code == 200
    assert client.get("/admin/health").json() == {"status": "ok"}
