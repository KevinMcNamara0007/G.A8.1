"""run.py — unified benchmark runner.

Loads an encoded shard via the production decode/query.py shim, runs a
query JSONL set with warmup, reports metrics via metrics.py.

WHEN TO USE
===========
You have an encoded corpus (output of `encode_triples` or
`encode_unstructured`) and a query set with known gold ids. You want
Hit@1/Hit@5/Hit@10/MRR/p50/p95 reported.

EXPECTED INPUTS
===============
  - --index-path : directory containing structural_v13/ + corpus.jsonl
                   (the same A81_INDEX_PATH the edge service consumes)
  - --queries    : JSONL, one query per line:
                   {"query_text": "...", "gold_ids": [int, ...]}

USAGE
=====
    python -m decode13.benchmark.run \
        --index-path /path/to/encoded_dir \
        --queries /path/to/queries.jsonl \
        --warmup 20

For Tier-1 SRO benchmarks where gold is the source record id, the
shape is identical — just supply queries with `gold_ids: [doc_id]`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent))      # G.A8.1 root
sys.path.insert(0, str(_HERE.parent.parent / "decode"))

from decode13.benchmark.metrics import aggregate  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(
        prog="benchmark.run",
        description="Run query benchmark against an encoded shard.",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--index-path", required=True,
                   help="Encoded shard directory (structural_v13/ + corpus.jsonl).")
    p.add_argument("--queries", required=True,
                   help="Query JSONL: {query_text, gold_ids: [int]}.")
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--warmup", type=int, default=20,
                   help="Throwaway queries before measurement.")
    p.add_argument("--threads", type=int, default=12,
                   help="Concurrent query threads.")
    p.add_argument("--out-json", default=None,
                   help="Optional path to write summary JSON.")
    return p.parse_args()


def _rank_of_first_gold(hit_ids: List[int], gold_ids: List[int]) -> int:
    gset = set(int(g) for g in gold_ids)
    for i, h in enumerate(hit_ids, start=1):
        if int(h) in gset:
            return i
    return 0


def main():
    args = parse_args()

    # Import the shim — single decode entry point.
    from query import QueryService  # noqa: E402
    print(f"[load] {args.index_path}", flush=True)
    t0 = time.perf_counter()
    svc = QueryService(args.index_path)
    print(f"[load] done in {time.perf_counter()-t0:.2f}s  stats={svc.stats}",
          flush=True)

    # Read query set
    queries = []
    with open(args.queries) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            queries.append(json.loads(line))
    if not queries:
        print("ERROR: no queries loaded", file=sys.stderr)
        return 2
    print(f"[queries] loaded {len(queries)} queries", flush=True)

    # Warmup
    warm = queries[: max(0, args.warmup)]
    if warm:
        t = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.threads) as ex:
            list(ex.map(lambda q: svc.query(q["query_text"], k=args.top_k),
                         warm))
        print(f"[warmup] {len(warm)} queries in "
              f"{time.perf_counter()-t:.2f}s", flush=True)

    # Bench
    ranks = [0] * len(queries)
    lats = [0.0] * len(queries)

    def _bench(item):
        i, q = item
        ta = time.perf_counter()
        res = svc.query(q["query_text"], k=args.top_k)
        lat = (time.perf_counter() - ta) * 1000.0
        ids = []
        for h in res.get("results", []):
            try:
                ids.append(int(h.get("id", -1)))
            except Exception:
                pass
        return i, _rank_of_first_gold(ids, q.get("gold_ids", [])), lat

    t = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        for i, rank, lat in ex.map(_bench, list(enumerate(queries))):
            ranks[i] = rank
            lats[i] = lat
    bench_t = time.perf_counter() - t

    metrics = aggregate(ranks, lats)
    metrics["bench_seconds"] = round(bench_t, 2)
    metrics["qps"] = round(len(queries) / bench_t, 1) if bench_t else 0

    print(f"\n{'=' * 60}", flush=True)
    print(f"{'BENCHMARK RESULT':^60}", flush=True)
    print(f"{'=' * 60}", flush=True)
    for kk, vv in metrics.items():
        print(f"  {kk:<14} : {vv}", flush=True)
    print(f"{'=' * 60}", flush=True)

    if args.out_json:
        with open(args.out_json, "w") as f:
            json.dump({
                "index_path": args.index_path,
                "queries":    args.queries,
                "metrics":    metrics,
            }, f, indent=2)
        print(f"[write] {args.out_json}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
