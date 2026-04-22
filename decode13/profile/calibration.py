"""Stage 2 — (D, k) calibration sweep (PlanC §4.2).

Discipline:
  - One EHC pipeline in memory at a time. Built → filled → queried →
    explicitly deleted → gc.collect() → next pair. Python never holds
    two indices concurrently. Encoded vectors live inside the C++
    pipeline and are released on its destruction.
  - Samples are byte offsets, not materialized records. `ingest_text`
    is called one line at a time, seeking the open file to each offset.
  - Result aggregation is numpy-backed — per-row we retain only the
    scalars the profile JSON needs, never the raw hit lists.

Query sources (in preference order):
  1. operator: `--calibration-queries path/to/queries.jsonl` — each line
     has `query_text` and a `gold_ids` list (or `gold_offset`).
  2. logs: `--queries-from-logs path/to/logs.jsonl` — same schema.
  3. synthetic: mask-one-field on sampled records. The profile JSON
     flags this source explicitly so audit tools can see it.
"""

from __future__ import annotations

import gc
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..structural_encoder import build_config  # builds ehc.StructuralConfig
from .schema import CalibrationRow

# Import ehc lazily inside functions to keep this module importable for
# doc-generation / schema-only contexts where EHC isn't built.


def _ehc():
    """Late import so tests without EHC built can still import schema/elbow."""
    import ehc  # type: ignore
    return ehc


def _k_triples(dim: int) -> Tuple[int, int, int]:
    """k grid for a given D: {√D/2, √D, 2√D}, each rounded to int ≥ 1."""
    root = int(round(dim ** 0.5))
    return max(1, root // 2), max(1, root), max(1, 2 * root)


@contextmanager
def _transient_pipeline(dim: int, k: int):
    """Build an EHC pipeline, hand it to the caller, then explicitly
    release. The `del` + gc here is not cosmetic — EHC holds large
    codebook + LSH buffers and the GC timing otherwise leaks into the
    next pair's peak-memory window."""
    ehc = _ehc()
    cfg = build_config(dim=dim, k=k)
    pipeline = ehc.StructuralPipelineV13(cfg)
    try:
        yield pipeline
    finally:
        del pipeline
        gc.collect()


def _iter_records_at_offsets(source_path: Path, offsets: np.ndarray):
    """Generator yielding (doc_id, record_dict, query_text) by seeking
    to each offset. Uses the record's own `doc_id` field when present
    so calibration_queries.jsonl gold_ids align with ingest ids. Falls
    back to iteration order when no doc_id is on the record.
    Records are not held in memory beyond the loop iter."""
    with open(source_path, "rb") as f:
        for i, off in enumerate(offsets):
            f.seek(int(off))
            line = f.readline()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            did = int(r.get("doc_id", i)) if "doc_id" in r else i
            qt = _record_to_query_text(r)
            yield did, r, qt


def _record_to_query_text(record: dict) -> str:
    """The text a record would be indexed under. Identity for text
    records; S R O joined for structured."""
    if record.get("text"):
        return str(record["text"])
    parts = [str(record.get(f, "") or "") for f in ("subject", "relation", "object")]
    return " ".join(p for p in parts if p)


def _tier_of_sample(record: dict, router) -> str:
    return router.from_record(record).value


def _synthetic_queries(
    source_path: Path,
    offsets: np.ndarray,
    *,
    n_queries: int,
    seed: int = 1337,
) -> List[dict]:
    """Mask-one-field (or mask-first-half) synthetic queries.

    CEILING MEASUREMENT — tests self-recovery. For structured records
    with multiple fields, masks one field at random and queries with
    the rest. For single-field text records, uses the first ~60% of
    tokens as the probe, holding the whole text as gold.

    Returns a list of `{query_text, gold_ids}` dicts keyed by the
    record's `doc_id` field (or iteration index when absent) so ids
    align with the ingest path in `sweep()`.
    """
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(offsets), size=min(n_queries, len(offsets)), replace=False)
    queries: List[dict] = []
    with open(source_path, "rb") as f:
        for i in idx:
            off = int(offsets[int(i)])
            f.seek(off)
            line = f.readline()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            did = int(r.get("doc_id", i)) if "doc_id" in r else int(i)
            text_fields = [fld for fld in ("object", "relation", "text") if r.get(fld)]
            if len(text_fields) >= 2:
                masked = str(rng.choice(text_fields))
                probe = {k: v for k, v in r.items() if k != masked}
                qt = _record_to_query_text(probe)
            elif r.get("text"):
                # Single-text-field corpus: mask-first-half. Use the first
                # ~60% of tokens as probe; gold is the source record.
                toks = str(r["text"]).split()
                if len(toks) < 4:
                    continue
                cut = max(2, int(len(toks) * 0.6))
                qt = " ".join(toks[:cut])
            else:
                continue
            if not qt.strip():
                continue
            queries.append({"query_text": qt, "gold_ids": [did]})
    return queries


def _load_query_file(path: Path) -> List[dict]:
    """Schema: one JSONL line per query, {query_text, gold_ids: [int,...]}."""
    out: List[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if "gold_ids" not in obj and "gold_id" in obj:
                obj["gold_ids"] = [int(obj["gold_id"])]
            out.append(obj)
    return out


def _recall_at_k(hits: List[int], gold_ids: Sequence[int], k: int = 10) -> float:
    if not gold_ids:
        return 0.0
    top = set(hits[:k])
    return 1.0 if any(g in top for g in gold_ids) else 0.0


def sweep(
    source_path: str | Path,
    offsets: np.ndarray,
    *,
    grid_dims: Sequence[int],
    queries: List[dict],
    tier_by_sample_id: Dict[int, str],
    top_k: int = 10,
    n_threads: int = 0,
    progress: bool = True,
) -> List[CalibrationRow]:
    """Run the (D, k) sweep.

    For each (D, k) pair:
      1. Build a fresh EHC pipeline.
      2. Ingest every sampled record via `pipeline.ingest_text` (C++).
      3. Issue each query, record hit list and per-query latency.
      4. Tear down pipeline before moving to the next pair.

    Returns one CalibrationRow per (D, k) pair. Rows carry per-tier
    recall (mean over queries that had gold in that tier), plus
    p50/p95 latency and total encode time.
    """
    source_path = Path(source_path)
    rows: List[CalibrationRow] = []

    total_pairs = sum(len(_k_triples(d)) for d in grid_dims)
    pair_idx = 0
    for dim in grid_dims:
        for k in _k_triples(dim):
            pair_idx += 1
            if progress:
                print(f"    [sweep {pair_idx}/{total_pairs}] D={dim} k={k} "
                      f"build+ingest…", file=sys.stderr, flush=True)
            pair_t0 = time.perf_counter()
            with _transient_pipeline(dim, k) as pipeline:
                t0 = time.perf_counter()
                # Gather (text, id) in small batches, then hand to the C++
                # parallel ingest path. Python only holds one batch worth
                # of string references at a time; the C++ pipeline owns
                # the encoded vectors. Explicit ids preserve the doc_id
                # space so calibration_queries.jsonl gold_ids match.
                _BATCH = 1000
                batch_texts: List[str] = []
                batch_ids: List[int] = []
                for did, _record, qt in _iter_records_at_offsets(source_path, offsets):
                    if not qt:
                        continue
                    batch_texts.append(qt)
                    batch_ids.append(int(did))
                    if len(batch_texts) >= _BATCH:
                        pipeline.ingest_batch_parallel(batch_texts, batch_ids, n_threads)
                        batch_texts.clear()
                        batch_ids.clear()
                if batch_texts:
                    pipeline.ingest_batch_parallel(batch_texts, batch_ids, n_threads)
                    batch_texts.clear()
                    batch_ids.clear()
                encode_time = time.perf_counter() - t0

                # Query. Measure per-query latency; record only the top-k
                # hit ids, never the scores (scores are irrelevant to
                # recall@10 and would bloat Python memory at scale).
                per_query_ms: List[float] = []
                per_tier_hits: Dict[str, List[int]] = {}
                per_tier_tot:  Dict[str, int] = {}
                for q in queries:
                    qt = q.get("query_text", "")
                    gold_ids = q.get("gold_ids", [])
                    if not qt or not gold_ids:
                        continue
                    tq = time.perf_counter()
                    hits = pipeline.query_text(qt, top_k)  # C++
                    per_query_ms.append((time.perf_counter() - tq) * 1000.0)
                    # EHC's StructuralQueryResult exposes .ids / .scores.
                    # Fall back to list-of-(id,score) tuples for older builds
                    # and raw int lists for the simplest case.
                    if hasattr(hits, "ids"):
                        hit_ids = [int(i) for i in hits.ids]
                    else:
                        hit_ids = [
                            int(h[0]) if isinstance(h, (tuple, list)) else int(h)
                            for h in hits
                        ]
                    # Bucket the recall into the tier of the *first* gold id.
                    tier = tier_by_sample_id.get(int(gold_ids[0]), "unknown")
                    per_tier_tot[tier] = per_tier_tot.get(tier, 0) + 1
                    if _recall_at_k(hit_ids, gold_ids, k=top_k) > 0:
                        per_tier_hits[tier] = per_tier_hits.get(tier, 0) + 1

                recall_by_tier = {
                    t: (per_tier_hits.get(t, 0) / per_tier_tot[t])
                    for t in per_tier_tot
                }
                lat = np.array(per_query_ms, dtype=np.float64) if per_query_ms else np.zeros(1)
                rows.append(CalibrationRow(
                    dim=int(dim),
                    k=int(k),
                    recall_by_tier=recall_by_tier,
                    p50_latency_ms=float(np.percentile(lat, 50)),
                    p95_latency_ms=float(np.percentile(lat, 95)),
                    encode_time_s=float(encode_time),
                ))
                if progress:
                    wtr = (min(recall_by_tier.values())
                           if recall_by_tier else 0.0)
                    print(f"    [sweep {pair_idx}/{total_pairs}] D={dim} "
                          f"k={k} done in {time.perf_counter()-pair_t0:.1f}s "
                          f"worst_tier_recall={wtr:.3f} "
                          f"p50={float(np.percentile(lat, 50)):.1f}ms",
                          file=sys.stderr, flush=True)
    return rows


def build_queries(
    source_path: Path,
    offsets: np.ndarray,
    *,
    operator_queries: Optional[Path] = None,
    log_queries: Optional[Path] = None,
    synthetic: bool = False,
    n_queries: int = 200,
) -> Tuple[List[dict], str]:
    """Resolve the query source per PlanC §9 preference order.

    Returns `(queries, source_label)` where source_label is one of
    `"operator"`, `"logs"`, or `"synthetic"` for the profile JSON.
    Synthetic emits a stderr warning that the recall@10 numbers are
    a ceiling measurement.
    """
    if operator_queries is not None:
        return _load_query_file(operator_queries), "operator"
    if log_queries is not None:
        return _load_query_file(log_queries), "logs"
    if not synthetic:
        raise ValueError(
            "No calibration queries provided. Pass --calibration-queries, "
            "--queries-from-logs, or opt in to --synthetic-queries (dev only).")
    print(
        "WARNING: synthetic calibration queries requested. recall@10 in the "
        "resulting profile is a CEILING measurement — it tests self-recovery "
        "via mask-one-field, not real-query generalization. Do not use "
        "synthetic profiles for production sizing decisions.",
        file=sys.stderr,
    )
    return _synthetic_queries(source_path, offsets, n_queries=n_queries), "synthetic"
