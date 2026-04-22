"""Path B v2 — redefine the Tier-1 retrieval key.

Insight from the diagnostic: role binding + top-k selection does NOT
preserve the "query ⊂ gold" subspace property when the query drops a
token. Ingesting gold as "s r o" and querying with "s r" lands the two
vectors in materially different LSH neighborhoods.

The cleaner fix is to match semantics: for Wikidata knowledge-graph
retrieval, the LOOKUP KEY is (subject, relation) and the OBJECT is the
ANSWER. Encoding the key differently than the value is standard in
retrieval systems; it's only weird here because we conflated them.

Layout:
  - Ingest each record with text = "s r" (the KEY only).
  - Keep full (s, r, o) in a sidecar dict keyed by doc_id for
    result presentation.
  - Query with "s r" — matches key exactly.

Hebbian is disabled (diagnostic showed it hurts single-exposure data).
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

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent))

for _d in (2, 3, 4):
    _p = _HERE.parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc  # noqa: E402

from decode13.benchmark.triples_reader import stream_triples  # noqa: E402
from decode13 import build_structural_config  # noqa: E402


TRIPLES_PATH = "/Users/stark/Quantum_Computing_Lab/GoldC/triples_21M.json"
N_TRIPLES = 5_000_000
N_QUERIES = 500
N_WARMUP = 20
DIM = 8192
K = 90
SEED = 42
TOP_K = 10


def _load_triples(n, seed):
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


def _sample_queries(triples, n, seed):
    sr_count = Counter()
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


def main():
    print(f"=== Path B v2: (s, r) retrieval key on {N_TRIPLES:,} triples ===",
          flush=True)
    print(f"    Ingest text = 'subject relation' (KEY)", flush=True)
    print(f"    Query text  = 'subject relation'", flush=True)
    print(f"    Sidecar     = full (s, r, o) in memory keyed by doc_id", flush=True)
    print(f"    Hebbian     = disabled (diagnostic showed it hurts)\n", flush=True)

    t0 = time.perf_counter()
    triples = _load_triples(N_TRIPLES, SEED)
    print(f"loaded {len(triples):,} in {time.perf_counter()-t0:.1f}s",
          flush=True)

    all_qs = _sample_queries(triples, N_QUERIES + N_WARMUP, SEED + 1)
    bench_qs = all_qs[:N_QUERIES]
    warm_qs = all_qs[N_QUERIES:]
    print(f"sampled {len(bench_qs)} benchmark + {len(warm_qs)} warmup queries",
          flush=True)

    # Sidecar — doc_id → full triple. Used for presenting results.
    sidecar = [(rec["subject"], rec["relation"], rec["object"])
               for rec in triples]
    print(f"built sidecar: {len(sidecar):,} entries\n", flush=True)

    cfg = build_structural_config(
        dim=DIM, k=K,
        enable_bigram=True,
        enable_kv=True,
        enable_hebbian=False,   # Hebbian off — noisy on single-exposure data
        remove_punct=False,
        use_stemming=False,
        remove_stopwords=False,
    )
    pipe = ehc.StructuralPipelineV13(cfg)

    # Ingest: text = "subject relation" (the KEY only).
    t0 = time.perf_counter()
    BATCH = 10_000
    tx, ix = [], []
    for i, rec in enumerate(triples):
        tx.append(f"{rec['subject']} {rec['relation']}")
        ix.append(i)
        if len(tx) >= BATCH:
            pipe.ingest_batch_parallel(tx, ix, 12)
            tx.clear(); ix.clear()
            if (i + 1) % 500_000 == 0:
                print(f"  ingested {i+1:,}/{N_TRIPLES:,} in "
                      f"{time.perf_counter()-t0:.1f}s "
                      f"({(i+1)/(time.perf_counter()-t0):,.0f}/s)", flush=True)
    if tx:
        pipe.ingest_batch_parallel(tx, ix, 12)
    t_ingest = time.perf_counter() - t0
    print(f"  ingest done: {len(triples):,} in {t_ingest:.1f}s "
          f"({len(triples)/t_ingest:,.0f}/s)\n", flush=True)

    del triples
    gc.collect()

    # Warmup
    print(f"warmup {len(warm_qs)} queries (discarded)…", flush=True)
    t_w = time.perf_counter()
    with ThreadPoolExecutor(max_workers=12) as ex:
        def _warm(q):
            _, s, r, _o = q
            pipe.query_text(f"{s} {r}", TOP_K)
        list(ex.map(_warm, warm_qs))
    print(f"  warmup done in {time.perf_counter()-t_w:.1f}s\n", flush=True)

    # Benchmark
    print(f"benchmark {len(bench_qs)} queries…", flush=True)
    ranks = [0] * len(bench_qs)
    latencies = [0.0] * len(bench_qs)

    def _bench(item):
        i, (rid, s, r, _o) = item
        t_a = time.perf_counter()
        r_result = pipe.query_text(f"{s} {r}", TOP_K)
        lat = (time.perf_counter() - t_a) * 1000.0
        hit_ids = list(r_result.ids)
        rank = _rank_of(hit_ids, rid)
        return i, rank, lat

    t_q = time.perf_counter()
    with ThreadPoolExecutor(max_workers=12) as ex:
        for i, rank, lat in ex.map(_bench, list(enumerate(bench_qs))):
            ranks[i] = rank
            latencies[i] = lat
    t_bench = time.perf_counter() - t_q

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

    print(f"\n{'=' * 65}", flush=True)
    print(f"{'PATH B v2 — (s, r) KEY / o SIDECAR on 5M':^65}", flush=True)
    print(f"{'=' * 65}", flush=True)
    print(f"  encoder        : StructuralPipelineV13 (role+bigram+KV, Hebbian OFF)",
          flush=True)
    print(f"  corpus         : {n} queries over {N_TRIPLES:,} triples", flush=True)
    print(f"  dim × k        : {DIM} × {K}", flush=True)
    print(f"  ingest time    : {t_ingest:.1f}s ({N_TRIPLES/t_ingest:,.0f}/s)",
          flush=True)
    print(f"  bench time     : {t_bench:.2f}s ({n/t_bench:.1f} q/s)", flush=True)
    print(f"  Hit@1          : {100.0*hit1/n:.2f}%", flush=True)
    print(f"  Hit@5          : {100.0*hit5/n:.2f}%", flush=True)
    print(f"  Hit@10         : {100.0*hit10/n:.2f}%", flush=True)
    print(f"  MRR            : {mrr:.4f}", flush=True)
    print(f"  p50 latency    : {statistics.median(latencies):.2f} ms",
          flush=True)
    print(f"  p95 latency    : {_pct(95):.2f} ms", flush=True)
    print(f"  max latency    : {max(latencies):.2f} ms", flush=True)
    print(f"{'=' * 65}", flush=True)

    # Demonstrate sidecar lookup for top 5 queries.
    print(f"\nSIDECAR DEMO (first 5 queries):", flush=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        def _demo(q):
            rid, s, r, o = q
            hit = pipe.query_text(f"{s} {r}", TOP_K)
            top_ids = list(hit.ids)
            top_sidecar = [sidecar[i] if i < len(sidecar) else None
                           for i in top_ids[:1]]
            return rid, s, r, o, top_ids, top_sidecar
        for rid, s, r, o, tids, side in ex.map(_demo, bench_qs[:5]):
            print(f"  q='{s} {r}'  gold=(rid={rid}, o='{o}')", flush=True)
            if tids:
                retrieved = side[0] if side else None
                print(f"    top-hit doc_id={tids[0]}  sidecar={retrieved}",
                      flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
