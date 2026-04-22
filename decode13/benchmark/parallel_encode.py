"""Parallel encoders for the Wikidata benchmark.

multiprocessing.Pool ('fork') with N workers. Each worker encodes its
chunk of triples into flat numpy arrays (indices[N,k] + signs[N,k]) +
metadata arrays (tier_id, confidence, gate, source_rid, manifest_key).
Main process concatenates and builds one BSCCompactIndex +
BSCLSHIndex via add_items (a single C++ bulk insert).

Why this shape:
  - Workers share the source triples list via fork COW (no pickle of
    21M dicts)
  - Workers return only numpy arrays (cheap to ship — ~320B/vec)
  - Main process owns the sole live C++ index
  - No per-vec Python dataclasses anywhere

Workers create their own TokenCodebook from the seed so hash outputs
are identical to the single-process path — deterministic.
"""

from __future__ import annotations

import math
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

for _d in (2, 3, 4):
    _p = Path(__file__).resolve().parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc  # noqa: E402

from decode13 import Tier, TierManifest, ManifestRegistry13  # noqa: E402
from decode13.tier_manifest import tier_to_int  # noqa: E402
from decode13.tier_encode import TierEncoder  # noqa: E402
from decode13.benchmark.baseline_encoder import (  # noqa: E402
    _shatter_tokenize, CanonicalBaselineEncoder,
)


# Shared state for fork workers — set by _worker_init.
_SHARED_TRIPLES: Optional[List[dict]] = None
_SHARED_DIM: int = 0
_SHARED_K: int = 0
_SHARED_SEED: int = 0


def _worker_init(triples, dim, k, seed):
    """Fork-time: stash shared references so worker chunks can index into
    them without pickling. Under fork COW this is ~free."""
    global _SHARED_TRIPLES, _SHARED_DIM, _SHARED_K, _SHARED_SEED
    _SHARED_TRIPLES = triples
    _SHARED_DIM = dim
    _SHARED_K = k
    _SHARED_SEED = seed


# ═══════════════════════════════════════════════════════════════
#  Worker: Tier 1 (atomic)
# ═══════════════════════════════════════════════════════════════

def _worker_tier1(chunk_range: Tuple[int, int]) -> Dict:
    """Encode triples[start:end] via Tier 1 (structured_atomic, atomic
    bind, no shattering). Return arrays suitable for concatenation."""
    start, end = chunk_range
    dim = _SHARED_DIM
    k = _SHARED_K
    seed = _SHARED_SEED
    triples = _SHARED_TRIPLES

    # Build local codebook (deterministic with seed)
    cfg = ehc.CodebookConfig()
    cfg.dim = dim
    cfg.k = k
    cfg.seed = seed
    cb = ehc.TokenCodebook(cfg)
    cb.build_from_vocabulary([])
    cache = ehc.LRUCache(max_size=50000) if hasattr(ehc, "LRUCache") else None

    def enc_tok(w):
        if cache is not None:
            c = cache.get(w)
            if c is not None:
                return c
        try:
            tv = cb.encode_token(w)
        except Exception:
            return None
        if cache is not None and tv is not None:
            cache.put(w, tv)
        return tv

    # Preallocate output buffers — worst case 1 vec per record.
    n = end - start
    ind_buf = np.zeros((n, k), dtype=np.int32)
    sgn_buf = np.zeros((n, k), dtype=np.int8)
    tier_id = np.zeros(n, dtype=np.int8)
    conf = np.zeros(n, dtype=np.float32)
    gate = np.zeros(n, dtype=np.bool_)
    src_rid = np.full(n, -1, dtype=np.int32)
    nzlen = np.zeros(n, dtype=np.int16)  # actual non-zero slots per row
    out = 0

    # For Tier 1, every record produces one vector with a fixed manifest
    # shape (structured_atomic, confidence=1.0, gate=True). We capture
    # this key once; main merges worker manifest tables.
    manifest_key_t1 = ("structured_atomic", "structured_atomic", "none", 1.0, True)

    atomized_cache: Dict[str, object] = {}  # token string → SparseVector

    def atomize(field):
        """Single atom — lowercase, strip whitespace; NEVER split _."""
        if not field:
            return ""
        s = field.replace("\n", " ").strip().lower()
        s = " ".join(s.split())
        return s

    for i in range(start, end):
        rec = triples[i]
        s = atomize(rec.get("subject", ""))
        r = atomize(rec.get("relation", ""))
        o = atomize(rec.get("object", "") or rec.get("text", ""))
        if not (s or r or o):
            continue
        vecs = []
        for tok in (s, r, o):
            if not tok:
                continue
            v = enc_tok(tok)
            if v is not None:
                vecs.append(v)
        if not vecs:
            continue
        sv = ehc.superpose(vecs) if len(vecs) > 1 else vecs[0]

        inds = np.asarray(sv.indices[:k], dtype=np.int32)
        sgns = np.asarray(sv.signs[:k], dtype=np.int8)
        nz = len(inds)
        ind_buf[out, :nz] = inds
        sgn_buf[out, :nz] = sgns
        nzlen[out] = nz
        tier_id[out] = tier_to_int(Tier.STRUCTURED_ATOMIC)
        conf[out] = 1.0
        gate[out] = True
        src_rid[out] = i  # record id = index in shared triples list
        out += 1

    return {
        "n": out,
        "indices": ind_buf[:out],
        "signs": sgn_buf[:out],
        "nzlen": nzlen[:out],
        "tier_id": tier_id[:out],
        "confidence": conf[:out],
        "gate": gate[:out],
        "source_rid": src_rid[:out],
        "manifest_key": manifest_key_t1,
    }


# ═══════════════════════════════════════════════════════════════
#  Worker: Baseline (shattered)
# ═══════════════════════════════════════════════════════════════

def _worker_baseline(chunk_range: Tuple[int, int]) -> Dict:
    start, end = chunk_range
    dim = _SHARED_DIM
    k = _SHARED_K
    seed = _SHARED_SEED
    triples = _SHARED_TRIPLES

    cfg = ehc.CodebookConfig()
    cfg.dim = dim
    cfg.k = k
    cfg.seed = seed
    cb = ehc.TokenCodebook(cfg)
    cb.build_from_vocabulary([])
    cache = ehc.LRUCache(max_size=50000) if hasattr(ehc, "LRUCache") else None

    def enc_tok(w):
        if cache is not None:
            c = cache.get(w)
            if c is not None:
                return c
        try:
            tv = cb.encode_token(w)
        except Exception:
            return None
        if cache is not None and tv is not None:
            cache.put(w, tv)
        return tv

    n = end - start
    ind_buf = np.zeros((n, k), dtype=np.int32)
    sgn_buf = np.zeros((n, k), dtype=np.int8)
    src_rid = np.full(n, -1, dtype=np.int32)
    nzlen = np.zeros(n, dtype=np.int16)
    out = 0

    for i in range(start, end):
        rec = triples[i]
        s = rec.get("subject", "")
        r = rec.get("relation", "")
        o = rec.get("object", "") or rec.get("text", "")
        tokens = _shatter_tokenize(s, r, o)
        if not tokens:
            continue
        vecs = []
        for tok in tokens:
            v = enc_tok(tok)
            if v is not None:
                vecs.append(v)
        if not vecs:
            continue
        sv = ehc.superpose(vecs) if len(vecs) > 1 else vecs[0]
        inds = np.asarray(sv.indices[:k], dtype=np.int32)
        sgns = np.asarray(sv.signs[:k], dtype=np.int8)
        nz = len(inds)
        ind_buf[out, :nz] = inds
        sgn_buf[out, :nz] = sgns
        nzlen[out] = nz
        src_rid[out] = i
        out += 1

    return {
        "n": out,
        "indices": ind_buf[:out],
        "signs": sgn_buf[:out],
        "nzlen": nzlen[:out],
        "source_rid": src_rid[:out],
    }


# ═══════════════════════════════════════════════════════════════
#  Driver
# ═══════════════════════════════════════════════════════════════

def _chunk_ranges(n: int, n_workers: int) -> List[Tuple[int, int]]:
    chunk = max(1, math.ceil(n / n_workers))
    ranges: List[Tuple[int, int]] = []
    for w in range(n_workers):
        start = w * chunk
        end = min(start + chunk, n)
        if start >= n:
            break
        ranges.append((start, end))
    return ranges


def parallel_encode_tier1(
    triples: List[dict],
    dim: int,
    k: int,
    seed: int,
    n_workers: int = 8,
    tenant_domain: str = "default::default",
    retain_vectors: bool = False,
) -> TierEncoder:
    """Encode via Tier 1 atomic in parallel. Returns a TierEncoder whose
    flat arrays + C++ indices are populated, ready for queries."""
    n = len(triples)
    ranges = _chunk_ranges(n, n_workers)

    t0 = time.perf_counter()
    ctx = mp.get_context("fork")
    with ctx.Pool(
        processes=len(ranges),
        initializer=_worker_init,
        initargs=(triples, dim, k, seed),
    ) as pool:
        results = pool.map(_worker_tier1, ranges)
    t_bind = time.perf_counter() - t0
    print(f"  [tier1] parallel bind: {t_bind:.1f}s across {len(ranges)} workers")

    # Concatenate arrays from all workers.
    indices = np.vstack([r["indices"] for r in results])
    signs = np.vstack([r["signs"] for r in results])
    nzlen = np.concatenate([r["nzlen"] for r in results])
    tier_id = np.concatenate([r["tier_id"] for r in results])
    confidence = np.concatenate([r["confidence"] for r in results])
    gate = np.concatenate([r["gate"] for r in results])
    source_rid = np.concatenate([r["source_rid"] for r in results])
    n_total = int(indices.shape[0])
    print(f"  [tier1] collected {n_total:,} vectors in "
          f"{time.perf_counter()-t0:.1f}s")

    # Build one BSCCompactIndex + BSCLSHIndex via add_items.
    # We construct SparseVector objects only as a short-lived list, then
    # drop the Python refs so the C++ index is the sole owner.
    t_build = time.perf_counter()
    cb_cfg = ehc.CodebookConfig(); cb_cfg.dim = dim; cb_cfg.k = k; cb_cfg.seed = seed
    # (codebook not needed for index build; just dim and k)
    idx = ehc.BSCCompactIndex(dim, use_sign_scoring=True)
    # Auto-scale LSH hash_size with corpus size. Avg bucket stays ~10
    # vectors as records grow from 100K to 100B. See
    # config.resolve_lsh_hash_size for the table.
    from config import resolve_lsh_hash_size
    auto_hs = resolve_lsh_hash_size(n_total)
    print(f"  [tier1] LSH hash_size auto-tuned → {auto_hs} "
          f"(for n={n_total:,}; avg bucket ≈ "
          f"{max(1, int(n_total / (2 ** auto_hs)))})", flush=True)
    lsh = ehc.BSCLSHIndex(dim, k, num_tables=8,
                          hash_size=auto_hs, use_multiprobe=True)

    # add_items in batches so we don't build a giant Python list.
    BATCH = 100_000
    ids = np.arange(n_total, dtype=np.int32)
    retained_vecs: List = [] if retain_vectors else None
    retained_ids: List[int] = [] if retain_vectors else None
    for bs in range(0, n_total, BATCH):
        be = min(bs + BATCH, n_total)
        bvs = []
        for row in range(bs, be):
            nz = int(nzlen[row])
            if nz == 0:
                continue
            bvs.append(ehc.SparseVector(
                dim,
                np.ascontiguousarray(indices[row, :nz]),
                np.ascontiguousarray(signs[row, :nz]),
            ))
        bids = ids[bs:be].tolist()
        # Align bids to only the ones we actually built (skipping nz==0)
        # For Tier 1 all rows have nz > 0 so this is safe, but guard just in case:
        if len(bvs) != be - bs:
            # fall back: build a filtered id list
            bids = [ids[row] for row in range(bs, be) if int(nzlen[row]) > 0]
        idx.add_items(bvs, bids)
        lsh.add_items(bvs, bids)
        if retain_vectors:
            retained_vecs.extend(bvs)
            retained_ids.extend(bids)
    print(f"  [tier1] index build: {time.perf_counter()-t_build:.1f}s")

    # Construct a thin TierEncoder wrapper that owns the flat arrays +
    # the C++ indices. We bypass its bind path entirely.
    enc = TierEncoder.__new__(TierEncoder)
    enc.dim = int(dim)
    enc.k = int(k)
    enc.seed = int(seed)
    enc.tenant_domain = tenant_domain
    enc.retain_triples = False
    enc._triples = None
    enc._tokens = None
    # Codebook needed for query encoding (query-time bind).
    enc.codebook = ehc.TokenCodebook(cb_cfg)
    enc.codebook.build_from_vocabulary([])
    enc.cache = ehc.LRUCache(max_size=50000) if hasattr(ehc, "LRUCache") else None

    # Canonical pipeline (used only by decode-side tier_query; encoder
    # keeps a reference so QueryService13 can reuse it).
    from canonical.pipeline import CanonicalizationPipeline
    enc.canonical = CanonicalizationPipeline()

    # Tier pipelines (for decode-side); not used during encode here.
    from decode13 import (
        TierRouter, StructuredAtomicPipeline, ExtractionPipeline,
        EmergentStructureFallback,
    )
    enc.router = TierRouter()
    enc.tier1 = StructuredAtomicPipeline()
    enc.tier2 = ExtractionPipeline(canonical=enc.canonical)
    enc.tier3 = EmergentStructureFallback(canonical=enc.canonical)

    # Flat arrays — this is what makes queries cheap.
    enc._tier_id = tier_id
    enc._confidence = confidence
    enc._gate = gate
    enc._source_rid = source_rid
    enc.n_vectors = n_total
    enc._capacity = n_total
    enc._pending_vecs = []
    enc._pending_ids = []
    enc._manifest_intern = {}

    # Registry — one interned manifest (all Tier 1 atomic).
    decode_m = TierManifest.from_symmetry(
        enc.canonical.manifest,
        tier=Tier.STRUCTURED_ATOMIC,
        tenant_domain=tenant_domain,
    )
    reg = ManifestRegistry13(decode_m)
    # Since all vectors share the same manifest, intern once and stamp
    # the whole array.
    single = TierManifest.from_symmetry(
        enc.canonical.manifest,
        tier=Tier.STRUCTURED_ATOMIC,
        extractor="structured_atomic",
        ner_model="none",
        extraction_confidence=1.0,
        gate_agreement=True,
        tenant_domain=tenant_domain,
    )
    mid = reg._intern(single)
    reg._manifest_id = np.full(n_total, mid, dtype=np.int16)
    reg._n = n_total
    reg._capacity = n_total
    enc.registry = reg

    enc._index = idx
    enc._lsh = lsh
    if retain_vectors:
        # Sweep hook: caller can rebuild LSH with different (hash_size,
        # num_tables) from these without re-encoding. Large memory cost
        # (~4 GB at 5M, ~17 GB at 21M); default off.
        enc._retained_vecs = retained_vecs
        enc._retained_ids = retained_ids
    return enc


def parallel_encode_baseline(
    triples: List[dict],
    dim: int,
    k: int,
    seed: int,
    n_workers: int = 8,
) -> CanonicalBaselineEncoder:
    """Baseline (shattered) encoder in parallel. Returns a
    CanonicalBaselineEncoder populated with flat arrays + C++ indices."""
    n = len(triples)
    ranges = _chunk_ranges(n, n_workers)

    t0 = time.perf_counter()
    ctx = mp.get_context("fork")
    with ctx.Pool(
        processes=len(ranges),
        initializer=_worker_init,
        initargs=(triples, dim, k, seed),
    ) as pool:
        results = pool.map(_worker_baseline, ranges)
    t_bind = time.perf_counter() - t0
    print(f"  [baseline] parallel bind: {t_bind:.1f}s across {len(ranges)} workers")

    indices = np.vstack([r["indices"] for r in results])
    signs = np.vstack([r["signs"] for r in results])
    nzlen = np.concatenate([r["nzlen"] for r in results])
    source_rid = np.concatenate([r["source_rid"] for r in results])
    n_total = int(indices.shape[0])
    print(f"  [baseline] collected {n_total:,} vectors in "
          f"{time.perf_counter()-t0:.1f}s")

    t_build = time.perf_counter()
    idx = ehc.BSCCompactIndex(dim, use_sign_scoring=True)
    # Auto-scale LSH hash_size with corpus size (same rule as tier1).
    from config import resolve_lsh_hash_size
    auto_hs = resolve_lsh_hash_size(n_total)
    print(f"  [baseline] LSH hash_size auto-tuned → {auto_hs} "
          f"(for n={n_total:,}; avg bucket ≈ "
          f"{max(1, int(n_total / (2 ** auto_hs)))})", flush=True)
    lsh = ehc.BSCLSHIndex(dim, k, num_tables=8,
                          hash_size=auto_hs, use_multiprobe=True)

    BATCH = 100_000
    ids = np.arange(n_total, dtype=np.int32)
    for bs in range(0, n_total, BATCH):
        be = min(bs + BATCH, n_total)
        bvs = []
        bids = []
        for row in range(bs, be):
            nz = int(nzlen[row])
            if nz == 0:
                continue
            bvs.append(ehc.SparseVector(
                dim,
                np.ascontiguousarray(indices[row, :nz]),
                np.ascontiguousarray(signs[row, :nz]),
            ))
            bids.append(int(ids[row]))
        idx.add_items(bvs, bids)
        lsh.add_items(bvs, bids)
    print(f"  [baseline] index build: {time.perf_counter()-t_build:.1f}s")

    # Construct a CanonicalBaselineEncoder without running its __init__
    # bind-loop path.
    enc = CanonicalBaselineEncoder.__new__(CanonicalBaselineEncoder)
    enc.dim = int(dim)
    enc.k = int(k)
    enc.seed = int(seed)
    enc.retain_tokens = False
    enc._tokens_ref = None

    cb_cfg = ehc.CodebookConfig(); cb_cfg.dim = dim; cb_cfg.k = k; cb_cfg.seed = seed
    enc.codebook = ehc.TokenCodebook(cb_cfg)
    enc.codebook.build_from_vocabulary([])
    enc.cache = ehc.LRUCache(max_size=50000) if hasattr(ehc, "LRUCache") else None

    enc._source_rid = source_rid
    enc.n_vectors = n_total
    enc._capacity = n_total
    enc._pending_vecs = []
    enc._pending_ids = []
    enc._index = idx
    enc._lsh = lsh
    return enc
