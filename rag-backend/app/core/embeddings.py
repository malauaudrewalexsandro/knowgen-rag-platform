"""
Embedding calls go through LiteLLM so the actual provider (Gemini, OpenAI,
Cohere, ...) is just a config string — swapping providers never touches
business logic.

EXCEPTION: models prefixed "local/" (e.g. "local/all-MiniLM-L6-v2") run
through sentence-transformers directly, on-device, with no API key and no
per-call cost. This matters if your LLM provider (e.g. DeepSeek) doesn't
offer an embedding endpoint at all — you're not forced to sign up for a
second paid provider just to get embeddings.

Every call returns the vector *and* the model/dims metadata that produced
it, because that pair has to be recorded per-document (see db/metadata_store)
and used to route the vector into the correct TurboVec collection.
"""
from dataclasses import dataclass

import litellm

from app.config import settings

_local_model_cache: dict[str, object] = {}


@dataclass
class EmbeddingResult:
    vector: list[float]
    model: str
    dims: int


def _get_local_model(model_name: str):
    """Lazy-load and cache a sentence-transformers model by name."""
    if model_name not in _local_model_cache:
        from sentence_transformers import SentenceTransformer
        _local_model_cache[model_name] = SentenceTransformer(model_name)
    return _local_model_cache[model_name]


def _embed_local(texts: list[str], model: str) -> list[list[float]]:
    # "local/all-MiniLM-L6-v2" -> "all-MiniLM-L6-v2" (or any HF model id)
    hf_name = model.split("local/", 1)[1] or "all-MiniLM-L6-v2"
    st_model = _get_local_model(hf_name)
    vectors = st_model.encode(texts, convert_to_numpy=True)
    return [v.tolist() for v in vectors]


def embed_text(text: str, model: str | None = None) -> EmbeddingResult:
    """Embed a single string. Raises on empty input — callers should guard."""
    text = (text or "").strip()
    if not text:
        raise ValueError("embed_text: empty input")

    model = model or settings.default_embedding_model
    if model.startswith("local/"):
        vector = _embed_local([text], model)[0]
    else:
        resp = litellm.embedding(model=model, input=[text])
        vector = resp.data[0]["embedding"]
    return EmbeddingResult(vector=vector, model=model, dims=len(vector))


def embed_batch(texts: list[str], model: str | None = None) -> list[EmbeddingResult]:
    """Batch embed. LiteLLM batches provider-side where supported."""
    texts = [t.strip() for t in texts if t and t.strip()]
    if not texts:
        return []

    model = model or settings.default_embedding_model
    if model.startswith("local/"):
        vectors = _embed_local(texts, model)
        return [EmbeddingResult(vector=v, model=model, dims=len(v)) for v in vectors]

    resp = litellm.embedding(model=model, input=texts)
    return [
        EmbeddingResult(vector=item["embedding"], model=model, dims=len(item["embedding"]))
        for item in resp.data
    ]
