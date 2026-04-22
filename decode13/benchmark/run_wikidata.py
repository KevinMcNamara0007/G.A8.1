"""End-to-end Wikidata benchmark comparing Tier 1 (atomic) vs Baseline
(shattered) encoding.

Pipeline:
  1. Stream-sample N triples from triples_21M.json (deterministic seed).
  2. Sample Q queries from the sampled corpus — query = (subject,
     relation), gold answer = record_id of the source triple. A query
     is only retained if its (s, r) is unique in the corpus (so there's
     an unambiguous gold record at rank 1).
  3. Encode the corpus twice — once with TierEncoder (Tier 1 atomic),
     once with CanonicalBaselineEncoder (shattered).
  4. Run every query against both indices. Record rank of gold, top-1
     record, score, and latency.
  5. Emit per-query CSV + aggregate metrics + summary table.

The whole thing is single-process for reproducibility and simplicity.
EHC's knn_query releases the GIL so even this is fast.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from concurrent.futures import ThreadPoolExecutor
from decode13.tier_encode import TierEncoder
from decode13.tier_query import QueryService13
from decode13.benchmark.baseline_encoder import CanonicalBaselineEncoder
from decode13.benchmark.parallel_encode import (
    parallel_encode_tier1, parallel_encode_baseline,
)
from decode13.benchmark.triples_reader import stream_triples


TRIPLES_PATH = "/Users/stark/Quantum_Computing_Lab/GoldC/triples_21M.json"


def _load_sample(path: str, n: int, seed: int, stride: int = 1) -> List[dict]:
    """Load N triples deterministically by streaming the first N*stride
    records and keeping every `stride`-th.

    Stride=1 (default) = contiguous first-N. This is the pragmatic choice
    for this benchmark: the corpus slice is ~3% of Wikidata, already
    diverse enough to exhibit the compound-token shape the plan targets,
    and avoids parsing all 21M records up-front.

    Pass stride>1 to get a uniformly-spaced sample across the full file,
    at the cost of proportionally longer streaming time.
    """
    rng = random.Random(seed)
    out: List[dict] = []
    want = n * stride
    for i, trip in enumerate(stream_triples(path, limit=want)):
        if stride <= 1 or i % stride == 0:
            out.append(trip)
            if len(out) >= n:
                break
    rng.shuffle(out)  # deterministic shuffle so query order ≠ record order
    # Re-assign record ids post-shuffle so the test harness can use the
    # index-in-returned-list as the stable record id.
    return out


def _sample_queries(
    triples: List[dict],
    n_queries: int,
    seed: int,
) -> List[Tuple[int, str, str, str]]:
    """Sample queries such that each (s, r) key is UNIQUE in the corpus
    (so there's exactly one gold record). Returns (record_id, s, r, o)."""
    sr_count: Counter = Counter()
    for rec in triples:
        key = (rec.get("subject", ""), rec.get("relation", ""))
        sr_count[key] += 1
    unique_sr = {k for k, v in sr_count.items() if v == 1}

    # Walk the corpus in order and pick records whose key is in unique_sr.
    # Shuffle afterwards so the query set isn't ordered by record id.
    candidates: List[Tuple[int, str, str, str]] = []
    for i, rec in enumerate(triples):
        key = (rec.get("subject", ""), rec.get("relation", ""))
        if key in unique_sr:
            candidates.append(
                (i, rec.get("subject", ""), rec.get("relation", ""),
                 rec.get("object", ""))
            )
    rng = random.Random(seed)
    rng.shuffle(candidates)
    return candidates[:n_queries]


def _encode_all(encoder, triples: List[dict], label: str, tier_mode: bool = False):
    t0 = time.perf_counter()
    for rid, rec in enumerate(triples):
        if tier_mode:
            encoder.encode_record(rid, rec, explicit_sro=True)
        else:
            encoder.encode_record(rid, rec)
        if (rid + 1) % 50_000 == 0:
            print(f"  [{label}] encoded {rid+1:,}/{len(triples):,} "
                  f"({time.perf_counter()-t0:.1f}s)")
    encoder.build_index()
    print(f"  [{label}] done: {encoder.n_vectors:,} vectors in "
          f"{time.perf_counter()-t0:.1f}s")


def _rank_of(results: list, gold_id: int, field: str) -> int:
    """Return 1-based rank of gold_id in results list, or 0 if absent."""
    for i, r in enumerate(results, start=1):
        if r[field] == gold_id:
            return i
    return 0


def _pct(x: int, total: int) -> float:
    return 100.0 * x / total if total else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-triples", type=int, default=500_000)
    ap.add_argument("--n-queries", type=int, default=500)
    ap.add_argument("--dim", type=int, default=4096)
    ap.add_argument("--k", type=int, default=64)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--out-dir", type=str,
                    default=str(_ROOT / "decode13" / "benchmark" / "out"))
    ap.add_argument("--verbose-rows", type=int, default=20,
                    help="Number of per-query rows to print to stdout")
    ap.add_argument("--retain-triples", action="store_true",
                    help="Keep per-vector ExtractedTriple objects (small corpora only; "
                         "always off-by-default at >1M scale).")
    ap.add_argument("--workers", type=int, default=8,
                    help="Encode workers (multiprocessing.Pool, fork).")
    ap.add_argument("--warmup", type=int, default=20,
                    help="Throwaway queries before measurement to warm caches "
                         "and amortize cold-page I/O. 0 disables.")
    ap.add_argument("--query-threads", type=int, default=8,
                    help="Concurrent queries via ThreadPoolExecutor.")
    ap.add_argument("--serial", action="store_true",
                    help="Use the single-process encode path (for comparison).")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"── Loading {args.n_triples:,} triples (seed={args.seed}) ──")
    t0 = time.perf_counter()
    triples = _load_sample(TRIPLES_PATH, args.n_triples, args.seed)
    print(f"  loaded {len(triples):,} in {time.perf_counter()-t0:.1f}s")

    # Sample benchmark + warmup queries together, then split. Warmup set
    # is disjoint from the measured set so we're not double-timing the
    # same records.
    total_needed = args.n_queries + max(0, args.warmup)
    all_queries = _sample_queries(triples, total_needed, args.seed + 1)
    queries = all_queries[:args.n_queries]
    warmup_queries = all_queries[args.n_queries:args.n_queries + args.warmup]
    print(f"  sampled {len(queries)} unique-(s,r) queries "
          f"(+ {len(warmup_queries)} warmup)")
    if not queries:
        print("NO UNIQUE QUERIES — bump --n-triples")
        return 1

    # ── Encode tier-1 atomic ──
    print(f"\n── Encoding Tier 1 (atomic) — dim={args.dim} k={args.k} "
          f"{'serial' if args.serial else f'parallel x{args.workers}'} ──")
    if args.serial:
        t1_enc = TierEncoder(dim=args.dim, k=args.k, seed=args.seed,
                             retain_triples=args.retain_triples)
        _encode_all(t1_enc, triples, "tier1", tier_mode=True)
    else:
        t1_enc = parallel_encode_tier1(
            triples, dim=args.dim, k=args.k, seed=args.seed,
            n_workers=args.workers,
        )
        print(f"  [tier1] done: {t1_enc.n_vectors:,} vectors")

    print(f"\n── Encoding baseline (shattered) — dim={args.dim} k={args.k} "
          f"{'serial' if args.serial else f'parallel x{args.workers}'} ──")
    if args.serial:
        base_enc = CanonicalBaselineEncoder(
            dim=args.dim, k=args.k, seed=args.seed,
            retain_tokens=args.retain_triples)
        _encode_all(base_enc, triples, "baseline", tier_mode=False)
    else:
        base_enc = parallel_encode_baseline(
            triples, dim=args.dim, k=args.k, seed=args.seed,
            n_workers=args.workers,
        )
        print(f"  [baseline] done: {base_enc.n_vectors:,} vectors")

    # Query samples have already been extracted into `queries`.
    # Free the source list so the 21M dicts aren't held through the query phase.
    corpus_size = len(triples)
    del triples
    import gc as _gc; _gc.collect()

    # ── Query both ──
    print(f"\n── Running {len(queries)} queries (threads={args.query_threads}) ──")
    svc = QueryService13(t1_enc)

    if warmup_queries:
        print(f"  [warmup] running {len(warmup_queries)} throwaway queries "
              f"(timing discarded)…", flush=True)
        t_warm = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.query_threads) as ex:
            def _warm_one(item):
                _, (_rid, s, r, _o) = item
                svc.query(subject=s, relation=r, k=args.top_k, explicit_sro=True)
                base_enc.query(subject=s, relation=r, k=args.top_k)
            # exhaust the map iterator
            list(ex.map(_warm_one, list(enumerate(warmup_queries))))
        print(f"  [warmup] done in {time.perf_counter()-t_warm:.1f}s",
              flush=True)

    def run_one(item):
        i, (rid, s, r, o) = item
        t_a = time.perf_counter()
        res_t1 = svc.query(subject=s, relation=r, k=args.top_k, explicit_sro=True)
        lat_t1 = (time.perf_counter() - t_a) * 1000.0
        rank_t1 = _rank_of(res_t1["results"], rid, "source_record_id")

        t_a = time.perf_counter()
        res_b = base_enc.query(subject=s, relation=r, k=args.top_k)
        lat_b = (time.perf_counter() - t_a) * 1000.0
        rank_b = _rank_of(res_b, rid, "source_record_id")

        top_t1 = res_t1["results"][0] if res_t1["results"] else None
        top_b = res_b[0] if res_b else None

        return {
            "q_idx": i, "subject": s, "relation": r, "gold_object": o,
            "gold_record_id": rid,
            "t1_rank": rank_t1,
            "t1_top_rid": top_t1["source_record_id"] if top_t1 else -1,
            "t1_top_tri": (f"{top_t1['triple']['s']}|{top_t1['triple']['r']}|"
                           f"{top_t1['triple']['o']}"
                           if top_t1 and top_t1.get("triple") else ""),
            "t1_top_score": round(top_t1["raw_score"], 4) if top_t1 else 0.0,
            "t1_latency_ms": round(lat_t1, 2),
            "b_rank": rank_b,
            "b_top_rid": top_b["source_record_id"] if top_b else -1,
            "b_top_tokens": "|".join(top_b["tokens"][:5]) if top_b else "",
            "b_top_score": round(top_b["raw_score"], 4) if top_b else 0.0,
            "b_latency_ms": round(lat_b, 2),
        }

    t_qstart = time.perf_counter()
    per_query_rows: List[dict] = [None] * len(queries)
    with ThreadPoolExecutor(max_workers=args.query_threads) as ex:
        for row in ex.map(run_one, list(enumerate(queries))):
            per_query_rows[row["q_idx"]] = row
    print(f"  queries done in {time.perf_counter()-t_qstart:.1f}s")

    t1_latencies = [r["t1_latency_ms"] for r in per_query_rows]
    base_latencies = [r["b_latency_ms"] for r in per_query_rows]
    t1_hit1 = sum(1 for r in per_query_rows if r["t1_rank"] == 1)
    t1_hit5 = sum(1 for r in per_query_rows if 1 <= r["t1_rank"] <= 5)
    t1_hit10 = sum(1 for r in per_query_rows if 1 <= r["t1_rank"] <= 10)
    t1_mrr = sum((1.0 / r["t1_rank"]) for r in per_query_rows if r["t1_rank"] > 0)
    b_hit1 = sum(1 for r in per_query_rows if r["b_rank"] == 1)
    b_hit5 = sum(1 for r in per_query_rows if 1 <= r["b_rank"] <= 5)
    b_hit10 = sum(1 for r in per_query_rows if 1 <= r["b_rank"] <= 10)
    b_mrr = sum((1.0 / r["b_rank"]) for r in per_query_rows if r["b_rank"] > 0)

    # ── Write CSV ──
    csv_path = out_dir / f"per_query_{args.n_triples}_{args.n_queries}.csv"
    fieldnames = list(per_query_rows[0].keys())
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(per_query_rows)
    print(f"per-query CSV: {csv_path}")

    n = len(queries)
    summary = {
        "corpus_size": corpus_size,
        "n_queries": n,
        "dim": args.dim,
        "k": args.k,
        "tier1": {
            "hit@1": round(_pct(t1_hit1, n), 2),
            "hit@5": round(_pct(t1_hit5, n), 2),
            "hit@10": round(_pct(t1_hit10, n), 2),
            "mrr": round(t1_mrr / n, 4),
            "p50_ms": round(statistics.median(t1_latencies), 2),
            "p85_ms": round(statistics.quantiles(t1_latencies, n=100)[84], 2)
                       if len(t1_latencies) >= 100 else
                       round(max(t1_latencies), 2),
            "mean_ms": round(statistics.mean(t1_latencies), 2),
        },
        "baseline": {
            "hit@1": round(_pct(b_hit1, n), 2),
            "hit@5": round(_pct(b_hit5, n), 2),
            "hit@10": round(_pct(b_hit10, n), 2),
            "mrr": round(b_mrr / n, 4),
            "p50_ms": round(statistics.median(base_latencies), 2),
            "p85_ms": round(statistics.quantiles(base_latencies, n=100)[84], 2)
                       if len(base_latencies) >= 100 else
                       round(max(base_latencies), 2),
            "mean_ms": round(statistics.mean(base_latencies), 2),
        },
    }
    summary["delta_hit@1_pp"] = round(
        summary["tier1"]["hit@1"] - summary["baseline"]["hit@1"], 2)
    summary["delta_hit@5_pp"] = round(
        summary["tier1"]["hit@5"] - summary["baseline"]["hit@5"], 2)

    summary_path = out_dir / f"summary_{args.n_triples}_{args.n_queries}.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"summary JSON: {summary_path}\n")

    # ── Print summary table ──
    print("═" * 78)
    print("AGGREGATE METRICS")
    print("═" * 78)
    print(f"  corpus: {summary['corpus_size']:,} triples   "
          f"queries: {summary['n_queries']}   "
          f"dim={summary['dim']} k={summary['k']}")
    print()
    print(f"                   Tier-1 Atomic     Baseline Shattered     Δ (pp)")
    print(f"  Hit@1               {summary['tier1']['hit@1']:>6.2f} %          "
          f"{summary['baseline']['hit@1']:>6.2f} %          "
          f"{summary['delta_hit@1_pp']:+.2f}")
    print(f"  Hit@5               {summary['tier1']['hit@5']:>6.2f} %          "
          f"{summary['baseline']['hit@5']:>6.2f} %          "
          f"{summary['delta_hit@5_pp']:+.2f}")
    print(f"  Hit@10              {summary['tier1']['hit@10']:>6.2f} %          "
          f"{summary['baseline']['hit@10']:>6.2f} %")
    print(f"  MRR                 {summary['tier1']['mrr']:>6.4f}           "
          f"{summary['baseline']['mrr']:>6.4f}")
    print(f"  p50 latency         {summary['tier1']['p50_ms']:>6.2f} ms        "
          f"{summary['baseline']['p50_ms']:>6.2f} ms")
    print(f"  p85 latency         {summary['tier1']['p85_ms']:>6.2f} ms        "
          f"{summary['baseline']['p85_ms']:>6.2f} ms")
    print(f"  mean latency        {summary['tier1']['mean_ms']:>6.2f} ms        "
          f"{summary['baseline']['mean_ms']:>6.2f} ms")
    print("═" * 78)

    # ── Print per-query sample ──
    n_rows = min(args.verbose_rows, len(per_query_rows))
    print(f"\nPER-QUERY SAMPLE (first {n_rows} of {len(per_query_rows)} — full CSV on disk)")
    print("─" * 78)
    hdr = f"{'#':>3}  {'subject':<22} {'relation':<22}  T1  Base"
    print(hdr)
    print("─" * 78)
    for row in per_query_rows[:n_rows]:
        rank_t1 = row["t1_rank"] if row["t1_rank"] > 0 else "—"
        rank_b = row["b_rank"] if row["b_rank"] > 0 else "—"
        print(f"{row['q_idx']:>3}  "
              f"{row['subject'][:22]:<22} "
              f"{row['relation'][:22]:<22} "
              f"{str(rank_t1):>3} {str(rank_b):>4}")
    print("─" * 78)

    return 0


if __name__ == "__main__":
    sys.exit(main())
