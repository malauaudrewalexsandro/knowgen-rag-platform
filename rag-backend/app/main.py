import torch

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_admin, routes_chat, routes_documents
from app.config import settings
from app.core.embeddings import _get_local_model
from app.db import metadata_store

app = FastAPI(
    title="RAG Backend",
    description="LiteLLM + LangChain + TurboVec + Docling powered RAG service",
    version="0.1.0",
)

# Loosen for local dev; restrict allow_origins to your actual frontend
# domain(s) before deploying anywhere real.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_documents.router)
app.include_router(routes_chat.router)
app.include_router(routes_admin.router)


@app.on_event("startup")
def on_startup():
    metadata_store.init_db()

    # Force torch/sentence-transformers to load here, in the main thread,
    # at startup. On Windows, torch's DLL init (c10.dll) can fail with
    # WinError 1114 when it's first imported from a worker thread (e.g.
    # FastAPI's threadpool handling a sync request handler), because those
    # threads have a smaller stack size. Loading it once here avoids that.
    if settings.default_embedding_model.startswith("local/"):
        hf_name = settings.default_embedding_model.split("local/", 1)[1] or "all-MiniLM-L6-v2"
        print(f"Warming up local embedding model: {hf_name}")
        _get_local_model(hf_name)
        print("Embedding model warmed up successfully")


@app.get("/")
def root():
    return {"service": "rag-backend", "status": "running"}