"""v13.1 generalized (D, k) sweep tool.

Takes any JSONL corpus + any JSONL query set, runs a dimension sweep
through StructuralPipelineV13, reports Hit@1/Hit@5/Hit@10/MRR and
p50/p95/max latency per D.

Corpus format (JSONL, one record per line):
    {"doc_id": int, "text": "string to ingest", ...}

Query format (JSONL):
    {"query_text": "string", "gold_ids": [doc_id, ...]}

Encoder modes:
  - `structural_text`: plain text ingest via StructuralPipelineV13
    (Hebbian on by default, remove_punct on, use_stemming on).
  - `sro_tier1`: SRO-key contract — corpus has subject/relation/object,
    ingest text = "subject relation" (key), gold = doc_id.

Examples:

    # Social media sweep on edge-shape corpus + 25 hand-crafted queries
    python -m decode13.benchmark.v13_dk_sweep \
        --source OUT/calibration_corpus.jsonl \
        --queries OUT/calibration_queries.jsonl \
        --encoder structural_text \
        --grid 4096,8192,16384,32768

    # SRO-Tier-1 sweep on a triples corpus
    python -m decode13.benchmark.v13_dk_sweep \
        --source corpus.jsonl \
        --queries queries.jsonl \
        --encoder sro_tier1
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent))

for _d in (2, 3, 4):
    _p = _HERE.parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc  # noqa: E402

from decode13 import (  # noqa: E402
    build_structural_config, build_sro_tier1_config,
    sro_tier1_encode_text, sro_tier1_query_text,
)


def parse_args():
    p = argparse.ArgumentParser(
        prog="v13_dk_sweep",
        description="Generalized D/k sweep for v13.1 retrieval.")
    p.add_argument("--source", required=True,
                   help="Path to corpus JSONL (one record per line).")
    p.add_argument("--queries", required=True,
                   help="Path to query JSONL "
                        "({query_text, gold_ids: [int]}).")
    p.add_argument("--encoder", default="structural_text",
                   choices=["structural_text", "sro_tier1"],
                   help="Encoding contract to test.")
    p.add_argument("--grid", default="4096,8192,16384,32768",
                   help="Comma-separated D values.")
    p.add_argument("--k-strategy", default="sqrt_d",
                   choices=["sqrt_d"],
                   help="k = √D (currently the only option).")
    p.add_argument("--max-records", type=int, default=0,
                   help="Cap corpus size. 0 = all.")
    p.add_argument("--n-queries", type=int, default=0,
                   help="Cap query count. 0 = all.")
    p.add_argument("--warmup", type=int, default=20,
                   help="Throwaway queries before measurement.")
    p.add_argument("--workers", type=int, default=12,
                   help="Ingest thread count.")
    p.add_argument("--query-threads", type=int, default=12,
                   help="Query thread count.")
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--out-json", default=None,
                   help="Optional JSON path for machine-readable summary.")
    return p.parse_args()


def _k_for(dim: int, strategy: str) -> int:
    if strategy == "sqrt_d":
        return max(1, int(round(math.sqrt(dim))))
    raise ValueError(f"unknown k-strategy: {strategy}")


def _load_corpus(path: str, max_records: int):
    """Streaming-friendly load: returns list of (doc_id, ingest_text, record)."""
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            out.append(rec)
            if max_records and len(out) >= max_records:
                break
    return out


def _load_queries(path: str, max_queries: int):
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if "gold_ids" not in obj and "gold_id" in obj:
                obj["gold_ids"] = [int(obj["gold_id"])]
            out.append(obj)
            if max_queries and len(out) >= max_queries:
                break
    return out


def _ingest_text_for(rec: dict, mode: str) -> Tuple[str, int]:
    """Return (ingest_text, doc_id) for a record under the chosen mode."""
    doc_id = int(rec.get("doc_id", rec.get("id", -1)))
    if mode == "sro_tier1":
        s = rec.get("subject", "") or ""
        r = rec.get("relation", "") or ""
        return sro_tier1_encode_text(s, r), doc_id
    # structural_text
    return rec.get("text", "") or "", doc_id


def _build_cfg(mode: str, dim: int, k: int):
    if mode == "sro_tier1":
        return build_sro_tier1_config(dim=dim, k=k)
    return build_structural_config(dim=dim, k=k,
                                    max_slots=24,
                                    enable_bigram=True,
                                    enable_kv=True,
                                    enable_hebbian=True,
                                    hebbian_window=5)


def _query_text_for(q: dict, mode: str) -> str:
    if mode == "sro_tier1":
        return sro_tier1_query_text(q.get("subject", "") or q.get("query_text", ""),
                                     q.get("relation", ""))
    return q.get("query_text", "")


def _recall_rank(hit_ids: List[int], gold_ids: List[int]) -> int:
    """1-based rank of the FIRST gold-id in hit_ids, or 0 if none present."""
    gold_set = set(int(g) for g in gold_ids)
    for i, h in enumerate(hit_ids, 1):
        if int(h) in gold_set:
            return i
    return 0


def _pct(xs, p):
    try:
        return statistics.quantiles(xs, n=100)[p - 1]
    except Exception:
        return max(xs) if xs else 0.0


def run_config(corpus, queries, warmup_qs, mode, dim, k,
               workers, query_threads, top_k):
    cfg = _build_cfg(mode, dim, k)
    pipe = ehc.StructuralPipelineV13(cfg)

    # Ingest
    t0 = time.perf_counter()
    BATCH = 10_000
    tx, ix = [], []
    for rec in corpus:
        text, did = _ingest_text_for(rec, mode)
        if not text:
            continue
        tx.append(text)
        ix.append(did)
        if len(tx) >= BATCH:
            pipe.ingest_batch_parallel(tx, ix, workers); tx.clear(); ix.clear()
    if tx:
        pipe.ingest_batch_parallel(tx, ix, workers)
    t_ingest = time.perf_counter() - t0

    # Warmup
    with ThreadPoolExecutor(max_workers=query_threads) as ex:
        list(ex.map(lambda q: pipe.query_text(_query_text_for(q, mode), top_k),
                    warmup_qs))

    # Bench
    latencies = [0.0] * len(queries)
    ranks = [0] * len(queries)

    def _bench(item):
        i, q = item
        qt = _query_text_for(q, mode)
        ta = time.perf_counter()
        res = pipe.query_text(qt, top_k)
        lat = (time.perf_counter() - ta) * 1000.0
        return i, _recall_rank(list(res.ids), q.get("gold_ids", [])), lat

    t_q = time.perf_counter()
    with ThreadPoolExecutor(max_workers=query_threads) as ex:
        for i, rank, lat in ex.map(_bench, list(enumerate(queries))):
            ranks[i] = rank
            latencies[i] = lat
    t_bench = time.perf_counter() - t_q

    n = len(queries)
    hit1 = sum(1 for r in ranks if r == 1)
    hit5 = sum(1 for r in ranks if 1 <= r <= 5)
    hit10 = sum(1 for r in ranks if 1 <= r <= 10)
    mrr = sum((1.0 / r) for r in ranks if r > 0) / n if n else 0.0

    result = {
        "dim": dim, "k": k,
        "ingest_s": round(t_ingest, 1),
        "ingest_rate": round(len(corpus) / t_ingest, 0) if t_ingest else 0,
        "bench_s": round(t_bench, 2),
        "Hit@1": round(100 * hit1 / n, 2) if n else 0,
        "Hit@5": round(100 * hit5 / n, 2) if n else 0,
        "Hit@10": round(100 * hit10 / n, 2) if n else 0,
        "MRR": round(mrr, 4),
        "p50_ms": round(statistics.median(latencies), 2) if latencies else 0,
        "p95_ms": round(_pct(latencies, 95), 2) if latencies else 0,
        "max_ms": round(max(latencies), 2) if latencies else 0,
    }

    del pipe
    gc.collect()
    return result


def main():
    args = parse_args()
    grid = [int(x) for x in args.grid.split(",")]
    print(f"=== v13.1 D/k sweep ===", flush=True)
    print(f"  encoder       : {args.encoder}", flush=True)
    print(f"  source        : {args.source}", flush=True)
    print(f"  queries       : {args.queries}", flush=True)
    print(f"  grid          : {grid} (k = √D)", flush=True)
    print(f"  workers       : {args.workers}", flush=True)

    t = time.perf_counter()
    corpus = _load_corpus(args.source, args.max_records)
    # Load all queries unless capped explicitly. n_queries=0 means "use
    # as many as are in the file after carving out warmup_qs."
    hard_cap = (args.n_queries + args.warmup) if args.n_queries else 0
    queries_all = _load_queries(args.queries, hard_cap)
    if args.n_queries:
        queries = queries_all[:args.n_queries]
        warmup_qs = queries_all[args.n_queries:args.n_queries + args.warmup]
    else:
        warmup_qs = queries_all[:args.warmup]
        queries = queries_all[args.warmup:]
    # Fallback: if not enough queries to carve a distinct warmup set, reuse.
    if len(warmup_qs) < args.warmup and queries:
        warmup_qs = queries[:args.warmup]
    print(f"  loaded {len(corpus):,} records + {len(queries)} queries "
          f"(+{len(warmup_qs)} warmup) in {time.perf_counter()-t:.1f}s\n",
          flush=True)

    # Sweep
    results = []
    for dim in grid:
        k = _k_for(dim, args.k_strategy)
        print(f"── D={dim}, k={k} ──", flush=True)
        r = run_config(corpus, queries, warmup_qs, args.encoder,
                       dim, k, args.workers, args.query_threads, args.top_k)
        print(f"   ingest={r['ingest_s']}s ({r['ingest_rate']:,.0f}/s)  "
              f"Hit@1={r['Hit@1']}%  Hit@10={r['Hit@10']}%  "
              f"p50={r['p50_ms']}ms  p95={r['p95_ms']}ms",
              flush=True)
        results.append(r)

    # Table
    print(f"\n{'─' * 90}", flush=True)
    print(f"  {'D':>5}  {'k':>4}  {'ingest/s':>10}  {'Hit@1':>7}  "
          f"{'Hit@5':>7}  {'Hit@10':>7}  {'MRR':>7}  "
          f"{'p50 ms':>8}  {'p95 ms':>8}", flush=True)
    for r in results:
        print(f"  {r['dim']:>5}  {r['k']:>4}  {r['ingest_rate']:>10,.0f}  "
              f"{r['Hit@1']:>6.2f}%  {r['Hit@5']:>6.2f}%  "
              f"{r['Hit@10']:>6.2f}%  {r['MRR']:>7.4f}  "
              f"{r['p50_ms']:>7.2f}  {r['p95_ms']:>7.2f}", flush=True)
    print(f"{'─' * 90}", flush=True)

    if args.out_json:
        with open(args.out_json, "w") as f:
            json.dump({
                "encoder": args.encoder,
                "source": args.source,
                "queries": args.queries,
                "corpus_size": len(corpus),
                "n_queries": len(queries),
                "n_warmup": len(warmup_qs),
                "grid": grid,
                "results": results,
            }, f, indent=2)
        print(f"\nfull results: {args.out_json}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
