#!/usr/bin/env python3
"""autotune_max_slots.py — 2-D (D, max_slots) autotune sweep.

WHY THIS EXISTS
===============
The standard autotune in `encode_unstructured.py` / `encode_triples.py`
derives `max_slots` from D and `p99_atoms`:

    k         = round(sqrt(D))
    max_slots = max(2·sqrt(k), p99_atoms)   capped at 256

That sizes the binding table to the 99th-percentile record. The longest
~1% of records — the tail — exceed `max_slots` and have their trailing
atoms truncated during slot binding. For narrative corpora where tail
records can carry meaningful signal, the heuristic may silently cap
recall on long-record queries without showing up in the average Hit@1.

This sweep treats `max_slots` as an *independent* axis. For each D in
the `predict_d_zone(p99)` zone, and each max_slots candidate (drawn
from the corpus's actual percentiles + the hard cap), we build a fresh
`ehc.StructuralPipelineV13`, ingest a 1M sample, run an oracle, and
record:

  - Hit@1  (overall, averaged across all oracle queries)
  - Hit@1_tail     (queries whose gold record has atom_count > p99)
  - Hit@1_nontail  (queries whose gold record has atom_count ≤ p99)
  - p50 latency

A winner is picked under the policy
`smallest D at max Hit@1_overall, smallest max_slots at chosen D`,
and the full grid is persisted to `sweep_results.json` for inspection.

This script does NOT modify the production encode path. It's a pure
diagnostic tool: surface whether the heuristic is leaving tail recall
on the table, then decide whether to lift the default or just bump
max_slots for a specific run.

USAGE
=====
    python3 -m encode.autotune_max_slots \\
        --source /path/to/corpus.jsonl \\
        --output /path/to/sweep_dir \\
        --operator-queries /path/to/operator_queries.jsonl

The `--operator-queries` argument is strongly recommended for narrative
corpora; the synthetic mask-first oracle is heavily biased upward in D.
"""
from __future__ import annotations

import argparse
import gc
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

# EHC import probe — same pattern as encode_unstructured.py
for _d in (1, 2, 3):
    _p = _HERE.parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc  # noqa: E402

from config import resolve_workers  # noqa: E402
from decode13 import build_structural_config  # noqa: E402
from encode._autotune import (  # noqa: E402
    derive_k_constants,
    load_operator_queries,
    predict_d_zone,
)
from encode.encode_unstructured import _stream_records  # noqa: E402


# ── arg parsing ──────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        prog="autotune_max_slots",
        description="2-D (D, max_slots) autotune sweep with tail-split Hit@1.",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--source", required=True,
                   help="Source corpus (JSONL or JSON array). Same shape "
                        "the encoder reads.")
    p.add_argument("--output", required=True,
                   help="Output dir — receives the autotune sample and "
                        "sweep_results.json.")
    p.add_argument("--operator-queries", default=None,
                   help="Optional JSONL of {query_text, gold_ids: [int]}. "
                        "Strongly recommended for narrative corpora.")
    p.add_argument("--workers", type=int, default=0,
                   help="Ingest threads. 0 = resolve via A81_CPU_FRACTION.")
    p.add_argument("--max-slots-cap", type=int, default=256,
                   help="Hard ceiling on max_slots. Default 256 matches "
                        "the production encoder's ceiling.")
    p.add_argument("--sample-cap", type=int, default=1_000_000,
                   help="Max records sampled for the sweep. 1M matches "
                        "the production autotune.")
    p.add_argument("--no-hebbian", action="store_true",
                   help="Disable Hebbian in the swept pipelines. Default "
                        "matches the production encoder (Hebbian on).")
    return p.parse_args()


# ── streaming pass: histogram + sample ───────────────────────────────────

def _stream_pass(
    source: Path,
    output: Path,
    sample_cap: int,
) -> Tuple[Path, Counter, int, int, Dict[int, int]]:
    """Single streaming pass over the source.

    Writes a sample JSONL (one record per line) and returns:
      - sample_path
      - atom-count histogram (atom_count → records)
      - total record count (after empty-text skip)
      - sampled record count
      - per-doc-id atom_count map (for tail classification)

    The sample preserves the encoder's `doc_id` so operator-query
    gold_ids line up exactly with what the production pipeline assigns.
    """
    sample_path = output / ".autotune_max_slots_sample.jsonl"
    BUCKETS = 4096
    histogram: Counter = Counter()
    doc_id_atoms: Dict[int, int] = {}
    n_total = 0
    n_sampled = 0
    with open(sample_path, "w", encoding="utf-8") as sf:
        for i, (text, rec) in enumerate(_stream_records(source)):
            atoms = len(text.split())
            histogram[min(atoms, BUCKETS)] += 1
            doc_id = int(rec.get("doc_id", i))
            doc_id_atoms[doc_id] = atoms
            n_total += 1
            if n_sampled < sample_cap:
                sf.write(json.dumps({"i": doc_id, "t": text, "a": atoms},
                                    ensure_ascii=False) + "\n")
                n_sampled += 1
    return sample_path, histogram, n_total, n_sampled, doc_id_atoms


def _percentiles_from_histogram(histogram: Counter,
                                 percentiles: Tuple[float, ...]
                                 ) -> Dict[float, int]:
    """Compute multiple percentiles from a packed histogram in one pass."""
    total = sum(histogram.values())
    if total == 0:
        return {p: 0 for p in percentiles}
    sorted_keys = sorted(histogram.keys())
    out: Dict[float, int] = {}
    cum = 0
    targets = [(p, p * total) for p in percentiles]
    ti = 0
    for k in sorted_keys:
        cum += histogram[k]
        while ti < len(targets) and cum >= targets[ti][1]:
            out[targets[ti][0]] = k
            ti += 1
    # Fill in any percentiles that fell exactly at the max bucket.
    last_key = sorted_keys[-1] if sorted_keys else 0
    for p, _t in targets:
        out.setdefault(p, last_key)
    return out


# ── max_slots candidate generation ───────────────────────────────────────

def _max_slots_candidates(k: int,
                           p99: int, p995: int, p999: int, p100: int,
                           cap: int) -> List[int]:
    """Produce the max_slots values to sweep at this D.

    Includes the heuristic's baseline (max(2·√k, p99)) plus larger
    values pinned to p99.5, p99.9, and p100 (capped). Always includes
    the hard cap. Always includes the 2·√k floor as a "what if we
    *don't* lift for p99" point — useful for diagnosing whether the
    p99 lift is even necessary for this corpus.
    """
    base = int(round(2.0 * math.sqrt(max(int(k), 1))))
    cands = {min(base, cap), min(max(base, p99), cap)}
    for pct in (p995, p999, p100):
        cands.add(min(max(base, int(pct)), cap))
    cands.add(cap)
    return sorted(c for c in cands if c >= 1)


# ── oracle builders ──────────────────────────────────────────────────────

def _build_operator_oracle(
    operator_queries_path: str,
) -> List[Tuple[int, str, Set[int]]]:
    """Load operator queries from JSONL. Returns [(probe_id, query_text,
    gold_id_set), ...]. probe_id is the first gold_id, used as a
    "representative" gold record for tail classification."""
    raws = load_operator_queries(operator_queries_path)
    out = []
    for q in raws:
        gold = set(int(g) for g in q.get("gold_ids", []) or [])
        if not gold:
            continue
        out.append((next(iter(gold)), q["query_text"], gold))
    return out


def _build_synthetic_oracle(
    sample_path: Path, n_queries: int = 200,
) -> List[Tuple[int, str, Set[int]]]:
    """Fallback: synthetic mask-first queries (cut text at 60%)."""
    import random
    rng = random.Random(42)
    # Count lines to make a stable sample, then pick rows.
    lines = []
    with open(sample_path, "r", encoding="utf-8") as sf:
        for line in sf:
            lines.append(line)
    rng.shuffle(lines)
    out = []
    for line in lines:
        rec = json.loads(line)
        toks = rec["t"].split()
        if len(toks) < 4:
            continue
        cut = max(2, int(len(toks) * 0.6))
        out.append((rec["i"], " ".join(toks[:cut]), {rec["i"]}))
        if len(out) >= n_queries:
            break
    return out


# ── single sweep point: build + ingest + measure ─────────────────────────

def _sweep_one(
    dim: int, k: int, max_slots: int,
    sample_path: Path,
    queries: List[Tuple[int, str, Set[int]]],
    doc_id_atoms: Dict[int, int],
    p99: int,
    workers: int,
    hebbian: bool,
) -> Dict:
    """Build a fresh pipeline, ingest the sample, run the oracle,
    return a result dict.

    Tear-down is handled by the caller (we don't gc.collect() here so
    the caller can decide pacing across the sweep)."""
    cfg = build_structural_config(
        dim=dim, k=k, max_slots=max_slots,
        enable_bigram=True, enable_kv=True,
        enable_hebbian=hebbian, hebbian_window=5,
    )
    pipe = ehc.StructuralPipelineV13(cfg)

    # Ingest the sample. One batch worth in Python memory.
    BATCH = 1_000
    tx, ix = [], []
    with open(sample_path, "r", encoding="utf-8") as sf:
        for line in sf:
            rec = json.loads(line)
            tx.append(rec["t"])
            ix.append(int(rec["i"]))
            if len(tx) >= BATCH:
                pipe.ingest_batch_parallel(tx, ix, workers)
                tx.clear()
                ix.clear()
    if tx:
        pipe.ingest_batch_parallel(tx, ix, workers)

    # Warmup (un-timed)
    for _, qt, _ in queries[:20]:
        (pipe.query_text_expanded(qt, 10, 3) if hebbian
         else pipe.query_text(qt, 10))

    # Measured run + tail-split bookkeeping.
    latencies: List[float] = []
    hits_overall = 0
    hits_tail = 0
    hits_nontail = 0
    n_tail = 0
    n_nontail = 0
    for probe_id, qt, gold_set in queries:
        ta = time.perf_counter()
        r = (pipe.query_text_expanded(qt, 10, 3) if hebbian
             else pipe.query_text(qt, 10))
        latencies.append((time.perf_counter() - ta) * 1000.0)
        ids = list(r.ids)
        hit = bool(ids) and int(ids[0]) in gold_set
        if hit:
            hits_overall += 1
        probe_atoms = doc_id_atoms.get(probe_id, 0)
        if probe_atoms > p99:
            n_tail += 1
            if hit:
                hits_tail += 1
        else:
            n_nontail += 1
            if hit:
                hits_nontail += 1

    latencies.sort()
    n = len(queries)
    p50 = latencies[len(latencies) // 2] if latencies else 0.0
    p99_ms = latencies[int(0.99 * len(latencies))] if latencies else 0.0

    del pipe
    return {
        "D": int(dim),
        "k": int(k),
        "max_slots": int(max_slots),
        "n_queries": int(n),
        "hit_at_1_overall":   round(100.0 * hits_overall / max(n, 1), 2),
        "hit_at_1_tail":      round(100.0 * hits_tail    / max(n_tail, 1), 2),
        "hit_at_1_nontail":   round(100.0 * hits_nontail / max(n_nontail, 1), 2),
        "n_tail":    n_tail,
        "n_nontail": n_nontail,
        "p50_ms":    round(p50,    3),
        "p99_ms":    round(p99_ms, 3),
    }


# ── reporting ────────────────────────────────────────────────────────────

def _print_table(results: List[Dict], baseline_pairs: Set[Tuple[int, int]]):
    """Pretty-print the sweep grid. `baseline_pairs` marks the
    heuristic's default (D, max_slots) pair so you can read the delta
    by eye."""
    print()
    print(f"{'D':>6} {'k':>4} {'slots':>6}  "
          f"{'Hit@1':>7} {'tail':>7} {'¬tail':>7}  "
          f"{'p50_ms':>7} {'p99_ms':>7}  marker")
    print("-" * 80)
    for r in results:
        marker = "← heuristic baseline" if (r["D"], r["max_slots"]) in baseline_pairs else ""
        print(f"{r['D']:>6} {r['k']:>4} {r['max_slots']:>6}  "
              f"{r['hit_at_1_overall']:>6.1f}% "
              f"{r['hit_at_1_tail']:>6.1f}% "
              f"{r['hit_at_1_nontail']:>6.1f}%  "
              f"{r['p50_ms']:>7.3f} {r['p99_ms']:>7.3f}  {marker}")
    print()


# ── main ─────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        print(f"ERROR: source not found: {source}", file=sys.stderr)
        return 2

    workers = resolve_workers(args.workers)
    hebbian = not args.no_hebbian

    print(f"[sweep] source       = {source}")
    print(f"[sweep] output       = {output}")
    print(f"[sweep] workers      = {workers}")
    print(f"[sweep] hebbian      = {hebbian}")
    print(f"[sweep] max_slots_cap= {args.max_slots_cap}")

    # 1. Streaming pass
    t0 = time.perf_counter()
    print(f"[sweep] streaming source → histogram + sample (cap={args.sample_cap:,})…",
          flush=True)
    sample_path, histogram, n_total, n_sampled, doc_id_atoms = _stream_pass(
        source, output, args.sample_cap)
    print(f"[sweep]   {n_total:,} records, {n_sampled:,} sampled in "
          f"{time.perf_counter()-t0:.1f}s", flush=True)

    # 2. Percentiles
    pcts = _percentiles_from_histogram(histogram, (0.99, 0.995, 0.999, 1.0))
    p99 = int(pcts[0.99])
    p995 = int(pcts[0.995])
    p999 = int(pcts[0.999])
    p100 = int(pcts[1.0])
    print(f"[sweep] atom-count percentiles: p99={p99}  p99.5={p995}  "
          f"p99.9={p999}  p100={p100}", flush=True)

    # 3. D zone (mirror the production autotune's choice)
    has_op = bool(args.operator_queries)
    predicted_zone, rationale = predict_d_zone(p99, has_operator_queries=has_op)
    print(f"[sweep] D zone: {predicted_zone}  rationale: {rationale}",
          flush=True)

    # 4. Oracle
    if args.operator_queries:
        queries = _build_operator_oracle(args.operator_queries)
        print(f"[sweep] oracle: operator queries ({len(queries)} from "
              f"{args.operator_queries})", flush=True)
        oracle_kind = "operator"
    else:
        queries = _build_synthetic_oracle(sample_path)
        print(f"[sweep] oracle: synthetic mask-first ({len(queries)} queries) "
              f"— biased upward in D", flush=True)
        oracle_kind = "synthetic_mask_first"

    if not queries:
        print("ERROR: no oracle queries built; aborting", file=sys.stderr)
        return 3

    # 5. Sweep
    results: List[Dict] = []
    baseline_pairs: Set[Tuple[int, int]] = set()
    for dim in predicted_zone:
        k = max(1, int(round(math.sqrt(dim))))
        baseline_ms = derive_k_constants(k, p99_atoms=p99)["max_slots"]
        baseline_ms = min(baseline_ms, args.max_slots_cap)
        baseline_pairs.add((dim, baseline_ms))
        for ms in _max_slots_candidates(k, p99, p995, p999, p100,
                                          args.max_slots_cap):
            t_sweep = time.perf_counter()
            r = _sweep_one(
                dim=dim, k=k, max_slots=ms,
                sample_path=sample_path, queries=queries,
                doc_id_atoms=doc_id_atoms, p99=p99,
                workers=workers, hebbian=hebbian)
            r["is_baseline"] = (ms == baseline_ms)
            r["wall_s"] = round(time.perf_counter() - t_sweep, 2)
            results.append(r)
            print(f"[sweep]  D={r['D']:>5} k={r['k']:>3} slots={r['max_slots']:>3}  "
                  f"Hit@1={r['hit_at_1_overall']:>5.1f}%  "
                  f"tail={r['hit_at_1_tail']:>5.1f}%  "
                  f"¬tail={r['hit_at_1_nontail']:>5.1f}%  "
                  f"p50={r['p50_ms']:>5.2f}ms  wall={r['wall_s']:.1f}s",
                  flush=True)
            gc.collect()

    # 6. Winner
    winner = sorted(
        results,
        key=lambda r: (-r["hit_at_1_overall"], r["D"], r["max_slots"], r["p50_ms"]),
    )[0]

    # 7. Persist + summary
    out = {
        "policy": "smallest_D_at_max_Hit@1_then_smallest_max_slots",
        "source":          str(source),
        "n_total":         n_total,
        "n_sampled":       n_sampled,
        "max_slots_cap":   args.max_slots_cap,
        "hebbian":         hebbian,
        "oracle":          oracle_kind,
        "n_queries":       len(queries),
        "percentiles": {
            "p99":  p99, "p99.5": p995, "p99.9": p999, "p100": p100,
        },
        "D_zone":          list(predicted_zone),
        "rationale":       rationale,
        "results":         results,
        "winner":          winner,
        "baseline_pairs":  sorted(baseline_pairs),
    }
    out_path = output / "sweep_results.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)

    # 8. Print final table + winner
    _print_table(results, baseline_pairs)

    base_at_winner_D = next(
        (r for r in results
         if r["D"] == winner["D"] and r["is_baseline"]),
        None,
    )
    delta_pp = (winner["hit_at_1_overall"] -
                base_at_winner_D["hit_at_1_overall"]) if base_at_winner_D else 0.0
    delta_tail_pp = (winner["hit_at_1_tail"] -
                     base_at_winner_D["hit_at_1_tail"]) if base_at_winner_D else 0.0
    print(f"[sweep] winner: D={winner['D']}  max_slots={winner['max_slots']}  "
          f"Hit@1={winner['hit_at_1_overall']:.1f}%  "
          f"tail={winner['hit_at_1_tail']:.1f}%  "
          f"p50={winner['p50_ms']:.2f}ms")
    if base_at_winner_D and not winner["is_baseline"]:
        print(f"[sweep]   vs baseline at same D "
              f"(max_slots={base_at_winner_D['max_slots']}): "
              f"Δ Hit@1 = {delta_pp:+.1f} pp   "
              f"Δ Hit@1_tail = {delta_tail_pp:+.1f} pp")
    elif winner["is_baseline"]:
        print(f"[sweep]   heuristic baseline is the winner — "
              f"no max_slots lift would help here")
    print(f"[sweep] full results → {out_path}")

    # 9. Cleanup sample
    try:
        sample_path.unlink()
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
