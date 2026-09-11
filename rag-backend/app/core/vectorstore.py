"""
Vector storage on TurboVec.

Corrected against the real API (turbovec's public class is `IdMapIndex`, not
`Index` — an earlier draft of this file guessed wrong). Reference:
https://github.com/RyanCodrai/turbovec

Important: TurboVec is an *embedded* local index (Rust core, Python
bindings) — not a client/server database like Qdrant. Each "collection" in
our system is really one TurboVec index file on disk. We key collections by
`{embedding_model}__{dims}` so that switching embedding models (per the
requirement: different embed model => different collection) never mixes
incompatible vector spaces in one index.

IdMapIndex uses stable external uint64 ids (not positional slots) — we
generate a random uint64 per vector, and keep a JSON sidecar mapping that id
to our own payload (chunk text, doc id, page, type), since IdMapIndex itself
only stores vectors + ids.
"""
import json
import os
import random
import re
from dataclasses import dataclass, field

import numpy as np
from turbovec import IdMapIndex

from app.config import settings


def _collection_key(embedding_model: str, dims: int) -> str:
    safe_model = re.sub(r"[^a-zA-Z0-9_.-]", "_", embedding_model)
    return f"{safe_model}__{dims}d"


def _paths(collection_key: str) -> tuple[str, str]:
    base = os.path.join(settings.vector_index_dir, collection_key)
    return f"{base}.tvim", f"{base}.payloads.json"


@dataclass
class SearchHit:
    id: str
    score: float
    payload: dict = field(default_factory=dict)


class TurboVecCollection:
    """One embedding-model-specific index, with an id -> payload sidecar."""

    def __init__(self, embedding_model: str, dims: int, bit_width: int = 4):
        self.embedding_model = embedding_model
        self.dims = dims
        self.key = _collection_key(embedding_model, dims)
        self.index_path, self.payload_path = _paths(self.key)
        os.makedirs(settings.vector_index_dir, exist_ok=True)

        # payload store: external uint64 id (as str, JSON keys must be str)
        # -> arbitrary metadata dict (chunk text, doc id, page, chunk type).
        self._payloads: dict[str, dict] = {}

        if os.path.exists(self.index_path):
            self._index = IdMapIndex.load(self.index_path)
            if os.path.exists(self.payload_path):
                with open(self.payload_path) as f:
                    self._payloads = json.load(f)
        else:
            # 4-bit is the recommended default: strong recall/memory balance.
            self._index = IdMapIndex(dim=self.dims, bit_width=bit_width)

    def add(self, vector: list[float], payload: dict) -> str:
        vec_id = random.getrandbits(64)
        arr = np.asarray([vector], dtype=np.float32)
        ids_arr = np.array([vec_id], dtype=np.uint64)
        self._index.add_with_ids(arr, ids_arr)
        self._payloads[str(vec_id)] = payload
        return str(vec_id)

    def add_batch(self, vectors: list[list[float]], payloads: list[dict]) -> list[str]:
        return [self.add(v, p) for v, p in zip(vectors, payloads)]

    def search(self, query_vector: list[float], k: int = 5,
               allowlist_ids: list[str] | None = None) -> list[SearchHit]:
        query_arr = np.asarray([query_vector], dtype=np.float32)

        if allowlist_ids is not None:
            allowlist = np.array([int(i) for i in allowlist_ids], dtype=np.uint64)
            scores, ids = self._index.search(query_arr, k=k, allowlist=allowlist)
        else:
            scores, ids = self._index.search(query_arr, k=k)
        # search() is batched (one row per query); we send one query at a time.
        scores0, ids0 = scores[0], ids[0]

        results = []
        for score, vid in zip(scores0, ids0):
            key = str(int(vid))
            results.append(SearchHit(id=key, score=float(score), payload=self._payloads.get(key, {})))
        return results

    def save(self):
        self._index.write(self.index_path)
        with open(self.payload_path, "w") as f:
            json.dump(self._payloads, f)


_collections: dict[str, TurboVecCollection] = {}


def get_collection(embedding_model: str, dims: int) -> TurboVecCollection:
    """Cached accessor so repeated calls reuse the in-memory index/session."""
    key = _collection_key(embedding_model, dims)
    if key not in _collections:
        _collections[key] = TurboVecCollection(embedding_model, dims)
    return _collections[key]


def list_collections() -> list[str]:
    if not os.path.isdir(settings.vector_index_dir):
        return []
    return sorted(
        f[:-5] for f in os.listdir(settings.vector_index_dir) if f.endswith(".tvim")
    )
