"""Benchmark the production sharded pipeline — tier-routed vs baseline.

Runs the 500-query protocol against TWO shard directories produced by
G.A8.1 encode/encode.py:

  1. A81_TIER_ROUTED=1  — tier-routed atomic encoding (v13)
  2. A81_TIER_ROUTED=0 + A81_CLOSED_LOOP=1  — shattered canonical (v12.5 Phase 1)

Queries go through decode13.QueryService — the v13 shard-aware query
service (native tier awareness, per-shard TierManifest compat, tier
weighting). Same service handles both corpora; the baseline shards just
don't carry tier_manifest.json so the service treats them as
tier-agnostic (legacy) shards with equal weighting.

Per-query output:
  q_idx, subject, relation, gold_object,
  tier_rank, tier_top_text, tier_score, tier_latency_ms,
  base_rank, base_top_text, base_score, base_latency_ms
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))


def _load_sample(source_path: str, n: int) -> List[dict]:
    """Stream the first N triples from the source JSON array."""
    from decode13.benchmark.triples_reader import stream_triples
    out = []
    for i, t in enumerate(stream_triples(source_path, limit=n)):
        out.append(t)
        if len(out) >= n:
            break
    return out


def _sample_queries(
    triples: List[dict],
    n_queries: int,
    seed: int,
) -> List[Tuple[int, str, str, str]]:
    """Unique-(s, r) sampling so each query has a single gold record."""
    sr_count: Counter = Counter()
    for rec in triples:
        sr_count[(rec.get("subject", ""), rec.get("relation", ""))] += 1
    unique_sr = {k for k, v in sr_count.items() if v == 1}
    candidates: List[Tuple[int, str, str, str]] = []
    for i, rec in enumerate(triples):
        key = (rec.get("subject", ""), rec.get("relation", ""))
        if key in unique_sr:
            candidates.append(
                (i, rec.get("subject", ""),
                 rec.get("relation", ""), rec.get("object", ""))
            )
    rng = random.Random(seed)
    rng.shuffle(candidates)
    return candidates[:n_queries]


def _build_service(shard_dir: str, dim: int, k: int):
    """Construct a decode13 QueryService against a shard directory.

    The service auto-detects tier_manifest.json presence per-shard; no
    env flag needed. A shard directory with tier manifests gets native
    tier-aware retrieval; one without (the baseline/closed-loop encode)
    is treated as tier-agnostic (weight 1.0 on all hits)."""
    from decode13.query_service import QueryService as QS13
    return QS13(shard_dir, dim=dim, k=k)


def _rank_in_results(results: list, gold_text: str) -> Tuple[int, str, float]:
    """Find rank of the gold triple in the decode13 result list.

    decode13.QueryService emits a flat dict per hit with `text` and
    `raw_score` keys. Returns (rank, matched_text, score) or
    (0, top_text, top_score) on miss.
    """
    gt = gold_text.lower().strip()
    top_text = ""
    top_score = 0.0
    for i, r in enumerate(results, start=1):
        text = r.get("text", "") or ""
        txt = text.lower().strip()
        if i == 1:
            top_text = text
            top_score = float(r.get("raw_score", 0.0) or 0.0)
        if txt == gt:
            return i, text, float(r.get("raw_score", 0.0) or 0.0)
    return 0, top_text, top_score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True,
                    help="Path to triples JSON (the corpus)")
    ap.add_argument("--tier-dir", required=True,
                    help="Shard output dir for tier-routed encode")
    ap.add_argument("--base-dir", required=True,
                    help="Shard output dir for baseline (closed-loop) encode")
    ap.add_argument("--n-triples", type=int, default=100_000,
                    help="How many source triples the shards contain "
                         "(used to sample queries)")
    ap.add_argument("--n-queries", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--n-shards", type=int, default=0,
                    help="Shards to probe per query (0 = all)")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--query-threads", type=int, default=8)
    ap.add_argument("--out-dir", type=str,
                    default=str(_ROOT / "decode13" / "benchmark" / "out"))
    ap.add_argument("--verbose-rows", type=int, default=30)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"── Loading {args.n_triples:,} triples for query sampling ──")
    t0 = time.perf_counter()
    triples = _load_sample(args.source, args.n_triples)
    print(f"  loaded {len(triples):,} in {time.perf_counter()-t0:.1f}s")
    queries = _sample_queries(triples, args.n_queries, args.seed + 1)
    # Build the gold sidecar text the same way encode.py does for structured
    # triples (f"{s} {r} {o}") so rank-check matches sidecar records.
    # Key by *enumeration index* (not record_id) so the ThreadPool's
    # enumerate(queries) index matches.
    gold_texts = {
        qidx: f"{s} {r} {o}"
        for qidx, (_rid, s, r, o) in enumerate(queries)
    }
    print(f"  sampled {len(queries)} unique-(s,r) queries")
    del triples

    # Resolve dim/k from config env for both services.
    _dim = int(os.environ.get("A81_DIM", "16384"))
    _k = int(os.environ.get("A81_K", str(int(math.sqrt(_dim)))))

    # ── Load tier-routed service ──
    print(f"\n── Loading tier-routed shards from {args.tier_dir} ──")
    tier_svc = _build_service(args.tier_dir, dim=_dim, k=_k)

    n_shards_total = len(tier_svc.shards)
    probe_n = args.n_shards or n_shards_total
    print(f"  shards loaded: {n_shards_total}  probe_n_per_query: {probe_n}")

    # ── Load baseline service ──
    print(f"\n── Loading baseline shards from {args.base_dir} ──")
    base_svc = _build_service(args.base_dir, dim=_dim, k=_k)

    # ── Queries ──
    print(f"\n── Running {len(queries)} queries (threads={args.query_threads}) ──")

    def run_one(item):
        idx, (rid, s, r, o) = item
        query_text = f"{s} {r}"  # atomic compound query
        gold_text = gold_texts[idx]

        t_a = time.perf_counter()
        rtier = tier_svc.query(query_text, k=args.top_k, n_shards=probe_n)
        lat_t = (time.perf_counter() - t_a) * 1000.0
        tier_rank, tier_top_text, tier_top_score = _rank_in_results(
            rtier.get("results", []), gold_text)

        t_a = time.perf_counter()
        rbase = base_svc.query(query_text, k=args.top_k, n_shards=probe_n)
        lat_b = (time.perf_counter() - t_a) * 1000.0
        base_rank, base_top_text, base_top_score = _rank_in_results(
            rbase.get("results", []), gold_text)

        return {
            "q_idx": idx,
            "subject": s, "relation": r, "gold_object": o,
            "tier_rank": tier_rank,
            "tier_top_text": tier_top_text[:80],
            "tier_top_score": round(tier_top_score, 4),
            "tier_latency_ms": round(lat_t, 2),
            "base_rank": base_rank,
            "base_top_text": base_top_text[:80],
            "base_top_score": round(base_top_score, 4),
            "base_latency_ms": round(lat_b, 2),
        }

    t_qstart = time.perf_counter()
    rows: List[dict] = [None] * len(queries)
    with ThreadPoolExecutor(max_workers=args.query_threads) as ex:
        for row in ex.map(run_one, list(enumerate(queries))):
            rows[row["q_idx"]] = row
    print(f"  queries done in {time.perf_counter()-t_qstart:.1f}s")

    # ── Aggregate ──
    n = len(rows)
    t_lat = [r["tier_latency_ms"] for r in rows]
    b_lat = [r["base_latency_ms"] for r in rows]
    t_hit1 = sum(1 for r in rows if r["tier_rank"] == 1)
    t_hit5 = sum(1 for r in rows if 1 <= r["tier_rank"] <= 5)
    t_hit10 = sum(1 for r in rows if 1 <= r["tier_rank"] <= 10)
    t_mrr = sum(1.0 / r["tier_rank"] for r in rows if r["tier_rank"] > 0) / n
    b_hit1 = sum(1 for r in rows if r["base_rank"] == 1)
    b_hit5 = sum(1 for r in rows if 1 <= r["base_rank"] <= 5)
    b_hit10 = sum(1 for r in rows if 1 <= r["base_rank"] <= 10)
    b_mrr = sum(1.0 / r["base_rank"] for r in rows if r["base_rank"] > 0) / n

    def _pct(x): return round(100.0 * x / n, 2)

    p85_t = statistics.quantiles(t_lat, n=100)[84] if n >= 100 else max(t_lat)
    p85_b = statistics.quantiles(b_lat, n=100)[84] if n >= 100 else max(b_lat)

    summary = {
        "corpus_size": args.n_triples,
        "n_queries": n,
        "n_shards_total": n_shards_total,
        "n_shards_probed": probe_n,
        "tier": {
            "hit@1": _pct(t_hit1), "hit@5": _pct(t_hit5), "hit@10": _pct(t_hit10),
            "mrr": round(t_mrr, 4),
            "p50_ms": round(statistics.median(t_lat), 2),
            "p85_ms": round(p85_t, 2),
            "mean_ms": round(statistics.mean(t_lat), 2),
        },
        "baseline": {
            "hit@1": _pct(b_hit1), "hit@5": _pct(b_hit5), "hit@10": _pct(b_hit10),
            "mrr": round(b_mrr, 4),
            "p50_ms": round(statistics.median(b_lat), 2),
            "p85_ms": round(p85_b, 2),
            "mean_ms": round(statistics.mean(b_lat), 2),
        },
    }
    summary["delta_hit@1_pp"] = round(
        summary["tier"]["hit@1"] - summary["baseline"]["hit@1"], 2)
    summary["delta_hit@5_pp"] = round(
        summary["tier"]["hit@5"] - summary["baseline"]["hit@5"], 2)

    csv_path = out_dir / f"prod_per_query_{args.n_triples}_{n}.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    summary_path = out_dir / f"prod_summary_{args.n_triples}_{n}.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"per-query CSV: {csv_path}")
    print(f"summary JSON: {summary_path}\n")

    print("═" * 78)
    print("AGGREGATE METRICS — production sharded pipeline")
    print("═" * 78)
    print(f"  corpus: {summary['corpus_size']:,}   queries: {n}   "
          f"shards={n_shards_total} probe={probe_n}")
    print()
    print(f"                Tier-Routed Atomic   Baseline Closed-Loop   Δ (pp)")
    print(f"  Hit@1         {summary['tier']['hit@1']:>7.2f} %            "
          f"{summary['baseline']['hit@1']:>7.2f} %            "
          f"{summary['delta_hit@1_pp']:+.2f}")
    print(f"  Hit@5         {summary['tier']['hit@5']:>7.2f} %            "
          f"{summary['baseline']['hit@5']:>7.2f} %            "
          f"{summary['delta_hit@5_pp']:+.2f}")
    print(f"  Hit@10        {summary['tier']['hit@10']:>7.2f} %            "
          f"{summary['baseline']['hit@10']:>7.2f} %")
    print(f"  MRR           {summary['tier']['mrr']:>7.4f}              "
          f"{summary['baseline']['mrr']:>7.4f}")
    print(f"  p50 latency   {summary['tier']['p50_ms']:>7.2f} ms          "
          f"{summary['baseline']['p50_ms']:>7.2f} ms")
    print(f"  p85 latency   {summary['tier']['p85_ms']:>7.2f} ms          "
          f"{summary['baseline']['p85_ms']:>7.2f} ms")
    print("═" * 78)

    # Per-query sample
    nrows = min(args.verbose_rows, n)
    print(f"\nPER-QUERY SAMPLE (first {nrows} of {n})")
    print("─" * 78)
    print(f"{'#':>3}  {'subject':<24} {'relation':<22}  Tier  Base")
    print("─" * 78)
    for row in rows[:nrows]:
        tr = row["tier_rank"] if row["tier_rank"] > 0 else "—"
        br = row["base_rank"] if row["base_rank"] > 0 else "—"
        print(f"{row['q_idx']:>3}  {row['subject'][:24]:<24} "
              f"{row['relation'][:22]:<22} {str(tr):>4}  {str(br):>4}")
    print("─" * 78)

    return 0


if __name__ == "__main__":
    sys.exit(main())
