"""Path A: (hash_size × num_tables) sweep on 5M Wikidata.

Purpose is not to ship — it's to validate the LSH-tuning math and
surface whether there's ANY (hash_size, num_tables) config that
delivers both acceptable Hit@1 AND sub-second latency at the current
Tier-1 query-vs-gold cosine regime (~0.7). If no corner of the space
delivers both, that's direct evidence Path B (strict-subspace query
construction) is required, not optional.

Flow:
  1. Load 5M triples once.
  2. parallel_encode_tier1 with retain_vectors=True → TierEncoder with
     BSCCompactIndex + one (default) BSCLSHIndex.
  3. For each (hash_size, num_tables) config, build a fresh
     BSCLSHIndex from the retained vectors, plug into enc._lsh, run
     20 warmup + 200 measured queries via QueryService13, record
     Hit@{1,5,10}/MRR/p50/p95.
  4. Print a table.

Retained vector memory: ~4 GB at 5M — fits.
"""

from __future__ import annotations

import gc
import random
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent))

for _d in (2, 3, 4):
    _p = _HERE.parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc  # noqa: E402

from decode13.benchmark.run_wikidata import TRIPLES_PATH, _load_sample, _sample_queries  # noqa: E402
from decode13.benchmark.parallel_encode import parallel_encode_tier1  # noqa: E402
from decode13.tier_query import QueryService13  # noqa: E402


HASH_SIZES = (6, 8, 10, 12)
NUM_TABLES = (16, 32, 64)

N_TRIPLES = 5_000_000
N_QUERIES = 200
N_WARMUP = 20
DIM = 8192
K = 90
SEED = 42
TOP_K = 10


def _rank_of(results: list, gold_id: int) -> int:
    for i, r in enumerate(results, start=1):
        if r["source_record_id"] == gold_id:
            return i
    return 0


def run_config(enc, warmup_qs, bench_qs, hash_size: int, num_tables: int,
               query_threads: int = 12) -> dict:
    """Build a fresh LSH, plug it into enc, run warmup + bench."""
    t0 = time.perf_counter()
    new_lsh = ehc.BSCLSHIndex(DIM, K,
                              num_tables=num_tables,
                              hash_size=hash_size,
                              use_multiprobe=True)
    new_lsh.add_items(enc._retained_vecs, enc._retained_ids)
    t_build = time.perf_counter() - t0

    # Swap in the new LSH.
    enc._lsh = new_lsh
    svc = QueryService13(enc)

    # Warmup
    t_warm = time.perf_counter()
    with ThreadPoolExecutor(max_workers=query_threads) as ex:
        def _warm_one(q):
            _, s, r, _o = q
            svc.query(subject=s, relation=r, k=TOP_K, explicit_sro=True)
        list(ex.map(_warm_one, warmup_qs))
    warm_time = time.perf_counter() - t_warm

    # Benchmark — measure per-query latency per thread.
    ranks: List[int] = [0] * len(bench_qs)
    latencies: List[float] = [0.0] * len(bench_qs)

    def _bench_one(item):
        i, (rid, s, r, _o) = item
        t_a = time.perf_counter()
        res = svc.query(subject=s, relation=r, k=TOP_K, explicit_sro=True)
        lat = (time.perf_counter() - t_a) * 1000.0
        rank = _rank_of(res["results"], rid)
        return i, rank, lat

    t_bench = time.perf_counter()
    with ThreadPoolExecutor(max_workers=query_threads) as ex:
        for i, rank, lat in ex.map(_bench_one, list(enumerate(bench_qs))):
            ranks[i] = rank
            latencies[i] = lat
    bench_time = time.perf_counter() - t_bench

    n = len(bench_qs)
    hit1 = sum(1 for r in ranks if r == 1)
    hit5 = sum(1 for r in ranks if 1 <= r <= 5)
    hit10 = sum(1 for r in ranks if 1 <= r <= 10)
    mrr = sum((1.0 / r) for r in ranks if r > 0) / n

    def _pct(v):
        try:
            return statistics.quantiles(latencies, n=100)[v - 1]
        except Exception:
            return max(latencies)

    return {
        "hash_size": hash_size,
        "num_tables": num_tables,
        "build_s": round(t_build, 1),
        "warm_s": round(warm_time, 2),
        "bench_s": round(bench_time, 2),
        "Hit@1": round(100.0 * hit1 / n, 2),
        "Hit@5": round(100.0 * hit5 / n, 2),
        "Hit@10": round(100.0 * hit10 / n, 2),
        "MRR": round(mrr, 4),
        "p50_ms": round(statistics.median(latencies), 2),
        "p95_ms": round(_pct(95), 2),
        "max_ms": round(max(latencies), 2),
    }


def main():
    print(f"=== Path A sweep: {N_TRIPLES:,} triples, {N_QUERIES} queries, "
          f"{N_WARMUP} warmup ===", flush=True)
    print(f"=== dim={DIM} k={K} grid=({len(HASH_SIZES)} × {len(NUM_TABLES)}) "
          f"= {len(HASH_SIZES) * len(NUM_TABLES)} configs ===\n", flush=True)

    # Load triples + sample queries ONCE.
    t0 = time.perf_counter()
    triples = _load_sample(TRIPLES_PATH, N_TRIPLES, SEED)
    print(f"loaded {len(triples):,} in {time.perf_counter()-t0:.1f}s",
          flush=True)

    all_qs = _sample_queries(triples, N_QUERIES + N_WARMUP, SEED + 1)
    bench_qs = all_qs[:N_QUERIES]
    warmup_qs = all_qs[N_QUERIES:N_QUERIES + N_WARMUP]
    print(f"sampled {len(bench_qs)} benchmark + {len(warmup_qs)} warmup queries\n",
          flush=True)

    # Encode once with retained vectors.
    print(f"=== encoding Tier-1 once (with retained vectors) ===", flush=True)
    t0 = time.perf_counter()
    enc = parallel_encode_tier1(
        triples, dim=DIM, k=K, seed=SEED,
        n_workers=12, retain_vectors=True,
    )
    print(f"encoded {enc.n_vectors:,} in {time.perf_counter()-t0:.1f}s "
          f"(retained {len(enc._retained_vecs):,} vectors in memory)",
          flush=True)

    # Free the source triple list — encode is done, queries are sampled.
    del triples
    gc.collect()
    print(flush=True)

    # Sweep.
    results: List[dict] = []
    for hs in HASH_SIZES:
        for nt in NUM_TABLES:
            print(f"--- config hash_size={hs} num_tables={nt} ---", flush=True)
            r = run_config(enc, warmup_qs, bench_qs, hs, nt)
            print(f"    Hit@1={r['Hit@1']}%  Hit@10={r['Hit@10']}%  "
                  f"MRR={r['MRR']}  p50={r['p50_ms']}ms  p95={r['p95_ms']}ms  "
                  f"build={r['build_s']}s",
                  flush=True)
            results.append(r)

    # Final table.
    print("\n" + "=" * 100, flush=True)
    print(f"  {'hs':>3}  {'tbl':>3}  {'Hit@1':>7}  {'Hit@5':>7}  "
          f"{'Hit@10':>7}  {'MRR':>7}  {'p50 ms':>8}  {'p95 ms':>8}  "
          f"{'build s':>8}", flush=True)
    print("-" * 100, flush=True)
    for r in results:
        print(f"  {r['hash_size']:>3}  {r['num_tables']:>3}  "
              f"{r['Hit@1']:>6.2f}%  {r['Hit@5']:>6.2f}%  "
              f"{r['Hit@10']:>6.2f}%  {r['MRR']:>7.4f}  "
              f"{r['p50_ms']:>7.2f}  {r['p95_ms']:>7.2f}  "
              f"{r['build_s']:>7.1f}",
              flush=True)
    print("=" * 100, flush=True)

    # Write JSON for machine reading.
    import json
    out_path = Path("/Users/stark/Quantum_Computing_Lab/OUT-WIKI/path_a_sweep.json")
    with open(out_path, "w") as f:
        json.dump({
            "n_triples": N_TRIPLES,
            "n_queries": N_QUERIES,
            "n_warmup": N_WARMUP,
            "dim": DIM,
            "k": K,
            "results": results,
        }, f, indent=2)
    print(f"\nfull results: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
