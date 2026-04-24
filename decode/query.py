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

        # Second LSH handle pointing at the same lsh.bin — needed for
        # raw-vector queries (analogy / what-if / abductive / connections
        # paths that go through vector arithmetic, not text). Doubles LSH
        # memory; acceptable for the corpus scales v13.1 targets. Deferred
        # optimization: expose the pipeline's internal LSH via EHC so
        # we don't need the second handle.
        self._lsh: Optional[Any] = None
        lsh_path = self._pipe_dir / "lsh.bin"
        if lsh_path.exists():
            try:
                self._lsh = ehc.BSCLSHIndex.load(str(lsh_path))
            except Exception as e:
                logger.warning(
                    "QueryService: raw-vector LSH handle unavailable "
                    "(%s). Vector-arithmetic endpoints will be disabled.", e)

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
        # `now` is snapped to the nearest minute so repeated queries in the
        # same 60-second window produce byte-identical orderings. Without
        # this, two calls ~seconds apart can reshuffle near-tied records
        # because the decay ratio drifts by ~1e-4 per second — enough to
        # cross scores when the top-k cluster tightly (which is the norm
        # for narrative retrieval on social-media corpora).
        if prefer_recent and results:
            def _ts(r):
                t = r["metadata"].get("timestamp", "")
                try:
                    return datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
                except Exception:
                    return 0.0
            half = max(float(recency_half_life_hours or 168.0), 1e-3) * 3600.0
            now = (int(time.time()) // 60) * 60  # minute-boundary snap
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

    # ── Vector-level primitives (Phase 1 of reasoning port) ──
    #
    # These expose the raw-vector surface the legacy edge reasoning paths
    # (analogy / what-if / abductive / connections) used to get from
    # `app_state.bsc_index` + `app_state.get_vector_by_id`. Purely read-only;
    # safe to call concurrently with text queries.

    def get_vector_by_id(self, doc_id: int):
        """Return the encoded ehc.SparseVector for a stored doc_id, or
        None if the id isn't in the index or the LSH handle is unavailable.

        Wraps BSCLSHIndex.get_vector_by_id; the vector is a copy (safe to
        pass into vector-ops without worrying about index mutation)."""
        if self._lsh is None:
            return None
        try:
            return self._lsh.get_vector_by_id(int(doc_id))
        except Exception:
            return None

    def knn_vec(self, vec, k: int = 10) -> List[Dict[str, Any]]:
        """Raw-vector k-NN. Input is an ehc.SparseVector; output is a list
        of {id, similarity, metadata} dicts in descending similarity order.

        Metadata shape matches the text `query()` path so downstream code
        can treat both paths uniformly."""
        if self._lsh is None:
            return []
        r = self._lsh.knn_query(vec, k=int(k))
        ids = list(r.ids)
        scores = list(r.scores)
        out: List[Dict[str, Any]] = []
        for doc_id, sim in zip(ids, scores):
            out.append({
                "id": str(doc_id),
                "doc_id": int(doc_id),
                "similarity": float(sim),
                "metadata": self._lookup(int(doc_id)),
            })
        return out

    def similarity(self, v1, v2) -> float:
        """Cosine similarity between two ehc.SparseVector instances.

        Returns 0.0 if either vector is None or the vector-ops surface is
        somehow unavailable. Uses ehc.sparse_cosine — the same scoring
        primitive the C++ LSH uses internally."""
        if v1 is None or v2 is None:
            return 0.0
        try:
            return float(ehc.sparse_cosine(v1, v2))
        except Exception:
            return 0.0

    def get_metadata(self, doc_id: int) -> Dict[str, Any]:
        """Public wrapper around the sidecar lookup (mirrors the legacy
        `app_state.get_metadata(vec_id)` surface)."""
        return self._lookup(int(doc_id))

    # ── Phase 2 reasoning endpoints ────────────────────────────
    # Analogy and what-if are pure vector arithmetic on top of the Phase-1
    # primitives. They don't need a role registry or multi-hop traversal.

    def analogy(self, a_id: int, b_id: int, c_id: int,
                top_k: int = 5) -> Dict[str, Any]:
        """Solve A:B :: C:? via BSC vector arithmetic.

        Computes D = superpose([C, B, negate(A)]) with top-k
        sparsification tied to the pipeline's k (so D has the same
        sparsity as any other encoded vector in the index). Returns the
        nearest neighbors to D, excluding the three input doc_ids."""
        a = self.get_vector_by_id(a_id)
        b = self.get_vector_by_id(b_id)
        c = self.get_vector_by_id(c_id)
        if a is None or b is None or c is None:
            return {"results": [], "confidence": 0.0,
                    "audit": {"strategy": "a81_analogy",
                              "reason": "missing_input_vector"}}
        # D = C + B − A
        pipe_k = int(self._pipe.config().k)
        d = ehc.superpose([c, b, ehc.negate(a)], pipe_k)
        fetch = max(int(top_k) + 3, 10)
        cand = self.knn_vec(d, k=fetch)
        # Drop the three input ids so the analogy target isn't its own input.
        exclude = {int(a_id), int(b_id), int(c_id)}
        results = [h for h in cand if h["doc_id"] not in exclude][:int(top_k)]
        confidence = results[0]["similarity"] if results else 0.0
        return {
            "results": results,
            "confidence": float(confidence),
            "audit": {"strategy": "a81_analogy",
                      "a_id": a_id, "b_id": b_id, "c_id": c_id,
                      "candidates_considered": len(cand)},
        }

    def what_if(self, superposition_id: int, component_id: int,
                goal_id: int) -> Dict[str, Any]:
        """Counterfactual contribution: how much does `component` help
        `superposition` align with `goal`?

        delta = sim(superposition, goal) − sim(superposition − component, goal)

        A positive delta means removing `component` HURTS goal alignment —
        i.e. the component is a genuine contributor. Negative means it
        opposes the goal. Near-zero means irrelevant."""
        sup = self.get_vector_by_id(superposition_id)
        comp = self.get_vector_by_id(component_id)
        goal = self.get_vector_by_id(goal_id)
        if sup is None or comp is None or goal is None:
            return {"results": [], "confidence": 0.0,
                    "audit": {"strategy": "a81_what_if",
                              "reason": "missing_input_vector"}}
        pipe_k = int(self._pipe.config().k)
        sup_minus_comp = ehc.superpose([sup, ehc.negate(comp)], pipe_k)
        sim_with = self.similarity(sup, goal)
        sim_without = self.similarity(sup_minus_comp, goal)
        delta = float(sim_with - sim_without)
        impact = ("high" if abs(delta) > 0.10
                  else "medium" if abs(delta) > 0.05
                  else "low")
        direction = "positive" if delta > 0 else "negative" if delta < 0 else "neutral"
        return {
            "results": [{
                "component_id": str(component_id),
                "delta_contribution": round(delta, 4),
                "percentage": round(delta * 100, 2),
                "impact": impact,
                "direction": direction,
                "sim_with_component": round(sim_with, 4),
                "sim_without_component": round(sim_without, 4),
            }],
            "confidence": abs(round(delta, 4)),
            "narrative": (
                f"Component {component_id} has {impact} {direction} "
                f"contribution (Δ={delta:.2%}) to goal alignment."),
            "audit": {"strategy": "a81_what_if",
                      "superposition_id": superposition_id,
                      "component_id": component_id,
                      "goal_id": goal_id},
        }

    # ── Phase 3 reasoning endpoint: abductive missing-link ────
    # Given evidence E and target T, find hypothesis H such that T is
    # explained by combining H with E. In BSC additive terms:
    #   H ≈ T − E  →  the "residual" signal needed beyond what E already
    #                 explains to reach T.
    # Candidates are scored against H from a dictionary built from the
    # nearest neighbors of E and T (the legacy approach — we reuse it
    # because it's what the endpoint's downstream consumers expect).

    def missing_link(self, evidence_id: int, target_id: int,
                     top_k: int = 5,
                     dictionary_size: int = 300) -> Dict[str, Any]:
        """Abductive inference. Returns top_k hypothesis doc_ids ranked
        by their similarity to the residual H = T − E.

        The dictionary is the union of the `dictionary_size` nearest
        neighbors of E and of T. Drawing candidates from both anchors
        keeps the search space concentrated on plausible hypotheses and
        avoids the whole-corpus blowup."""
        e_vec = self.get_vector_by_id(evidence_id)
        t_vec = self.get_vector_by_id(target_id)
        if e_vec is None or t_vec is None:
            return {"results": [], "confidence": 0.0,
                    "audit": {"strategy": "a81_missing_link",
                              "reason": "missing_input_vector"}}

        # Residual hypothesis vector: what must combine with E to yield T.
        pipe_k = int(self._pipe.config().k)
        h_vec = ehc.superpose([t_vec, ehc.negate(e_vec)], pipe_k)

        # Dictionary: neighbors of both E and T, dedup'd. Using knn_vec so
        # the candidate set reflects what the LSH actually can route to
        # (not a random slice of the corpus).
        cand_ids: Dict[int, Dict[str, Any]] = {}
        for anchor in (e_vec, t_vec):
            for h in self.knn_vec(anchor, k=int(dictionary_size)):
                did = int(h["doc_id"])
                if did in (int(evidence_id), int(target_id)):
                    continue
                cand_ids.setdefault(did, h)
        # Score each dictionary candidate against H.
        scored: List[Tuple[int, float, Dict[str, Any]]] = []
        for did, meta in cand_ids.items():
            cv = self.get_vector_by_id(did)
            if cv is None:
                continue
            s = self.similarity(h_vec, cv)
            scored.append((did, s, meta["metadata"]))
        scored.sort(key=lambda t: t[1], reverse=True)

        results = [
            {"id": str(did), "doc_id": did,
             "similarity": round(float(s), 4),
             "type": "hypothesis",
             "metadata": md}
            for (did, s, md) in scored[:int(top_k)]
        ]
        confidence = results[0]["similarity"] if results else 0.0
        return {
            "results": results,
            "confidence": float(confidence),
            "audit": {"strategy": "a81_missing_link",
                      "evidence_id": evidence_id,
                      "target_id": target_id,
                      "dictionary_size": len(cand_ids)},
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
        # Edge-shape fields surface by name; everything else in the source
        # record is passed through so domain-specific fields (e.g. SRO
        # subject/relation/object, wiki categories, log level) reach the
        # caller without a shim update.
        passthrough = {k: v for k, v in rec.items()
                       if k not in ("doc_id", "text", "raw", "author",
                                    "site", "timestamp", "media_url",
                                    "url", "msg_id", "native_id")}
        return {
            "text":      rec.get("text", ""),
            "raw":       rec.get("raw", ""),
            "author":    rec.get("author", ""),
            "site":      rec.get("site", ""),
            "timestamp": rec.get("timestamp", ""),
            "media_url": media_url,
            "url":       rec.get("url", ""),
            "msg_id":    rec.get("msg_id", ""),
            "native_id": rec.get("native_id", ""),
            **passthrough,
        }


_MEDIA_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".webm", ".mkv"}


def _looks_like_media(u: str) -> bool:
    if not u:
        return False
    ext = os.path.splitext(u.lower())[1]
    return ext in _MEDIA_EXT
