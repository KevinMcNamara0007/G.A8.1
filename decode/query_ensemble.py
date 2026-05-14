"""Ensemble query backend — fan-out across N codebook-seeded flat
backends, fuse results.

Produced by ``encode.encode_unstructured --ensemble-seeds N,M,P,...``. The
on-disk layout is:

    <root>/
      ensemble.json                    -- manifest (seeds, default fusion)
      corpus.jsonl                     -- shared sidecar across all seeds
      corpus.jsonl.offsets             -- mmap index (built on first open)
      structural_v13_seed42/
        structural_v13.cfg
        lsh.bin
        hebbian.bin
      structural_v13_seed56/
        ...

EnsembleQueryService opens one ``decode.query.QueryService`` per seed,
fans queries out on a thread pool (each ``ehc`` query call releases the
GIL on the C++ side), and fuses the per-seed top-k lists by the
configured strategy.

Fusion strategies (env override: ``A81_ENSEMBLE_FUSION``):

  ``merge_top10`` (default)
      Union across seeds, dedupe by ``id`` keeping the max-similarity
      copy, sort desc. Simplest and best Hit@5 on EDGE.

  ``max_top1``
      Pick the seed whose top-1 has highest similarity, return that
      seed's full list. Best Hit@10 (more diverse) on EDGE.

  ``sum_sim``
      Sum similarities across seeds per ``id``. Rewards cross-rotation
      consensus. Equivalent to ``merge_top10`` on Hit@1 when most gold
      surfaces in only 1-2 seeds (the EDGE case).

Spread seeds (not consecutive integers) materially outperform clustered
ones on Hit@1 — consecutive ``mt19937_64`` states produce correlated
codebooks; spread states produce more independent rotations. EDGE 25-query
operator bench at K=6 reached 56% Hit@1 with seeds
``[42, 56, 64, 96, 104, 116]`` vs 40% at K=8 with consecutive seeds
``[42..49]``.
"""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


def _utc_now_iso() -> str:
    """Match decode.query's audit timestamp format (milliseconds, +00:00)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


logger = logging.getLogger(__name__)


def _merge_top10(per_seed: List[List[Dict[str, Any]]],
                 k: int) -> List[Dict[str, Any]]:
    """Union, dedupe by id, keep max-similarity copy, sort desc."""
    best: Dict[Any, Dict[str, Any]] = {}
    for results in per_seed:
        for h in results:
            did = h.get("id")
            sim = float(h.get("similarity", 0.0))
            cur = best.get(did)
            if cur is None or sim > float(cur.get("similarity", -1.0)):
                best[did] = h
    return sorted(best.values(),
                  key=lambda h: -float(h.get("similarity", 0.0)))[:k]


def _max_top1(per_seed: List[List[Dict[str, Any]]],
              k: int) -> List[Dict[str, Any]]:
    """Return the full list from whichever seed has the highest top-1."""
    best_seed = -1
    best_sim = -1.0
    for i, results in enumerate(per_seed):
        if results:
            sim = float(results[0].get("similarity", -1.0))
            if sim > best_sim:
                best_sim = sim
                best_seed = i
    if best_seed < 0:
        return []
    return list(per_seed[best_seed])[:k]


def _sum_sim(per_seed: List[List[Dict[str, Any]]],
             k: int) -> List[Dict[str, Any]]:
    """Sum similarities across seeds per id, rank by sum."""
    totals: Dict[Any, float] = {}
    seen: Dict[Any, Dict[str, Any]] = {}
    for results in per_seed:
        for h in results:
            did = h.get("id")
            sim = float(h.get("similarity", 0.0))
            totals[did] = totals.get(did, 0.0) + sim
            if did not in seen:
                seen[did] = h
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    out: List[Dict[str, Any]] = []
    for did, total in ranked[:k]:
        h = dict(seen[did])
        h["similarity"] = total
        out.append(h)
    return out


_FUSION: Dict[str, Callable[[List[List[Dict[str, Any]]], int],
                            List[Dict[str, Any]]]] = {
    "merge_top10": _merge_top10,
    "max_top1":    _max_top1,
    "sum_sim":     _sum_sim,
}


class EnsembleQueryService:
    """Codebook-seeded ensemble backend.

    Opens one flat ``decode.query.QueryService`` per seed. Queries fan
    out concurrently across all backends and per-seed result lists are
    fused via the configured strategy.

    Constructor kwargs:
        ``fusion`` — override the manifest default
                     (``merge_top10`` / ``max_top1`` / ``sum_sim``).
                     Resolution order: kwarg > ``A81_ENSEMBLE_FUSION`` env >
                     ``ensemble.json::fusion`` > ``merge_top10``.

    Public API mirrors ``decode.query.QueryService``: ``query``, ``stats``,
    ``close``. Additionally exposes ``backends`` (the per-seed handles)
    and ``fusion`` (the active strategy name).
    """

    def __init__(self, path: str, fusion: Optional[str] = None,
                 product_dir: Optional[str] = None,
                 context: Optional[Dict[str, Any]] = None,
                 hebbian_topk: int = 3,
                 **kwargs):
        root = Path(path).resolve()
        manifest_path = root / "ensemble.json"
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"ensemble.json not found at {manifest_path}")
        with open(manifest_path) as mf:
            self._manifest = json.load(mf)
        self._root = root
        self._seeds: List[int] = list(self._manifest["seeds"])
        if len(self._seeds) < 2:
            raise ValueError(
                f"ensemble.json has only {len(self._seeds)} seed(s); "
                f"need ≥2 for an ensemble.")

        env = os.environ.get("A81_ENSEMBLE_FUSION", "").strip()
        chosen = (fusion or env or self._manifest.get("fusion")
                  or "merge_top10")
        if chosen not in _FUSION:
            raise ValueError(
                f"unknown ensemble fusion strategy {chosen!r}; "
                f"pick one of {sorted(_FUSION)}")
        self._fusion_name = chosen

        from decode.query import QueryService as _FlatQS
        self._backends: List[Any] = []
        for seed in self._seeds:
            pdir = root / f"structural_v13_seed{seed}"
            if not (pdir / "structural_v13.cfg").exists():
                raise FileNotFoundError(
                    f"ensemble.json lists seed={seed} but "
                    f"{pdir}/structural_v13.cfg is missing.")
            self._backends.append(_FlatQS(
                a81_path=str(pdir),
                product_dir=product_dir,
                context=context,
                hebbian_topk=hebbian_topk,
            ))

        self._pool = ThreadPoolExecutor(
            max_workers=len(self._backends),
            thread_name_prefix="ensemble-q")
        logger.info(
            "EnsembleQueryService ready: %d seeds=%s fusion=%s",
            len(self._backends), self._seeds, self._fusion_name)

    @property
    def fusion(self) -> str:
        return self._fusion_name

    @property
    def backends(self) -> List[Any]:
        return list(self._backends)

    def query(self, text: str = "", k: int = 10,
              fusion: Optional[str] = None,
              **kwargs) -> Dict[str, Any]:
        """Fan out, fuse. Pass ``fusion=`` for a one-shot strategy
        override without changing the configured default."""
        t0 = time.perf_counter()
        def _one(b):
            return b.query(text=text, k=k, **kwargs)
        futures = [self._pool.submit(_one, b) for b in self._backends]
        per_seed_full = [f.result() for f in futures]
        per_seed = [r.get("results", []) for r in per_seed_full]

        fuse = _FUSION[fusion] if fusion else _FUSION[self._fusion_name]
        fused = fuse(per_seed, k)

        confidence = max(
            (float(r.get("confidence", 0.0)) for r in per_seed_full),
            default=0.0)
        duration_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "results": fused,
            "confidence": confidence,
            "audit": {
                "timestamp": _utc_now_iso(),
                "duration_ms": duration_ms,
                "strategy": f"ensemble.{fusion or self._fusion_name}",
                "n_retrieved": sum(len(p) for p in per_seed),
                "n_returned": len(fused),
                "n_backends": len(self._backends),
                "seeds": list(self._seeds),
                "per_seed_n_returned": [
                    r.get("audit", {}).get("n_returned", 0)
                    for r in per_seed_full],
            },
        }

    @property
    def stats(self) -> Dict[str, Any]:
        s0 = (self._backends[0].stats
              if self._backends and hasattr(self._backends[0], "stats")
              else {})
        base = dict(s0) if isinstance(s0, dict) else {}
        base.update({
            "backend":  "ensemble",
            "seeds":    list(self._seeds),
            "n_seeds":  len(self._seeds),
            "fusion":   self._fusion_name,
            "pipe_dir": str(self._root),
        })
        return base

    def close(self):
        for b in self._backends:
            if hasattr(b, "close"):
                try:
                    b.close()
                except Exception:
                    pass
        self._pool.shutdown(wait=False)

    def __getattr__(self, name: str) -> Any:
        """Forward unknown attributes to backend[0].

        Methods that aren't ensembleable — vector-arithmetic
        (``analogy``, ``what_if``, ``missing_link``), metadata lookups
        (``get_metadata``), media-only paths (``query_images``,
        ``query_multimodal``) — route to seed 0 with single-backend
        semantics. Only ``query`` fans out + fuses.

        Vector-arithmetic on a single seed is the right call:
        analogy/what_if rely on token-codebook geometry that's tied to
        a specific seed; ensembling them would mean ensembling vector
        compositions across different codebook rotations, which is a
        category error.
        """
        if name == "_backends":
            raise AttributeError(name)
        backends = self.__dict__.get("_backends")
        if not backends:
            raise AttributeError(name)
        return getattr(backends[0], name)
