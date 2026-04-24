"""v13.1 Tier-1 SRO prod runner — sweep → encode → bench end-to-end.

Phases:

  1. D/k sweep at 1M: {4096, 8192, 16384} × k=√D. Hit@1 should be ~100%
     across the board under the contract; pick the smallest D that
     delivers acceptable latency.
  2. Wipe OUT-WIKI. Encode full 21.3M wikidata triples via the
     production SRO Tier-1 contract (key = "s r", sidecar = full triple).
     Save pipeline to OUT-WIKI/structural_v13/ + corpus.jsonl sidecar.
  3. Load the encoded corpus via the edge-shim QueryService (the SAME
     code the edge_service uses in production). 20 warmup queries +
     500 measured. Report Hit@1, MRR, p50/p95 latency.

All three phases use:
  - StructuralPipelineV13 with decode13.build_sro_tier1_config
  - SimHash-based BSCLSHIndex (C++ fix landed)
  - Warmup pass before measurement
"""

from __future__ import annotations

import gc
import json
import math
import os
import random
import shutil
import statistics
import subprocess
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

from decode13 import (  # noqa: E402
    build_sro_tier1_config, sro_tier1_encode_text, sro_tier1_query_text,
)
from decode13.benchmark.triples_reader import stream_triples  # noqa: E402


TRIPLES_PATH = "/Users/stark/Quantum_Computing_Lab/GoldC/triples_21M.json"
OUT_DIR = Path("/Users/stark/Quantum_Computing_Lab/OUT-WIKI")
SHIM_PATH = Path("/Users/stark/Quantum_Computing_Lab/G.A8.1/decode")

SWEEP_N = 1_000_000
SWEEP_Q = 200
SWEEP_WARMUP = 20
SWEEP_CONFIGS: List[Tuple[int, int]] = [
    (4096, 64),
    (8192, 90),
    (16384, 128),
]

FULL_N = 21_354_359   # actual count in triples_21M.json
BENCH_Q = 500
BENCH_WARMUP = 20

SEED = 42
TOP_K = 10


# ═══ shared helpers ═══════════════════════════════════════════

def _load_triples(n: int, seed: int):
    out = []
    for trip in stream_triples(TRIPLES_PATH, limit=n):
        out.append({
            "subject": trip.get("subject", "") or "",
            "relation": trip.get("relation", "") or "",
            "object": trip.get("object", "") or "",
        })
    rng = random.Random(seed)
    rng.shuffle(out)
    return out


def _sample_unique_queries(triples, n, seed):
    sr_count: Counter = Counter()
    for rec in triples:
        sr_count[(rec["subject"], rec["relation"])] += 1
    unique_sr = {k for k, v in sr_count.items() if v == 1}
    cands = []
    for i, rec in enumerate(triples):
        if (rec["subject"], rec["relation"]) in unique_sr:
            cands.append((i, rec["subject"], rec["relation"], rec["object"]))
    rng = random.Random(seed)
    rng.shuffle(cands)
    return cands[:n]


def _rank_of(hit_ids, gold_id):
    for i, h in enumerate(hit_ids, 1):
        if int(h) == gold_id:
            return i
    return 0


def _pct(xs, p):
    try:
        return statistics.quantiles(xs, n=100)[p - 1]
    except Exception:
        return max(xs)


# ═══ Phase 1: D/k sweep ═══════════════════════════════════════

def phase1_sweep() -> Tuple[int, int]:
    print(f"\n{'═' * 70}", flush=True)
    print(f"{'PHASE 1 — D/k sweep at ' + f'{SWEEP_N:,}' + ' triples':^70}",
          flush=True)
    print(f"{'═' * 70}", flush=True)

    t0 = time.perf_counter()
    triples = _load_triples(SWEEP_N, SEED)
    print(f"loaded {len(triples):,} in {time.perf_counter()-t0:.1f}s",
          flush=True)

    qs = _sample_unique_queries(triples, SWEEP_Q + SWEEP_WARMUP, SEED + 1)
    bench_qs, warm_qs = qs[:SWEEP_Q], qs[SWEEP_Q:]

    results = []
    for dim, k in SWEEP_CONFIGS:
        print(f"\n── D={dim}, k={k} ──", flush=True)
        cfg = build_sro_tier1_config(dim=dim, k=k)
        pipe = ehc.StructuralPipelineV13(cfg)

        # Ingest
        t_i = time.perf_counter()
        BATCH = 10_000
        tx, ix = [], []
        for i, rec in enumerate(triples):
            tx.append(sro_tier1_encode_text(rec["subject"], rec["relation"]))
            ix.append(i)
            if len(tx) >= BATCH:
                pipe.ingest_batch_parallel(tx, ix, 12); tx.clear(); ix.clear()
        if tx:
            pipe.ingest_batch_parallel(tx, ix, 12)
        t_ingest = time.perf_counter() - t_i

        # Warmup
        with ThreadPoolExecutor(max_workers=12) as ex:
            list(ex.map(lambda q: pipe.query_text(
                sro_tier1_query_text(q[1], q[2]), TOP_K), warm_qs))

        # Bench
        t_b = time.perf_counter()
        ranks, lats = [0]*len(bench_qs), [0.0]*len(bench_qs)
        def _bench(item):
            i, (rid, s, r, _o) = item
            ta = time.perf_counter()
            res = pipe.query_text(sro_tier1_query_text(s, r), TOP_K)
            return i, _rank_of(list(res.ids), rid), (time.perf_counter()-ta)*1000.0
        with ThreadPoolExecutor(max_workers=12) as ex:
            for i, rank, lat in ex.map(_bench, list(enumerate(bench_qs))):
                ranks[i] = rank; lats[i] = lat
        t_bench = time.perf_counter() - t_b

        n = len(bench_qs)
        hit1 = sum(1 for r in ranks if r == 1)
        h10 = sum(1 for r in ranks if 1 <= r <= 10)
        row = {
            "dim": dim, "k": k,
            "ingest_s": round(t_ingest, 1),
            "ingest_rate": round(SWEEP_N/t_ingest, 0),
            "bench_s": round(t_bench, 2),
            "Hit@1": round(100*hit1/n, 2),
            "Hit@10": round(100*h10/n, 2),
            "p50_ms": round(statistics.median(lats), 2),
            "p95_ms": round(_pct(lats, 95), 2),
        }
        print(f"   ingest={t_ingest:.1f}s ({row['ingest_rate']:,.0f}/s)  "
              f"Hit@1={row['Hit@1']}%  p50={row['p50_ms']}ms  "
              f"p95={row['p95_ms']}ms", flush=True)
        results.append(row)

        del pipe
        gc.collect()

    # Report table
    print(f"\n{'─' * 70}", flush=True)
    print(f"  {'D':>5}  {'k':>4}  {'ingest/s':>10}  {'Hit@1':>7}  "
          f"{'Hit@10':>7}  {'p50 ms':>8}  {'p95 ms':>8}", flush=True)
    for r in results:
        print(f"  {r['dim']:>5}  {r['k']:>4}  {r['ingest_rate']:>10,.0f}  "
              f"{r['Hit@1']:>6.2f}%  {r['Hit@10']:>6.2f}%  "
              f"{r['p50_ms']:>7.2f}  {r['p95_ms']:>7.2f}", flush=True)
    print(f"{'─' * 70}", flush=True)

    # Pick winner: highest Hit@1, break ties by smallest D, break by smallest p50.
    winner = sorted(results,
                    key=lambda r: (-r['Hit@1'], r['dim'], r['p50_ms']))[0]
    print(f"\n→ winner: D={winner['dim']}, k={winner['k']} "
          f"(Hit@1={winner['Hit@1']}%, p50={winner['p50_ms']}ms)",
          flush=True)
    return winner['dim'], winner['k']


# ═══ Phase 2: wipe + full encode ═══════════════════════════════

def phase2_encode_21m(dim: int, k: int):
    print(f"\n{'═' * 70}", flush=True)
    print(f"{'PHASE 2 — wipe + encode full 21.3M at D=' + str(dim) + ', k=' + str(k):^70}",
          flush=True)
    print(f"{'═' * 70}", flush=True)

    # Wipe OUT-WIKI (except keep staged files if any — but for this run
    # we want a clean dir).
    if OUT_DIR.exists():
        for item in OUT_DIR.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        print(f"wiped contents of {OUT_DIR}", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pipe_dir = OUT_DIR / "structural_v13"
    pipe_dir.mkdir(parents=True, exist_ok=True)

    # Stream + encode. We keep the sidecar in memory during encode so we
    # can emit corpus.jsonl immediately after; at 21M records × 3 strings
    # ≈ 3-4 GB resident, fits easily.
    cfg = build_sro_tier1_config(dim=dim, k=k)
    pipe = ehc.StructuralPipelineV13(cfg)

    t0 = time.perf_counter()
    BATCH = 10_000
    tx, ix = [], []
    sidecar: List[Tuple[str, str, str]] = []  # doc_id → (s, r, o)
    n = 0
    for trip in stream_triples(TRIPLES_PATH):
        s = trip.get("subject", "") or ""
        r = trip.get("relation", "") or ""
        o = trip.get("object", "") or ""
        sidecar.append((s, r, o))
        tx.append(sro_tier1_encode_text(s, r))
        ix.append(n)
        n += 1
        if len(tx) >= BATCH:
            pipe.ingest_batch_parallel(tx, ix, 12); tx.clear(); ix.clear()
            if n % 1_000_000 == 0:
                el = time.perf_counter() - t0
                print(f"  ingested {n:,} in {el:.1f}s "
                      f"({n/el:,.0f}/s)", flush=True)
    if tx:
        pipe.ingest_batch_parallel(tx, ix, 12)
    t_ingest = time.perf_counter() - t0
    print(f"\n  ingest done: {n:,} in {t_ingest:.1f}s "
          f"({n/t_ingest:,.0f}/s)", flush=True)

    # Save pipeline (shim-loadable).
    t = time.perf_counter()
    pipe.save(str(pipe_dir))
    print(f"  saved pipeline to {pipe_dir} in {time.perf_counter()-t:.1f}s",
          flush=True)

    # Save corpus.jsonl sidecar (shim reads this).
    t = time.perf_counter()
    cpath = OUT_DIR / "corpus.jsonl"
    with open(cpath, "w", encoding="utf-8") as f:
        for i, (s, r, o) in enumerate(sidecar):
            f.write(json.dumps({
                "doc_id": i,
                "text": sro_tier1_encode_text(s, r),
                "subject": s,
                "relation": r,
                "object": o,
            }, ensure_ascii=False) + "\n")
    print(f"  wrote corpus.jsonl ({n:,} rows) in {time.perf_counter()-t:.1f}s",
          flush=True)

    # Free before benchmark phase loads a fresh copy via the shim.
    del pipe, sidecar
    gc.collect()


# ═══ Phase 3: benchmark via the edge shim ═══════════════════════

def phase3_bench_via_shim():
    print(f"\n{'═' * 70}", flush=True)
    print(f"{'PHASE 3 — benchmark via edge shim (prod contract)':^70}",
          flush=True)
    print(f"{'═' * 70}", flush=True)

    # Import the shim — same code path the edge service uses.
    sys.path.insert(0, str(SHIM_PATH))
    from query_service import QueryService as ShimQueryService  # type: ignore

    print(f"loading via shim: {OUT_DIR}", flush=True)
    t = time.perf_counter()
    svc = ShimQueryService(str(OUT_DIR))
    print(f"  loaded in {time.perf_counter()-t:.2f}s  stats={svc.stats}",
          flush=True)

    # Sample queries from the sidecar (corpus.jsonl).
    # Unique-(s,r) sampling needs the full corpus in scope — cheap because
    # we're just reading the jsonl.
    t = time.perf_counter()
    print(f"  scanning corpus.jsonl for unique (s, r) pairs…", flush=True)
    sr_first_id: dict = {}
    sr_multi: set = set()
    with open(OUT_DIR / "corpus.jsonl") as f:
        for line in f:
            rec = json.loads(line)
            key = (rec["subject"], rec["relation"])
            if key in sr_multi:
                continue
            if key in sr_first_id:
                sr_multi.add(key)
                del sr_first_id[key]
            else:
                sr_first_id[key] = rec["doc_id"]
    total_unique = len(sr_first_id)
    print(f"  {total_unique:,} unique (s, r) pairs in "
          f"{time.perf_counter()-t:.1f}s", flush=True)

    rng = random.Random(SEED + 1)
    all_keys = list(sr_first_id.keys())
    rng.shuffle(all_keys)
    sampled = all_keys[:BENCH_Q + BENCH_WARMUP]

    # Resolve gold by reloading just the sampled ids from corpus.jsonl.
    sampled_ids = set(sr_first_id[k] for k in sampled)
    gold: dict = {}
    with open(OUT_DIR / "corpus.jsonl") as f:
        for line in f:
            rec = json.loads(line)
            if rec["doc_id"] in sampled_ids:
                gold[rec["doc_id"]] = (rec["subject"], rec["relation"],
                                        rec.get("object", ""))
                if len(gold) == len(sampled_ids):
                    break
    queries = []
    for key in sampled:
        rid = sr_first_id[key]
        s, r, o = gold.get(rid, (key[0], key[1], ""))
        queries.append((rid, s, r, o))
    warm_qs = queries[BENCH_Q:]
    bench_qs = queries[:BENCH_Q]
    print(f"  sampled {len(bench_qs)} benchmark + {len(warm_qs)} warmup "
          f"queries", flush=True)

    # Warmup
    t_w = time.perf_counter()
    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(lambda q: svc.query(
            sro_tier1_query_text(q[1], q[2]), k=TOP_K), warm_qs))
    print(f"  warmup {len(warm_qs)} queries in "
          f"{time.perf_counter()-t_w:.2f}s", flush=True)

    # Benchmark
    t_b = time.perf_counter()
    ranks, lats = [0]*len(bench_qs), [0.0]*len(bench_qs)

    def _bench(item):
        i, (rid, s, r, _o) = item
        ta = time.perf_counter()
        res = svc.query(sro_tier1_query_text(s, r), k=TOP_K)
        # shim returns {"results": [...]} with "id" (string) per hit
        hit_ids = []
        for hit in res.get("results", []):
            try:
                hit_ids.append(int(hit.get("id", -1)))
            except Exception:
                pass
        return i, _rank_of(hit_ids, rid), (time.perf_counter()-ta)*1000.0

    with ThreadPoolExecutor(max_workers=12) as ex:
        for i, rank, lat in ex.map(_bench, list(enumerate(bench_qs))):
            ranks[i] = rank; lats[i] = lat
    t_bench = time.perf_counter() - t_b

    n = len(bench_qs)
    hit1 = sum(1 for r in ranks if r == 1)
    hit5 = sum(1 for r in ranks if 1 <= r <= 5)
    hit10 = sum(1 for r in ranks if 1 <= r <= 10)
    mrr = sum((1.0/r) for r in ranks if r > 0) / n

    print(f"\n{'=' * 70}", flush=True)
    print(f"{'FINAL RESULT — prod contract on 21.3M Wikidata':^70}", flush=True)
    print(f"{'=' * 70}", flush=True)
    print(f"  load time        : {svc.stats}", flush=True)
    print(f"  Hit@1            : {100*hit1/n:.2f}%", flush=True)
    print(f"  Hit@5            : {100*hit5/n:.2f}%", flush=True)
    print(f"  Hit@10           : {100*hit10/n:.2f}%", flush=True)
    print(f"  MRR              : {mrr:.4f}", flush=True)
    print(f"  p50 latency      : {statistics.median(lats):.2f} ms", flush=True)
    print(f"  p95 latency      : {_pct(lats, 95):.2f} ms", flush=True)
    print(f"  max latency      : {max(lats):.2f} ms", flush=True)
    print(f"  bench total      : {t_bench:.2f}s ({n/t_bench:.1f} q/s)",
          flush=True)
    print(f"{'=' * 70}", flush=True)

    # Write summary JSON.
    with open(OUT_DIR / "prod_bench.json", "w") as f:
        json.dump({
            "corpus_size": int(svc.stats.get("total_vectors", 0)),
            "dim": int(svc.stats.get("dim", 0)),
            "k": int(svc.stats.get("k", 0)),
            "n_queries": n,
            "warmup_queries": len(warm_qs),
            "Hit@1": 100*hit1/n,
            "Hit@5": 100*hit5/n,
            "Hit@10": 100*hit10/n,
            "MRR": mrr,
            "p50_ms": statistics.median(lats),
            "p95_ms": _pct(lats, 95),
            "max_ms": max(lats),
            "bench_seconds": t_bench,
        }, f, indent=2)


def main():
    # Phase 1 — pick (D, k).
    dim, k = phase1_sweep()
    # Phase 2 — wipe + full encode.
    phase2_encode_21m(dim, k)
    # Phase 3 — bench via shim.
    phase3_bench_via_shim()
    return 0


if __name__ == "__main__":
    sys.exit(main())
