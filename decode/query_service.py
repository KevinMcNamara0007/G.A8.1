"""
G.A8.1 — C++ Query Service Layer (Hook Architecture)

C++ hot path: encode(text) → route(centroid_index) → search(shard_indices)
Hooks (pluggable): query_cleaner → reranker → enricher → learner

Seven hooks, one engine. Products override via hooks.py.
Convention over configuration: auto-detect what's available.

Usage:
    from query_service import QueryService
    from hooks import load_hooks

    hooks = load_hooks("/path/to/product")
    svc = QueryService("/path/to/encoded_output", hooks=hooks)
    results = svc.query("iran missile test", k=10)
"""

import asyncio
import json
import logging
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

import numpy as np

# ── EHC import ──────────────────────────────────────────────
for _depth in (2, 3, 4):
    _ehc = Path(__file__).resolve().parents[_depth] / "EHC" / "build" / "bindings" / "python"
    if _ehc.exists():
        sys.path.insert(0, str(_ehc))
        break
import ehc


STOP_WORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "is", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "may", "might",
    "can", "shall", "must", "and", "but", "or", "not", "no", "so",
    "if", "then", "than", "that", "this", "it", "its", "with", "from",
    "by", "about", "as", "into", "through", "during",
})

QUERY_FILTER_WORDS = frozenset({
    "find", "search", "show", "list", "get", "give", "tell", "display",
    "retrieve", "fetch", "lookup", "look", "query",
    "all", "any", "some", "every", "each",
    "documents", "document", "docs", "doc",
    "articles", "article", "posts", "post", "messages", "message",
    "records", "record", "entries", "entry", "items", "item",
    "results", "result", "matches", "match",
    "information", "info", "data", "details",
    "about", "regarding", "concerning", "involving", "related",
    "mentioning", "references", "discussing",
    "what", "where", "when", "how", "why", "which", "who", "whom",
    "me", "you", "us", "them", "it",
})


def _tokenize_query(text: str) -> list:
    """Tokenize query text — strips stop words and query filter words."""
    return [w for w in text.replace("_", " ").lower().split()
            if w not in STOP_WORDS and w not in QUERY_FILTER_WORDS and len(w) > 1]


class ShardData:
    """Pre-loaded shard: C++ index + sidecar metadata arrays."""
    __slots__ = ("shard_id", "index", "lsh", "media_index",
                 "sidecar",
                 "texts", "authors", "tags", "channels", "timestamps",
                 "media_paths", "urls", "values")

    def __init__(self, shard_dir: Path, dim: int = None):
        self.shard_id = int(shard_dir.name.split("_")[1])
        if dim is None:
            try:
                from config import cfg as _c
                dim = _c.DIM
            except ImportError:
                dim = 16384
        k = int(math.sqrt(dim))

        # ── C++ indices (searchable) ─────────────────────────
        idx_path = shard_dir / "index" / "chunk_index.npz"
        self.index = self._load_compact_index(idx_path, dim)

        lsh_path = shard_dir / "index" / "lsh_index.npz"
        self.lsh = self._load_lsh(lsh_path, dim, k) if lsh_path.exists() else None

        media_idx_path = shard_dir / "index" / "media_index.npz"
        self.media_index = self._load_compact_index(media_idx_path, dim) if media_idx_path.exists() else None

        # ── Sidecar metadata ─────────────────────────────────
        from sidecar_utils import ShardSidecar
        self.sidecar = ShardSidecar.open_dir(shard_dir)
        if self.sidecar is not None:
            self.texts = self.authors = self.tags = None
            self.channels = self.timestamps = None
            self.media_paths = self.urls = self.values = None
        else:
            meta_dir = shard_dir / "meta"
            if not meta_dir.exists():
                meta_dir = shard_dir
            self.texts = self._load_json(meta_dir / "texts.json",
                                         shard_dir / "texts.json")
            self.authors = self._load_json(meta_dir / "authors.json")
            self.tags = self._load_json(meta_dir / "tags.json")
            self.channels = self._load_json(meta_dir / "channels.json")
            self.timestamps = self._load_json(meta_dir / "timestamps.json")
            self.media_paths = self._load_json(meta_dir / "media_paths.json")
            self.urls = self._load_json(meta_dir / "urls.json")
            self.values = self._load_json(meta_dir / "values.json")

    @staticmethod
    def _load_json(*paths) -> list:
        for p in paths:
            if Path(p).exists():
                with open(p) as f:
                    return json.load(f)
        return []

    @staticmethod
    def _load_compact_index(npz_path, dim):
        if not Path(npz_path).exists():
            return None
        d = np.load(str(npz_path), allow_pickle=True)
        sign_scoring = int(d["use_sign_scoring"][0]) if "use_sign_scoring" in d else 1

        if hasattr(ehc, "MmapCompactIndex"):
            idx = ehc.MmapCompactIndex()
            ok = idx.load_from_arrays(
                int(d["dim"][0]), int(d["n_vectors"][0]), sign_scoring,
                np.ascontiguousarray(d["ids"], dtype=np.int32),
                np.ascontiguousarray(d["plus_data"], dtype=np.int32),
                np.ascontiguousarray(d["plus_offsets"], dtype=np.int64),
                np.ascontiguousarray(d["minus_data"], dtype=np.int32),
                np.ascontiguousarray(d["minus_offsets"], dtype=np.int64),
                np.ascontiguousarray(d["vec_indices"], dtype=np.int32),
                np.ascontiguousarray(d["vec_signs"], dtype=np.int8),
                np.ascontiguousarray(d["vec_offsets"], dtype=np.int64),
            )
            if ok:
                return idx

        idx = ehc.BSCCompactIndex(dim, True)
        idx.load_arrays(
            int(d["dim"][0]), int(d["n_vectors"][0]), sign_scoring,
            np.ascontiguousarray(d["ids"], dtype=np.int32),
            np.ascontiguousarray(d["plus_data"], dtype=np.int32),
            np.ascontiguousarray(d["plus_offsets"], dtype=np.int64),
            np.ascontiguousarray(d["minus_data"], dtype=np.int32),
            np.ascontiguousarray(d["minus_offsets"], dtype=np.int64),
            np.ascontiguousarray(d["vec_indices"], dtype=np.int32),
            np.ascontiguousarray(d["vec_signs"], dtype=np.int8),
            np.ascontiguousarray(d["vec_offsets"], dtype=np.int64),
        )
        return idx

    @staticmethod
    def _load_lsh(npz_path, dim, k):
        d = np.load(str(npz_path), allow_pickle=True)
        lsh_data = ehc.LSHIndexData()
        lsh_data.dim = int(d["dim"][0])
        lsh_data.k = int(d["k"][0])
        lsh_data.num_tables = int(d["num_tables"][0])
        lsh_data.hash_size = int(d["hash_size"][0])
        lsh_data.n_vectors = int(d["n_vectors"][0])
        lsh_data.ids = d["ids"].tolist()
        lsh_data.vec_indices = d["vec_indices"].astype(np.int32).tolist()
        lsh_data.vec_signs = d["vec_signs"].astype(np.int8).tolist()
        lsh_data.vec_offsets = d["vec_offsets"].tolist()
        nt = lsh_data.num_tables
        lsh_data.bucket_ids = [d[f"bucket_ids_{t}"].tolist() for t in range(nt)]
        lsh_data.bucket_offsets = [d[f"bucket_offsets_{t}"].tolist() for t in range(nt)]
        lsh = ehc.BSCLSHIndex(dim, k)
        lsh.deserialize(lsh_data)
        return lsh

    @staticmethod
    def _ms_to_iso(ms: int) -> str:
        """Epoch milliseconds → ISO-8601 UTC string for downstream compat."""
        from sidecar_utils import ms_to_iso
        return ms_to_iso(ms)

    def get_metadata(self, vec_id: int) -> dict:
        """O(1) sidecar lookup by vector ID. Returns original record fields."""
        if self.sidecar is not None:
            sc = self.sidecar
            n = sc.n_vectors()
            if vec_id >= n:
                return {k: "" for k in (
                    "message_text_translated", "message_text", "author",
                    "channel", "tags", "filtered_tags", "posted_at",
                    "media_path", "url", "text", "value", "timestamp")}
            tags = sc.tags(vec_id)
            ts_iso = self._ms_to_iso(sc.timestamp(vec_id))
            return {
                "message_text_translated": sc.text(vec_id),
                "message_text": sc.value(vec_id),
                "author": sc.author(vec_id),
                "channel": sc.channel(vec_id),
                "tags": tags,
                "filtered_tags": tags,
                "posted_at": ts_iso,
                "media_path": sc.media_path(vec_id),
                "url": sc.url(vec_id),
                "text": sc.text(vec_id),
                "value": sc.value(vec_id),
                "timestamp": ts_iso,
            }

        raw_tags = self.tags[vec_id] if vec_id < len(self.tags) else "[]"
        if isinstance(raw_tags, str):
            try:
                tags = json.loads(raw_tags)
            except (json.JSONDecodeError, ValueError):
                tags = raw_tags.split() if raw_tags else []
        else:
            tags = raw_tags

        return {
            "message_text_translated": self.texts[vec_id] if vec_id < len(self.texts) else "",
            "message_text": self.values[vec_id] if vec_id < len(self.values) else "",
            "author": self.authors[vec_id] if vec_id < len(self.authors) else "",
            "channel": self.channels[vec_id] if vec_id < len(self.channels) else "",
            "tags": tags,
            "filtered_tags": tags,
            "posted_at": self.timestamps[vec_id] if vec_id < len(self.timestamps) else "",
            "media_path": self.media_paths[vec_id] if vec_id < len(self.media_paths) else "",
            "url": self.urls[vec_id] if vec_id < len(self.urls) else "",
            "text": self.texts[vec_id] if vec_id < len(self.texts) else "",
            "value": self.values[vec_id] if vec_id < len(self.values) else "",
            "timestamp": self.timestamps[vec_id] if vec_id < len(self.timestamps) else "",
        }


class QueryResult:
    """Single result with score + metadata."""
    __slots__ = ("shard_id", "vec_id", "bsc_score", "combined_score", "metadata")

    def __init__(self, shard_id, vec_id, bsc_score, metadata):
        self.shard_id = shard_id
        self.vec_id = vec_id
        self.bsc_score = bsc_score
        self.combined_score = bsc_score
        self.metadata = metadata

    def to_dict(self) -> dict:
        return {
            "id": f"s{self.shard_id}_{self.vec_id}",
            "shard_id": self.shard_id,
            "similarity": round(self.combined_score, 4),
            "bsc_score": round(self.bsc_score, 4),
            "metadata": self.metadata,
        }


class QueryService:
    """G.A8.1 C++ Query Service (Hook Architecture).

    Startup: loads all shard indices + centroid router + hooks.
    Query: [hook: clean] → encode (C++) → route (C++) → search (C++) →
           [hook: rerank] → [hook: enrich] → [hook: learn]
    """

    def __init__(self, run_dir: str, dim: int = None, hooks=None,
                 product_dir: str = None, context: dict = None):
        # ── Load config ──────────────────────────────────────
        try:
            # config.py lives at G.A8.1 root
            _cfg_dir = str(Path(__file__).resolve().parent.parent)
            if _cfg_dir not in sys.path:
                sys.path.insert(0, _cfg_dir)
            from config import cfg as a81_cfg
        except ImportError:
            a81_cfg = None

        self.run_dir = Path(run_dir)
        self.dim = dim if dim is not None else (a81_cfg.DIM if a81_cfg else 16384)
        self.k = int(math.sqrt(self.dim))
        self.context = context or {}
        self._cfg = a81_cfg

        t0 = time.perf_counter()

        # ── Load hooks (auto-detect or explicit) ─────────────
        from hooks import load_hooks, DEFAULT_HOOKS
        if hooks is not None:
            self.hooks = hooks
        else:
            self.hooks = load_hooks(product_dir=product_dir, index_dir=run_dir)
        print(f"[QueryService] Hooks: {self.hooks.name}")

        # ── C++ encoder (hash-based, deterministic) ──────────
        _seed = a81_cfg.SEED if a81_cfg else 42
        cfg = ehc.CodebookConfig()
        cfg.dim = self.dim
        cfg.k = self.k
        cfg.seed = _seed
        self.codebook = ehc.TokenCodebook(cfg)
        self.codebook.build_from_vocabulary([])

        # C++ phrase cache
        self.phrase_cache = ehc.LRUCache(max_size=10000) if hasattr(ehc, "LRUCache") else None

        # ── Load all shards ──────────────────────────────────
        self.shards: Dict[int, ShardData] = {}
        for sd in sorted(self.run_dir.glob("shard_*")):
            shard = ShardData(sd, self.dim)
            self.shards[shard.shard_id] = shard

        # ── Build centroid routing index (C++ CompactIndex) ──
        self.centroid_index = ehc.BSCCompactIndex(self.dim, use_sign_scoring=True)
        cvecs, cids = [], []
        for sid, shard in self.shards.items():
            cp = self.run_dir / f"shard_{sid:04d}" / "centroid.npz"
            if cp.exists():
                cd = np.load(str(cp))
                cvec = ehc.SparseVector(self.dim,
                    np.array(cd["indices"], dtype=np.int32),
                    np.array(cd["signs"], dtype=np.int8))
                cvecs.append(cvec)
                cids.append(sid)
        if cvecs:
            self.centroid_index.add_items(cvecs, cids)

        # ── Selective attention for reranking ─────────────────
        # ── Thread pool for parallel shard search ─────────────
        # EHC knn_query releases GIL → true parallel on threads
        self._executor = ThreadPoolExecutor(
            max_workers=min(len(self.shards), 8),
            thread_name_prefix="a81_search",
        )

        _att_beta = a81_cfg.ATTENTION_BETA if a81_cfg else 1.5
        _att_min = a81_cfg.ATTENTION_MIN_SCORE if a81_cfg else 0.0
        self.attention = ehc.SelectiveAttention(beta=_att_beta, min_score=_att_min) \
            if hasattr(ehc, "SelectiveAttention") else None

        # ── Adaptive gazetteer (Hebbian + Ebbinghaus) ─────────
        # Disabled by default. Enable for diverse corpora where
        # Hebbian learning can differentiate signal from noise.
        # On homogeneous corpora (single-domain OSINT), static
        # gazetteer + concept family expansion performs better.
        # Enable via: A81_ADAPTIVE_GAZ=1 environment variable
        self.adaptive_gaz = None
        _adaptive = (a81_cfg.ADAPTIVE_GAZ if a81_cfg
                     else os.environ.get("A81_ADAPTIVE_GAZ") == "1")
        if _adaptive:
            try:
                from adaptive_gazetteer import AdaptiveGazetteer
                self.adaptive_gaz = AdaptiveGazetteer(
                    query_service=self,
                    index_dir=run_dir,
                )
                self.adaptive_gaz.start()
                print(f"[QueryService] Adaptive gazetteer: {self.adaptive_gaz.stats}")
            except Exception as e:
                print(f"[QueryService] Adaptive gazetteer failed: {e}")

        elapsed = time.perf_counter() - t0
        total_vecs = sum(s.index.size() for s in self.shards.values() if s.index)
        n_media = sum(1 for s in self.shards.values() if s.media_index)
        print(f"[QueryService] Ready: {len(self.shards)} shards, "
              f"{total_vecs:,} vectors, {n_media} media indices, "
              f"{elapsed:.1f}s")

    def _encode_query(self, text: str) -> Optional['ehc.SparseVector']:
        """Encode query text as superpose(tokens). Entire path in C++."""
        tokens = _tokenize_query(text)
        if not tokens:
            return None
        vecs = []
        for w in tokens:
            cached = self.phrase_cache.get(w) if self.phrase_cache else None
            if cached is None:
                try:
                    cached = self.codebook.encode_token(w)
                    if self.phrase_cache:
                        self.phrase_cache.put(w, cached)
                except Exception:
                    continue
            vecs.append(cached)
        if not vecs:
            return None
        return ehc.superpose(vecs) if len(vecs) > 1 else vecs[0]

    def _route(self, qvec: 'ehc.SparseVector', n_shards: int = 3) -> List[int]:
        """Route query to top-N shards via C++ centroid knn. Sub-ms."""
        if self.centroid_index.size() == 0:
            return list(self.shards.keys())[:n_shards]
        result = self.centroid_index.knn_query(qvec, k=n_shards)
        return [int(sid) for sid in result.ids]

    def _search_shard(self, shard: ShardData, qvec: 'ehc.SparseVector',
                      k: int = 50) -> List[QueryResult]:
        """Search one shard via C++ LSH → CompactIndex. Sub-ms per shard."""
        # LSH for candidate narrowing, CompactIndex as fallback
        if shard.lsh:
            result = shard.lsh.knn_query(qvec, k=k)
        elif shard.index:
            result = shard.index.knn_query(qvec, k=k)
        else:
            return []

        results = []
        for vid, score in zip(result.ids, result.scores):
            vid = int(vid)
            meta = shard.get_metadata(vid)
            results.append(QueryResult(shard.shard_id, vid, float(score), meta))
        return results

    def _keyword_score(self, query_tokens: list, text: str) -> float:
        """Keyword overlap scoring (edge-compatible)."""
        if not query_tokens or not text:
            return 0.0
        text_lower = text.lower()
        matches = sum(1 for t in query_tokens if t in text_lower)
        return (matches * 100.0) / len(query_tokens)

    def _proximity_score(self, query_tokens: list, text: str) -> float:
        """Adjacent term pair bonus (edge-compatible)."""
        if len(query_tokens) < 2:
            return 0.0
        text_lower = text.lower()
        phrase = " ".join(query_tokens)
        if phrase in text_lower:
            return 100.0
        total_pairs = len(query_tokens) - 1
        pairs_found = sum(1 for i in range(total_pairs)
                         if f"{query_tokens[i]} {query_tokens[i+1]}" in text_lower)
        return (pairs_found * 100.0) / total_pairs if total_pairs > 0 else 0.0

    def query(self, text: str, k: int = None, n_shards: int = None,
              has_media: bool = None, tags_any: list = None,
              prefer_recent: bool = False,
              recency_half_life_hours: int = 72) -> dict:
        """Full query with hook architecture.

        C++ core: encode → route → search
        Hooks: clean → rerank → enrich → learn

        Returns dict matching edge's QueryResponse schema.
        """
        t0 = time.perf_counter()
        from hooks import ScoredResult

        # Apply config defaults
        if k is None:
            k = self._cfg.QUERY_TOP_K if self._cfg else 10
        if n_shards is None:
            n_shards = self._cfg.QUERY_SHARDS if self._cfg else 3

        # ── HOOK: query_cleaner ──────────────────────────────
        cleaned = self.hooks.query_cleaner(text)

        # ── Adaptive gazetteer expansion (learned associations) ─
        if self.adaptive_gaz:
            pre_count = len(cleaned.tokens)
            cleaned.tokens = self.adaptive_gaz.expand_tokens(cleaned.tokens)
            cleaned.cleaned = " ".join(cleaned.tokens)
            if len(cleaned.tokens) > pre_count:
                logger.info(f"[AdaptiveGaz] Expanded {pre_count} → {len(cleaned.tokens)} tokens")

        # ── ENCODE (C++ — uses cleaned tokens) ───────────────
        qvec = self._encode_query(cleaned.cleaned)
        if qvec is None:
            return {"results": [], "confidence": 0.0,
                    "audit": {"duration_ms": 0, "strategy": "empty_query"}}

        # ── ROUTE (C++ centroid knn) ─────────────────────────
        target_shard_ids = self._route(qvec, n_shards)

        # ── SEARCH (C++ per-shard knn — PARALLEL) ────────────
        # EHC knn_query releases GIL → true parallel on threads
        fetch_k = k * (self._cfg.QUERY_FETCH_MULTIPLIER if self._cfg else 5)

        def _search_one(sid):
            shard = self.shards.get(sid)
            if shard is None:
                return []
            return self._search_shard(shard, qvec, k=fetch_k)

        futures = [self._executor.submit(_search_one, sid)
                   for sid in target_shard_ids]
        raw_results = []
        for f in futures:
            raw_results.extend(f.result())

        # Convert to ScoredResult for hooks
        scored = []
        for r in raw_results:
            # Format media_url for frontend
            mp = r.metadata.get("media_path", "")
            if mp:
                r.metadata["media_url"] = f"/media/{Path(mp).name}"
                r.metadata["media_files"] = [r.metadata["media_url"]]
            else:
                r.metadata["media_url"] = None
                r.metadata["media_files"] = []

            scored.append(ScoredResult(
                id=f"s{r.shard_id}_{r.vec_id}",
                shard_id=r.shard_id,
                vec_id=r.vec_id,
                bsc_score=r.bsc_score,
                combined_score=r.bsc_score,
                metadata=r.metadata,
            ))

        # ── HOOK: reranker ───────────────────────────────────
        hook_context = {
            **self.context,
            "prefer_recent": prefer_recent,
            "recency_half_life_hours": recency_half_life_hours,
        }
        scored = self.hooks.reranker(cleaned, scored, hook_context)

        # ── DEDUP (first 100 chars of text) ──────────────────
        seen = set()
        deduped = []
        for r in scored:
            text_key = (r.metadata.get("message_text_translated") or
                        r.metadata.get("text", ""))[:100].strip().lower()
            if text_key and text_key in seen:
                continue
            seen.add(text_key)
            deduped.append(r)
            if len(deduped) >= k * 2:  # keep extra for filtering
                break

        # ── FILTER ───────────────────────────────────────────
        if has_media is True:
            deduped = [r for r in deduped if r.metadata.get("media_url")]
        if has_media is False:
            deduped = [r for r in deduped if not r.metadata.get("media_url")]
        if tags_any:
            tags_set = set(t.lower() for t in tags_any)
            deduped = [r for r in deduped
                       if any(t in str(r.metadata.get("tags", "")).lower()
                              for t in tags_set)]

        deduped = deduped[:k]

        # ── HOOK: enricher ───────────────────────────────────
        deduped = self.hooks.enricher(cleaned, deduped)

        # ── HOOK: learner (async, non-blocking) ──────────────
        try:
            self.hooks.learner(cleaned, deduped)
        except Exception:
            pass  # Never break the query for learning

        # ── Adaptive gazetteer: learn from results ─────────────
        if self.adaptive_gaz and deduped:
            avg_score = sum(r.combined_score for r in deduped) / max(len(deduped), 1)
            # Extract terms from top-scoring results
            result_terms = []
            for r in deduped[:5]:  # top-5 only
                text = (r.metadata.get("message_text_translated") or
                        r.metadata.get("text", ""))
                tags = r.metadata.get("tags", [])
                if isinstance(tags, list):
                    result_terms.extend(tags)
                words = text.lower().split()
                result_terms.extend(w for w in words if len(w) >= 4)
            self.adaptive_gaz.observe(cleaned.tokens, result_terms, avg_score)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        confidence = deduped[0].combined_score if deduped else 0.0

        # ── FORMAT response ──────────────────────────────────
        results = []
        for r in deduped:
            results.append({
                "id": r.id,
                "similarity": round(r.combined_score, 4),
                "bsc_score": round(r.bsc_score, 4),
                "metadata": r.metadata,
            })

        return {
            "results": results,
            "confidence": round(confidence, 4),
            "audit": {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "duration_ms": round(elapsed_ms, 2),
                "strategy": f"a81_cpp_{self.hooks.name}",
                "shards_searched": len(target_shard_ids),
                "candidates_before_dedup": len(raw_results),
                "hooks": self.hooks.name,
            },
        }

    async def aquery(self, text: str, **kwargs) -> dict:
        """Async query — offloads C++ work to thread pool.
        Use from FastAPI: result = await svc.aquery("iran missile", k=10)
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, lambda: self.query(text, **kwargs))

    async def aquery_images(self, text: str, **kwargs) -> dict:
        """Async image query."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, lambda: self.query_images(text, **kwargs))

    async def aquery_multimodal(self, text: str, **kwargs) -> dict:
        """Async multimodal query."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, lambda: self.query_multimodal(text, **kwargs))

    def query_images(self, text: str, k: int = 10, n_shards: int = 5) -> dict:
        """Query the separate media indices. Returns image results with parent text."""
        t0 = time.perf_counter()
        qvec = self._encode_query(text)
        if qvec is None:
            return {"results": [], "confidence": 0.0, "audit": {"duration_ms": 0}}

        target_shard_ids = self._route(qvec, n_shards)

        def _search_media_one(sid):
            shard = self.shards.get(sid)
            if shard is None or shard.media_index is None:
                return []
            result = shard.media_index.knn_query(qvec, k=k * 3)
            hits = []
            for vid, score in zip(result.ids, result.scores):
                vid = int(vid)
                meta = shard.get_metadata(vid)
                mp = meta.get("media_path", "")
                if mp:
                    meta["media_url"] = f"/media/{Path(mp).name}"
                    hits.append(QueryResult(sid, vid, float(score), meta))
            return hits

        futures = [self._executor.submit(_search_media_one, sid)
                   for sid in target_shard_ids]
        all_results = []
        for f in futures:
            all_results.extend(f.result())

        all_results.sort(key=lambda r: -r.bsc_score)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        return {
            "results": [r.to_dict() for r in all_results[:k]],
            "confidence": all_results[0].bsc_score if all_results else 0.0,
            "audit": {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "duration_ms": round(elapsed_ms, 2),
                "strategy": "a81_cpp_media_search",
            },
        }

    def query_multimodal(self, text: str, k: int = 10,
                         image_weight: float = 0.3) -> dict:
        """Parallel text + image search, merged with configurable weight."""
        t0 = time.perf_counter()

        text_results = self.query(text, k=k * 2)
        image_results = self.query_images(text, k=k * 2)

        # Merge: text results get (1-image_weight), image results get image_weight
        merged = {}
        for r in text_results["results"]:
            merged[r["id"]] = {
                **r,
                "similarity": r["similarity"] * (1 - image_weight),
            }
        for r in image_results["results"]:
            rid = r["id"]
            if rid in merged:
                merged[rid]["similarity"] += r["similarity"] * image_weight
            else:
                merged[rid] = {
                    **r,
                    "similarity": r["similarity"] * image_weight,
                }

        results = sorted(merged.values(), key=lambda r: -r["similarity"])[:k]

        elapsed_ms = (time.perf_counter() - t0) * 1000
        return {
            "results": results,
            "confidence": results[0]["similarity"] if results else 0.0,
            "audit": {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "duration_ms": round(elapsed_ms, 2),
                "strategy": "a81_cpp_multimodal",
            },
        }

    def reload_shards(self, shard_ids: set = None):
        """Reload shard data from disk after incremental ingest.

        Args:
            shard_ids: specific shards to reload. None = reload all.
        """
        targets = shard_ids or set(self.shards.keys())
        reloaded = 0
        for sid in targets:
            sd = self.run_dir / f"shard_{sid:04d}"
            if sd.exists():
                self.shards[sid] = ShardData(sd, self.dim)
                reloaded += 1
        if reloaded:
            logger.info(f"[QueryService] Reloaded {reloaded} shards")
        return reloaded

    @property
    def stats(self) -> dict:
        """Service statistics for /health/stats endpoint."""
        total_vecs = sum(s.index.size() for s in self.shards.values() if s.index)
        total_media = sum(s.media_index.size() for s in self.shards.values()
                         if s.media_index)
        return {
            "n_shards": len(self.shards),
            "total_vectors": total_vecs,
            "total_media_vectors": total_media,
            "dim": self.dim,
            "k": self.k,
            "centroid_index_size": self.centroid_index.size(),
            "engine": "G.A8.1 C++ (EHC)",
        }
