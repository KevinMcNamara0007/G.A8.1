"""CanonicalBaselineEncoder — reproduces the Phase 1 shattering path.

Mirrors TierEncoder's flat-array layout: no per-vector Python
dataclasses, only numpy arrays + C++ CSR indices.

Tokenizer is the v12.5 shatter (underscore → space, stopword filter,
min-length-2) to reproduce the Phase 1 behavior the plan targets.
Geometry is identical to TierEncoder — same codebook seed, dim, k,
superpose, BSCCompactIndex, BSCLSHIndex.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import numpy as np

for _d in (2, 3, 4):
    _p = Path(__file__).resolve().parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc  # noqa: E402


_STOP_WORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "is", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "may", "might",
    "can", "shall", "must", "and", "but", "or", "not", "no", "so",
    "if", "then", "than", "that", "this", "it", "its", "with", "from",
    "by", "about", "as", "into", "through", "during",
})


def _shatter_tokenize(*fields: str) -> List[str]:
    out: List[str] = []
    seen: set = set()
    for field in fields:
        if not field:
            continue
        for w in field.replace("_", " ").lower().split():
            if w in _STOP_WORDS or len(w) <= 1:
                continue
            if w not in seen:
                seen.add(w)
                out.append(w)
    return out


class CanonicalBaselineEncoder:
    """Shattered-tokenization encoder — the Phase 1 baseline.

    Per-vector storage is flat numpy (source_record_id only); tokens
    are retained optionally for introspection. The C++ CSR index owns
    the vectors after build_index().
    """

    def __init__(
        self,
        dim: int = 4096,
        k: int = 64,
        seed: int = 42,
        retain_tokens: bool = True,
        initial_capacity: int = 16384,
    ):
        self.dim = int(dim)
        self.k = int(k)
        self.seed = int(seed)
        self.retain_tokens = bool(retain_tokens)

        cfg = ehc.CodebookConfig()
        cfg.dim = self.dim
        cfg.k = self.k
        cfg.seed = self.seed
        self.codebook = ehc.TokenCodebook(cfg)
        self.codebook.build_from_vocabulary([])
        self.cache = ehc.LRUCache(max_size=50000) if hasattr(ehc, "LRUCache") else None

        self._capacity = int(initial_capacity)
        self._source_rid = np.full(self._capacity, -1, dtype=np.int32)
        self.n_vectors = 0

        self._tokens_ref: Optional[List[List[str]]] = [] if retain_tokens else None

        self._pending_vecs: List = []
        self._pending_ids: List[int] = []

        self._index: Optional[object] = None
        self._lsh: Optional[object] = None

    def _ensure_capacity(self, required: int) -> None:
        if required <= self._capacity:
            return
        new_cap = max(self._capacity * 2, required)
        self._source_rid = np.resize(self._source_rid, new_cap)
        self._capacity = new_cap

    def _encode_token(self, tok: str):
        if self.cache is not None:
            cached = self.cache.get(tok)
            if cached is not None:
                return cached
        try:
            tv = self.codebook.encode_token(tok)
        except Exception:
            return None
        if self.cache is not None and tv is not None:
            self.cache.put(tok, tv)
        return tv

    def _bind_tokens(self, tokens: List[str]):
        vecs = []
        for t in tokens:
            tv = self._encode_token(t)
            if tv is not None:
                vecs.append(tv)
        if not vecs:
            return None
        return ehc.superpose(vecs) if len(vecs) > 1 else vecs[0]

    def encode_record(self, record_id: int, record: dict) -> bool:
        s = record.get("subject", "")
        r = record.get("relation", "")
        o = record.get("object", record.get("text", ""))
        tokens = _shatter_tokenize(s, r, o)
        if not tokens:
            return False
        sv = self._bind_tokens(tokens)
        if sv is None:
            return False
        vec_id = self.n_vectors
        self._ensure_capacity(vec_id + 1)
        self._source_rid[vec_id] = int(record_id)
        if self._tokens_ref is not None:
            self._tokens_ref.append(tokens)
        self._pending_vecs.append(sv)
        self._pending_ids.append(vec_id)
        self.n_vectors += 1
        return True

    def build_index(self, lsh_tables: int = 8, lsh_hash_size: int = 16) -> None:
        self._index = ehc.BSCCompactIndex(self.dim, use_sign_scoring=True)
        if self._pending_vecs:
            self._index.add_items(self._pending_vecs, self._pending_ids)
            self._lsh = ehc.BSCLSHIndex(
                self.dim, self.k,
                num_tables=lsh_tables, hash_size=lsh_hash_size,
                use_multiprobe=True,
            )
            self._lsh.add_items(self._pending_vecs, self._pending_ids)

        # C++ CSR index owns the vectors now — drop python refs.
        self._pending_vecs = []
        self._pending_ids = []

        if self._capacity > self.n_vectors:
            self._source_rid = self._source_rid[:self.n_vectors].copy()
            self._capacity = self.n_vectors

    # ── query mirror ─────────────────────────────────────────
    def query(self, subject: str = "", relation: str = "", obj: str = "",
              text: str = "", k: int = 10, fetch_k: Optional[int] = None) -> list:
        fetch_k = fetch_k or max(k * 5, 20)
        tokens = _shatter_tokenize(subject, relation, obj, text)
        if not tokens:
            return []
        qvec = self._bind_tokens(tokens)
        if qvec is None:
            return []
        if self._lsh is not None:
            res = self._lsh.knn_query(qvec, k=fetch_k)
        else:
            res = self._index.knn_query(qvec, k=fetch_k)
        ids = np.asarray(res.ids, dtype=np.int64)
        scores = np.asarray(res.scores, dtype=np.float32)
        n = min(k, ids.size)
        src = self._source_rid[ids[:n]]
        out = []
        for i in range(n):
            vid = int(ids[i])
            toks = self._tokens_ref[vid] if self._tokens_ref and vid < len(self._tokens_ref) else []
            out.append({
                "vec_id": vid,
                "source_record_id": int(src[i]),
                "raw_score": float(scores[i]),
                "tokens": toks,
            })
        return out

    def vector_by_id(self, vec_id: int) -> Optional[dict]:
        if vec_id < 0 or vec_id >= self.n_vectors:
            return None
        return {
            "vec_id": vec_id,
            "source_record_id": int(self._source_rid[vec_id]),
            "tokens": (self._tokens_ref[vec_id]
                       if self._tokens_ref and vec_id < len(self._tokens_ref)
                       else None),
        }
