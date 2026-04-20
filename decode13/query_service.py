"""decode13/query_service — shard-aware v13 query service.

Loads the shard layout that G.A8.1 encode/encode.py writes to disk and
natively handles tier routing, per-shard TierManifest compat, and tier-
weighted retrieval. Supersedes the bolt-on path in decode2/query_service.

Shard directory layout (written by encode/worker_encode.py when
A81_TIER_ROUTED=1):

    shard_NNNN/
      index/chunk_index.npz          BSCCompactIndex serialization
      index/lsh_index.npz            BSCLSHIndex serialization
      sidecar.ehs                    EHS1 binary metadata (text, value, etc.)
      sidecar.manifest               sidecar manifest
      symmetry_manifest.json         SymmetryManifest (legacy)
      tier_manifest.json             TierManifest registry (v13)
      tier_manifest.npy              flat per-vector manifest_id array
      centroid.npz                   per-shard centroid (for routing)
      texts.json                     legacy JSON sidecar (fallback)

Hot path:

    query text ─► TierRouter.classify ─► tier tokens ─► C++ superpose
                                                         │
    centroid_index.knn_query ◄───────────────────────────┘
           │
           ▼
    per-shard BSCLSHIndex.knn_query (parallel via ThreadPool, GIL-free)
           │
           ▼
    per-shard filter by TierManifest(axes_used)
           │
           ▼
    tier-weighted score + merge + top-k
           │
           ▼
    sidecar metadata attach (EHS1)

Everything heavy is C++ (codebook, superpose, knn, sparse_cosine, EHS1
reader). Python handles routing, merge, and tier weighting.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

# ── EHC import ──────────────────────────────────────────────
for _d in (2, 3, 4):
    _p = Path(__file__).resolve().parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from canonical.pipeline import CanonicalizationPipeline  # noqa: E402
from sidecar_utils import ShardSidecar  # noqa: E402

from .emergent_pipeline import EmergentStructureFallback
from .extraction_pipeline import ExtractionPipeline
from .structured_pipeline import StructuredAtomicPipeline
from .tier_manifest import ManifestRegistry13, TierManifest, int_to_tier
from .tier_router import TierRouter
from .tier_types import Tier


TIER_WEIGHT = {
    Tier.STRUCTURED_ATOMIC: 1.00,
    Tier.EXTRACTED_TRIPLE: 0.70,
    Tier.EMERGENT_STRUCTURE: 0.40,
}
GATE_BONUS = 0.20


# ═══════════════════════════════════════════════════════════════
#  ShardData13 — loads one shard off disk
# ═══════════════════════════════════════════════════════════════

class ShardData13:
    """One on-disk shard loaded for query-time use."""

    __slots__ = (
        "shard_id", "index", "lsh", "sidecar",
        "tier_registry", "legacy_texts",
    )

    def __init__(self, shard_dir: Path, dim: int, k: int):
        self.shard_id = int(shard_dir.name.split("_")[1])

        idx_path = shard_dir / "index" / "chunk_index.npz"
        self.index = self._load_compact_index(idx_path, dim) \
            if idx_path.exists() else None
        lsh_path = shard_dir / "index" / "lsh_index.npz"
        self.lsh = self._load_lsh(lsh_path, dim, k) \
            if lsh_path.exists() else None

        self.sidecar = ShardSidecar.open_dir(shard_dir)
        # Legacy JSON fallback when EHS1 sidecar unavailable
        self.legacy_texts: Optional[List[str]] = None
        if self.sidecar is None:
            jpath = shard_dir / "texts.json"
            if jpath.exists():
                with open(jpath) as f:
                    self.legacy_texts = json.load(f)

        # Per-vector tier manifest (v13). Absent on legacy shards.
        tm_path = shard_dir / "tier_manifest.json"
        self.tier_registry: Optional[ManifestRegistry13] = (
            ManifestRegistry13.load(tm_path) if tm_path.exists() else None
        )

    @staticmethod
    def _load_compact_index(npz_path: Path, dim: int):
        d = np.load(str(npz_path), allow_pickle=True)
        sign_scoring = int(d["use_sign_scoring"][0]) if "use_sign_scoring" in d else 1
        idx = ehc.BSCCompactIndex(dim, use_sign_scoring=bool(sign_scoring))
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
    def _load_lsh(npz_path: Path, dim: int, k: int):
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

    def get_text(self, vec_id: int) -> str:
        if self.sidecar is not None:
            try:
                return self.sidecar.text(vec_id) or ""
            except Exception:
                return ""
        if self.legacy_texts is not None and 0 <= vec_id < len(self.legacy_texts):
            return self.legacy_texts[vec_id]
        return ""

    def get_value(self, vec_id: int) -> str:
        if self.sidecar is not None:
            try:
                return self.sidecar.value(vec_id) or ""
            except Exception:
                return ""
        return ""

    def tier_of(self, vec_id: int) -> Optional[Tier]:
        if self.tier_registry is None:
            return None
        return self.tier_registry.tier_of(vec_id)

    def size(self) -> int:
        if self.index is None:
            return 0
        return int(self.index.size())


# ═══════════════════════════════════════════════════════════════
#  QueryHit13 — one result row
# ═══════════════════════════════════════════════════════════════

@dataclass
class QueryHit13:
    shard_id: int
    vec_id: int
    tier: Optional[Tier]
    raw_score: float
    tier_weight: float
    ranking_score: float
    text: str
    value: str
    matched_via: str = ""

    def to_dict(self) -> dict:
        return {
            "shard_id": self.shard_id,
            "vec_id": self.vec_id,
            "tier": self.tier.value if self.tier else None,
            "raw_score": round(self.raw_score, 4),
            "tier_weight": round(self.tier_weight, 3),
            "ranking_score": round(self.ranking_score, 4),
            "text": self.text,
            "value": self.value,
            "matched_via": self.matched_via,
        }


# ═══════════════════════════════════════════════════════════════
#  QueryService — the v13 shard-aware decoder
# ═══════════════════════════════════════════════════════════════

class QueryService:
    """v13 shard-aware query service.

    Loads a directory of shards written by G.A8.1 encode.py. Each query
    is tier-classified, dispatched to the matching tier pipeline, routed
    via the centroid index, fanned out to top-N shards in parallel,
    filtered per-shard by TierManifest(axes_used), ranked by tier-
    weighted score, and returned with EHS1 sidecar metadata.

    Hooks are intentionally omitted — this class is the *clean v13 core*.
    Hook integration can wrap it later.
    """

    def __init__(
        self,
        run_dir: str,
        dim: Optional[int] = None,
        k: Optional[int] = None,
        tenant_domain: str = "default::default",
        gate_mode: str = "default",
    ):
        self.run_dir = Path(run_dir)
        if not self.run_dir.exists():
            raise FileNotFoundError(f"run_dir does not exist: {run_dir}")

        # Resolve dim + k from config.py if not explicit.
        if dim is None or k is None:
            try:
                sys.path.insert(0, str(_ROOT))
                from config import cfg as _cfg
                dim = dim or _cfg.DIM
                k = k or _cfg.K
            except Exception:
                dim = dim or 16384
                k = k or int(math.sqrt(dim))
        self.dim = int(dim)
        self.k = int(k)

        # Canonical pipeline (for Tier 2 extraction decode-side).
        self.canonical = CanonicalizationPipeline()
        self.router = TierRouter()
        self.tier1 = StructuredAtomicPipeline()
        self.tier2 = ExtractionPipeline(canonical=self.canonical, gate_mode=gate_mode)
        self.tier3 = EmergentStructureFallback(canonical=self.canonical)
        self.tenant_domain = tenant_domain

        # Codebook — must match the encode-side seed.
        cfg = ehc.CodebookConfig()
        cfg.dim = self.dim
        cfg.k = self.k
        cfg.seed = int(os.environ.get("A81_SEED", "42"))
        self.codebook = ehc.TokenCodebook(cfg)
        self.codebook.build_from_vocabulary([])
        self.phrase_cache = ehc.LRUCache(max_size=5000) \
            if hasattr(ehc, "LRUCache") else None

        # Load shards.
        t0 = time.perf_counter()
        self.shards: Dict[int, ShardData13] = {}
        for d in sorted(self.run_dir.glob("shard_*")):
            if not d.is_dir():
                continue
            shard = ShardData13(d, self.dim, self.k)
            if shard.index is not None:
                self.shards[shard.shard_id] = shard

        # Centroid index (one vector per shard, for routing).
        self.centroid_index = ehc.BSCCompactIndex(self.dim, use_sign_scoring=True)
        cvecs = []
        cids = []
        for sid, shard in self.shards.items():
            cpath = self.run_dir / f"shard_{sid:04d}" / "centroid.npz"
            if cpath.exists():
                cd = np.load(str(cpath))
                inds = np.ascontiguousarray(cd["indices"], dtype=np.int32)
                sgns = np.ascontiguousarray(cd["signs"], dtype=np.int8)
                cvecs.append(ehc.SparseVector(self.dim, inds, sgns))
                cids.append(sid)
        if cvecs:
            self.centroid_index.add_items(cvecs, cids)

        self._executor = ThreadPoolExecutor(
            max_workers=min(max(len(self.shards), 1), 16),
            thread_name_prefix="decode13_search",
        )

        # Decode-time TierManifest (our local reference).
        self.decode_manifest = TierManifest.from_symmetry(
            self.canonical.manifest,
            tier=Tier.STRUCTURED_ATOMIC,
            tenant_domain=tenant_domain,
        )

        # Tier counts summary
        tier_totals = {t.value: 0 for t in Tier}
        total_vecs = 0
        for shard in self.shards.values():
            total_vecs += shard.size()
            if shard.tier_registry is not None:
                s = shard.tier_registry.summary()
                for tk, tc in s["tier_counts"].items():
                    tier_totals[tk] = tier_totals.get(tk, 0) + tc

        print(f"[decode13.QueryService] {len(self.shards)} shards, "
              f"{total_vecs:,} vectors, tier_counts={tier_totals}, "
              f"{time.perf_counter()-t0:.1f}s")

    # ── query tokenization ──────────────────────────────────
    def _atomic_tokens_from_text(self, text: str) -> Tuple[List[str], Set[str]]:
        """Shape-route the query and return (tokens, axes_used).

        Mirror of the TierRouter logic used on encode. Atomic compounds
        preserved; narrative text extracted to triples; fallback bag.
        """
        stripped = (text or "").strip()
        if not stripped:
            return [], {"escape"}
        parts = stripped.split()
        has_sentence_punct = any(c in stripped for c in ".!?")
        looks_structured = (
            len(parts) <= 4
            and any("_" in p for p in parts)
            and not has_sentence_punct
        )
        if looks_structured:
            return [p.lower() for p in parts if p], {"escape"}

        tier = self.router.classify(text=stripped)
        if tier == Tier.EXTRACTED_TRIPLE:
            dec = self.tier2.extract(stripped)
            if dec.tier == Tier.EXTRACTED_TRIPLE and dec.triples:
                tokens: List[str] = []
                for tri in dec.triples:
                    for t in (tri.subject, tri.relation, tri.obj):
                        if t and t not in tokens:
                            tokens.append(t)
                return tokens, {"escape"}
            dec = self.tier3.emit(stripped)
            return list(dec.fallback_tokens), {"escape"}

        dec = self.tier3.emit(stripped)
        return list(dec.fallback_tokens), {"escape"}

    def _encode_tokens(self, tokens: List[str]):
        if not tokens:
            return None
        vecs = []
        for t in tokens:
            cached = self.phrase_cache.get(t) if self.phrase_cache else None
            if cached is None:
                try:
                    cached = self.codebook.encode_token(t)
                    if self.phrase_cache:
                        self.phrase_cache.put(t, cached)
                except Exception:
                    continue
            vecs.append(cached)
        if not vecs:
            return None
        return ehc.superpose(vecs) if len(vecs) > 1 else vecs[0]

    # ── routing ─────────────────────────────────────────────
    def _route(self, qvec, n_shards: int) -> List[int]:
        if self.centroid_index.size() == 0:
            return list(self.shards.keys())[:n_shards]
        res = self.centroid_index.knn_query(qvec, k=n_shards)
        return [int(sid) for sid in res.ids]

    def _all_shard_ids(self) -> List[int]:
        return list(self.shards.keys())

    # ── per-shard search (parallel) ─────────────────────────
    def _search_shard(
        self, shard: ShardData13, qvec, fetch_k: int,
        axes_used: Optional[Set[str]],
    ) -> List[Tuple[int, float, Optional[Tier], float]]:
        """Return [(vec_id, raw_score, tier, tier_weight), ...]."""
        if shard.lsh is not None:
            res = shard.lsh.knn_query(qvec, k=fetch_k)
        elif shard.index is not None:
            res = shard.index.knn_query(qvec, k=fetch_k)
        else:
            return []

        ids = np.asarray(res.ids, dtype=np.int64)
        scores = np.asarray(res.scores, dtype=np.float32)
        if ids.size == 0:
            return []

        # Per-shard manifest compat filter.
        if shard.tier_registry is not None:
            compat_per_mid = shard.tier_registry.precompute_compat(axes_used)
            mids = shard.tier_registry.manifest_ids_for(ids)
            mask = compat_per_mid[mids] if compat_per_mid.size \
                else np.zeros(ids.size, dtype=bool)
            if not mask.any():
                return []
            ids = ids[mask]
            scores = scores[mask]
            # Tier + weight per surviving candidate.
            tiers = [shard.tier_registry.manifest_for(int(v)) for v in ids]
            out: List[Tuple[int, float, Optional[Tier], float]] = []
            for vid, sc, m in zip(ids, scores, tiers):
                if m is None:
                    continue
                tier = m.tier
                w = TIER_WEIGHT.get(tier, 0.4)
                if tier == Tier.EXTRACTED_TRIPLE and m.gate_agreement:
                    w = min(1.0, w + GATE_BONUS)
                out.append((int(vid), float(sc), tier, float(w)))
            return out
        else:
            # Legacy shard — assume structured_atomic tier weight.
            return [(int(v), float(s), None, 1.0)
                    for v, s in zip(ids, scores)]

    # ── public query ────────────────────────────────────────
    def query(
        self,
        text: str = "",
        subject: str = "",
        relation: str = "",
        obj: str = "",
        k: int = 10,
        n_shards: int = 0,
        fetch_k: Optional[int] = None,
    ) -> Dict:
        """Run a query. n_shards=0 means probe all shards."""
        fetch_k = fetch_k or max(k * 5, 20)

        # Build query tokens via the right tier dispatch.
        if subject or relation:
            atoms = [a.lower().strip() for a in (subject, relation, obj) if a]
            tokens = [a for a in atoms if a]
            axes_used: Set[str] = {"escape"}
        else:
            tokens, axes_used = self._atomic_tokens_from_text(text)

        qvec = self._encode_tokens(tokens)
        if qvec is None:
            return {
                "results": [],
                "trace": {"tokens": tokens, "axes_used": sorted(axes_used),
                          "note": "empty token vector"},
            }

        # Route.
        if n_shards <= 0 or n_shards >= len(self.shards):
            shard_ids = self._all_shard_ids()
        else:
            shard_ids = self._route(qvec, n_shards)

        # Search each shard in parallel.
        def _search(sid):
            shard = self.shards.get(sid)
            if shard is None:
                return (sid, [])
            return (sid, self._search_shard(shard, qvec, fetch_k, axes_used))

        shard_results: Dict[int, List[Tuple[int, float, Optional[Tier], float]]] = {}
        futs = [self._executor.submit(_search, sid) for sid in shard_ids]
        for f in futs:
            sid, hits = f.result()
            shard_results[sid] = hits

        # Merge + rank by ranking_score.
        merged: List[QueryHit13] = []
        for sid, hits in shard_results.items():
            shard = self.shards[sid]
            for vid, sc, tier, w in hits:
                ranking = sc * w
                merged.append(QueryHit13(
                    shard_id=sid,
                    vec_id=vid,
                    tier=tier,
                    raw_score=sc,
                    tier_weight=w,
                    ranking_score=ranking,
                    text=shard.get_text(vid),
                    value=shard.get_value(vid),
                ))

        merged.sort(key=lambda h: -h.ranking_score)
        top = merged[:k]
        return {
            "results": [h.to_dict() for h in top],
            "trace": {
                "tokens": tokens,
                "axes_used": sorted(axes_used),
                "shards_probed": len(shard_ids),
                "candidates": len(merged),
            },
        }

    def close(self):
        self._executor.shutdown(wait=False)
