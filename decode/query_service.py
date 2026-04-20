"""QueryService — edge-compat adapter over `ehc.StructuralPipelineV13`.

This module preserves the legacy import path used by frontend services:
    from query_service import QueryService
    svc = QueryService(a81_path, product_dir=..., context={...})
    svc.stats          # {total_vectors, ...}
    svc.query(text, k=..., ...)               # {results, confidence, audit}
    svc.query_images(text, k=...)             # image-tagged subset
    svc.query_multimodal(text, k=..., ...)    # text+image fused (degraded)

Under the hood it loads a persisted `StructuralPipelineV13` plus a
`corpus.jsonl` sidecar produced by
`decode13/eval/run_edge_benchmark.py --out <dir>`. The sidecar maps
`doc_id → {text, raw, url, author, site, timestamp}` so the adapter can
return the metadata shape the frontend expects.

Shard layout expected at `a81_path`:
    a81_path/
      corpus.jsonl           # doc_id-aligned metadata (required)
      structural_v13/
        structural_v13.cfg
        hebbian.bin          # optional (present iff Hebbian was enabled)
        lsh.bin

The `product_dir` and `context` kwargs are accepted but currently
unused — they are part of the legacy surface and left in place so
callers can pass whatever they already pass.

Limitations:
- `query_images` returns the subset of `query` results that have a
  resolved `media_url`. No separate image-modality encoder is loaded
  here (the structural pipeline does not consume image pixels).
- `query_multimodal` is the same path as `query` — image_weight is
  accepted and ignored. Upgrade to a true fused multimodal query would
  require binding the C++ VisionEncoder alongside the structural
  pipeline. Tracked separately.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# EHC native module probe — tolerant of _ROOT being shallow.
_cand = [_ROOT / "EHC" / "build" / "bindings" / "python"]
for _i in range(len(_ROOT.parents)):
    _cand.append(_ROOT.parents[_i] / "EHC" / "build" / "bindings" / "python")
for _p in _cand:
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc  # noqa: E402


logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _resolve_paths(a81_path: str) -> Dict[str, Path]:
    """Accept either the shard root or the structural_v13 subdir.

    run_edge_benchmark.py writes:
      <root>/corpus.jsonl
      <root>/structural_v13/structural_v13.cfg
      <root>/structural_v13/hebbian.bin
      <root>/structural_v13/lsh.bin
    """
    p = Path(a81_path).resolve()
    if (p / "structural_v13.cfg").exists():
        root = p.parent
        pipe_dir = p
    else:
        root = p
        pipe_dir = p / "structural_v13"
        if not (pipe_dir / "structural_v13.cfg").exists():
            raise FileNotFoundError(
                f"no structural_v13.cfg under {p} or {pipe_dir}")
    corpus = root / "corpus.jsonl"
    if not corpus.exists():
        raise FileNotFoundError(
            f"corpus.jsonl missing at {corpus}. Re-run "
            f"decode13/eval/run_edge_benchmark.py --out {root}")
    return {"root": root, "pipe_dir": pipe_dir, "corpus": corpus}


class QueryService:
    """Adapter: legacy QueryService API → StructuralPipelineV13.

    Thread safety: `ehc.StructuralPipelineV13.query_text(_expanded)` releases
    the GIL and is safe to call concurrently for read-only queries. The
    sidecar dict is read-only after load.
    """

    def __init__(
        self,
        a81_path: str,
        product_dir: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        *,
        hebbian_topk: int = 3,
    ):
        paths = _resolve_paths(a81_path)
        self._root = paths["root"]
        self._pipe_dir = paths["pipe_dir"]
        self.product_dir = product_dir
        self.context = context or {}
        self._hebbian_topk = int(hebbian_topk)

        t0 = time.perf_counter()
        self._pipe = ehc.StructuralPipelineV13.load(str(self._pipe_dir))
        t_pipe = time.perf_counter() - t0

        t0 = time.perf_counter()
        self._docs: Dict[int, dict] = {}
        with open(paths["corpus"], "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                did = int(rec.get("doc_id", -1))
                if did < 0:
                    continue
                self._docs[did] = rec
        t_corpus = time.perf_counter() - t0

        self._has_hebbian = bool(self._pipe.config().enable_hebbian)
        logger.info(
            "QueryService ready: %d vectors, %d corpus rows "
            "(pipeline=%.2fs, corpus=%.2fs, hebbian=%s)",
            self._pipe.size(), len(self._docs), t_pipe, t_corpus,
            self._has_hebbian,
        )

    # ── Introspection ─────────────────────────────────────────
    @property
    def stats(self) -> Dict[str, Any]:
        cfg = self._pipe.config()
        return {
            "total_vectors":  int(self._pipe.size()),
            "corpus_rows":    len(self._docs),
            "dim":            int(cfg.dim),
            "k":              int(cfg.k),
            "hebbian":        self._has_hebbian,
            "backend":        "structural_v13",
            "pipe_dir":       str(self._pipe_dir),
        }

    # ── Core query ────────────────────────────────────────────
    def query(
        self,
        text: str,
        k: int = 10,
        has_media: Optional[bool] = None,
        tags_any: Optional[Iterable[str]] = None,
        prefer_recent: Optional[bool] = None,
        recency_half_life_hours: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Main text retrieval. Returns the legacy `{results, confidence, audit}` shape."""
        return self._run_query(
            text, k,
            has_media=has_media,
            tags_any=tags_any,
            prefer_recent=prefer_recent,
            recency_half_life_hours=recency_half_life_hours,
            strategy="a81_structural_v13",
        )

    # ── Image-only query ──────────────────────────────────────
    def query_images(self, text: str, k: int = 10) -> Dict[str, Any]:
        """Text-scored retrieval filtered to records with resolved media.

        The structural pipeline does not ingest pixels, so we score by
        text and then filter to hits that have a media_url. Fallback
        behavior — a proper fused image search would bind the C++
        VisionEncoder separately.
        """
        return self._run_query(
            text, k,
            has_media=True,
            strategy="a81_structural_v13_images",
        )

    # ── Multimodal query ──────────────────────────────────────
    def query_multimodal(
        self,
        text: str,
        k: int = 10,
        image_weight: float = 0.5,
    ) -> Dict[str, Any]:
        """Degraded multimodal: ignores image_weight, returns text-scored results."""
        _ = image_weight  # accepted for API parity; not used here
        return self._run_query(
            text, k,
            strategy="a81_structural_v13_multimodal",
        )

    # ── Internals ─────────────────────────────────────────────
    def _run_query(
        self,
        text: str,
        k: int,
        *,
        has_media: Optional[bool] = None,
        tags_any: Optional[Iterable[str]] = None,
        prefer_recent: Optional[bool] = None,
        recency_half_life_hours: Optional[float] = None,
        strategy: str,
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()
        # Over-fetch so post-filters (has_media, tags) still leave k results.
        fetch = max(k * 5, k + 20)
        if self._has_hebbian:
            raw = self._pipe.query_text_expanded(text, fetch, self._hebbian_topk)
        else:
            raw = self._pipe.query_text(text, fetch)

        ids = list(raw.ids)
        scores = list(raw.scores)

        # Filter + decorate.
        results: List[dict] = []
        tag_set = {str(t).lower() for t in (tags_any or [])}
        for doc_id, sim in zip(ids, scores):
            meta = self._lookup(int(doc_id))
            if has_media is True and not meta.get("media_url"):
                continue
            if has_media is False and meta.get("media_url"):
                continue
            if tag_set:
                text_blob = (meta.get("text", "") + " " +
                             meta.get("raw", "")).lower()
                if not any(t in text_blob for t in tag_set):
                    continue
            results.append({
                "id": str(doc_id),
                "similarity": float(sim),
                "metadata": meta,
            })
            if len(results) >= k:
                break

        # Cheap recency re-rank when requested (monotonic on posted_at).
        if prefer_recent and results:
            def _ts(r):
                t = r["metadata"].get("timestamp", "")
                try:
                    return datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
                except Exception:
                    return 0.0
            half = max(float(recency_half_life_hours or 168.0), 1e-3) * 3600.0
            now = time.time()
            for r in results:
                age = max(now - _ts(r), 0.0)
                r["similarity"] = float(r["similarity"]) * (0.5 ** (age / half))
            results.sort(key=lambda r: r["similarity"], reverse=True)

        confidence = float(results[0]["similarity"]) if results else 0.0
        return {
            "results":    results,
            "confidence": confidence,
            "audit": {
                "timestamp":    _utc_now_iso(),
                "duration_ms":  int((time.perf_counter() - t0) * 1000),
                "strategy":     strategy,
                "n_retrieved":  len(ids),
                "n_returned":   len(results),
            },
        }

    def _lookup(self, doc_id: int) -> Dict[str, Any]:
        rec = self._docs.get(doc_id) or {}
        # Prefer explicit media_url; fall back to url only if it has a
        # media extension (avoids treating post URLs as media).
        media_url = rec.get("media_url", "")
        if not media_url:
            u = rec.get("url", "")
            if _looks_like_media(u):
                media_url = u
        return {
            "text":      rec.get("text", ""),
            "raw":       rec.get("raw", ""),
            "author":    rec.get("author", ""),
            "site":      rec.get("site", ""),
            "timestamp": rec.get("timestamp", ""),
            "media_url": media_url,
            "url":       rec.get("url", ""),
            # Native ids so the UI can resolve back to the source record
            # via the edge service's existing msg_id / native_id lookups.
            "msg_id":    rec.get("msg_id", ""),
            "native_id": rec.get("native_id", ""),
        }


_MEDIA_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".webm", ".mkv"}


def _looks_like_media(u: str) -> bool:
    if not u:
        return False
    ext = os.path.splitext(u.lower())[1]
    return ext in _MEDIA_EXT
