# RAG Backend

FastAPI service implementing the RAG spec:
- **LiteLLM** → swap LLM/embedding provider via config string, no code changes
- **LangChain** (LangGraph swap-in ready) → orchestrates retrieve → prompt → generate
- **TurboVec** → local compressed vector index, one collection per embedding model
- **Docling** → layout-aware chunking, table extraction, image extraction
- **VLM toggle** → per-document flag to describe images/tables via a vision model

## 0. Where this came from

You said you're starting from a **blank folder in VSCode**. Here's exactly
what to do, in order.

## 1. Open the folder & create a virtual environment

```bash
# inside your blank project folder, in VSCode's integrated terminal
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
```

You should see `(venv)` appear in your terminal prompt. VSCode may also pop
up "select interpreter" — pick the one inside `venv/`.

## 2. Copy in these files

Drop everything from this scaffold into your folder so it looks like:

```
your-project/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes_chat.py
│   │   ├── routes_documents.py
│   │   └── routes_admin.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── llm.py
│   │   ├── embeddings.py
│   │   ├── chunking.py
│   │   ├── vectorstore.py
│   │   ├── vlm.py
│   │   └── rag_chain.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py
│   └── db/
│       ├── __init__.py
│       └── metadata_store.py
├── storage/
│   ├── vector_indexes/
│   ├── uploads/
│   └── metadata/
├── requirements.txt
├── .env.example
└── README.md
```

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

Note: `docling` pulls in some heavier ML deps (it uses layout/OCR models
under the hood) — first install can take a few minutes. `turbovec` needs a
prebuilt wheel for your platform (Python 3.9+, no Rust toolchain required).

## 4. Configure your keys

```bash
cp .env.example .env
```

Open `.env` and fill in at least ONE provider key (e.g. `GEMINI_API_KEY`),
matching whatever you set as `DEFAULT_LLM_MODEL` / `DEFAULT_EMBEDDING_MODEL`.
LiteLLM reads provider keys straight from these env vars — you don't pass
keys manually in code anywhere.

Model string format is always `provider/model-name`, e.g.:
- `gemini/gemini-2.0-flash`
- `openai/gpt-4o-mini`
- `deepseek/deepseek-chat`

## 5. Run it

```bash
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000/docs` — FastAPI's auto-generated Swagger UI,
you can test every endpoint from the browser directly.

## 6. Try the flow

1. **Upload a document**: `POST /documents/ingest` (multipart form: `file`,
   optional `embedding_model`, `vlm_enabled`, `vlm_model`)
2. **Ask a question**: `POST /chat` with:
   ```json
   { "messages": [{ "role": "user", "content": "what does the document say about X?" }] }
   ```
3. Check `GET /documents` to see what's been ingested, and
   `GET /documents/collections` to see the TurboVec collections that exist
   (one per embedding-model+dims combination, per the spec).

## Excel/CSV ingestion (new)

`POST /documents/ingest` now also accepts `.xlsx`, `.xls`, and `.csv`:

- Each sheet (or the single CSV table) is written to its own real SQLite
  table in `storage/metadata/excel_data.sqlite3` — never embedded as raw
  row text. Only a compact **schema summary** (table name, columns +
  types, a couple of sample rows) gets embedded, so the table is
  discoverable by semantic search the same way a text/table chunk is.
- At `/chat` time, if retrieval surfaces one of these schema-summary
  chunks, the LLM is handed a `query_table` tool (LiteLLM function
  calling) backed by `app/core/sql_tool.py` — a sandboxed, read-only SQL
  executor (SELECT-only, single statement, row cap, timeout). The model
  writes the exact SQL it needs, gets the real computed result back, and
  answers from that — instead of guessing a number from similarity search.
  Executed queries show up in `retrieved_chunks` (`chunk_type:
  "sql_result"`) for citation/debugging in the same way text/table hits do.
- `GET /admin/documents/{id}/excel-tables` lists the underlying
  table_name/columns/row_count for a given ingested spreadsheet.

### Running the tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/ -v
```

The suite (32 tests) is fully offline — no API keys, no downloaded
embedding model, no live LLM calls:
- `test_excel_ingest.py` — sheet→table creation, CSV, column sanitization/
  dedup, multi-workbook table namespacing, schema summary content.
- `test_sql_tool.py` — correct aggregation/joins, and rejects
  DROP/DELETE/INSERT/UPDATE/PRAGMA/ATTACH/CREATE/stacked statements, row cap.
- `test_metadata_store_excel.py` — table-tracking CRUD.
- `test_rag_chain_sql.py` — the LLM tool-calling loop, with the LLM call
  mocked: verifies a normal SQL round trip, that a malicious tool call
  (e.g. `DROP TABLE`) is safely rejected without corrupting data, and that
  a model that keeps calling the tool forever is still cut off.
- `test_ingest_route_integration.py` — real FastAPI `TestClient` hitting
  `/documents/ingest` → `/documents` → `/admin/.../excel-tables` end to
  end, with only the embedding call mocked (fixed 8-dim vectors — TurboVec
  requires `dim` to be a multiple of 8, which every real embedding model
  satisfies).

### Manual end-to-end test (needs a real LLM key configured in `.env`)

1. `uvicorn app.main:app --reload --port 8000`
2. Ingest a spreadsheet:
   ```bash
   curl -F "file=@sample_sales.xlsx" http://localhost:8000/documents/ingest
   ```
   Expect `excel_tables` > 0 in the response, `text_chunks`/`table_chunks` = 0.
3. Check the table landed correctly:
   ```bash
   curl http://localhost:8000/admin/documents/<document_id>/excel-tables
   ```
4. Ask a question that requires computing over the data, not just finding text:
   ```bash
   curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
     -d '{"messages":[{"role":"user","content":"Berapa total revenue region West bulan lalu?"}]}'
   ```
   In the response, check `retrieved_chunks` for an entry with
   `"chunk_type": "sql_result"` — open its `sql` field and confirm the
   query is correct and the number in `reply` matches
   `SELECT SUM(...) FROM ... WHERE region = 'West'` run directly against
   `storage/metadata/excel_data.sqlite3` via `sqlite3` CLI, so you're
   checking the model's arithmetic against ground truth, not trusting it.
5. Ask a question the sheet can't answer (e.g. about a column that doesn't
   exist) and confirm the model says so instead of inventing a number.
6. Re-ingest the same file with a different `embedding_model` and confirm
   `GET /documents/collections` shows a second collection — table
   discovery must still work per-collection, same as text documents.



- **Auth** — no auth wired in yet (spec didn't mention it; add an API key
  or JWT dependency on the routers before exposing this publicly).
- **Qdrant comparison** — this scaffold ships TurboVec by default per your
  choice. If you want to benchmark against Qdrant too, add a second
  `vectorstore_qdrant.py` implementing the same `.add/.search/.save`
  interface as `TurboVecCollection`, and a config flag to pick between them.
- **LangGraph** — `core/rag_chain.py` has a commented-out LangGraph version
  at the bottom; swap to it once you need branching logic (e.g. skip
  retrieval for small talk, or retry with a rewritten query on low scores).
- **Frontend** — this is backend-only. Point a Next.js frontend at
  `POST /chat` and `POST /documents/ingest`.

## Notes on library versions

`turbovec` and `docling` are both fast-moving libraries. The wrapper code
here (`app/core/vectorstore.py`, `app/core/chunking.py`) isolates every call
into their actual SDKs into one file each — if `pip install` resolves a
newer version with a slightly different API, that's the only file you
should need to touch.
