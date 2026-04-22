"""Path B — first test: encode 5M Wikidata via StructuralPipelineV13
(role binding, not TierEncoder's naive superpose). Compound tokens like
`lalit_kumar_goel` stay atomic because we disable punctuation stripping.

If query-gold cosine is in the 0.85+ regime (as role binding predicts),
the SimHash LSH should deliver both high Hit@1 AND fast queries.

Layout mirrors run_wikidata.py but swaps the encoder:
  - Load 5M triples (stream_triples, deterministic first-N).
  - Build StructuralPipelineV13 at D=8192, k=90, remove_punct=False.
  - Ingest each triple via ingest_batch_parallel using text = "s r o".
  - Sample 200 benchmark + 20 warmup queries (unique (s,r)).
  - Query via pipe.query_text_expanded("s r", top_k, hebbian_topk).
  - Report Hit@{1,5,10}, MRR, p50/p95 latency.
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

from decode13.benchmark.triples_reader import stream_triples  # noqa: E402
from decode13 import build_structural_config  # noqa: E402


TRIPLES_PATH = "/Users/stark/Quantum_Computing_Lab/GoldC/triples_21M.json"
N_TRIPLES = 5_000_000
N_QUERIES = 200
N_WARMUP = 20
DIM = 8192
K = 90
SEED = 42
TOP_K = 10
HEBBIAN_TOPK = 3


def _load_triples(n: int, seed: int):
    """Load first N triples from the file (deterministic). Returns a list
    of dicts keyed by subject, relation, object."""
    out = []
    for trip in stream_triples(TRIPLES_PATH, limit=n):
        out.append({
            "subject": trip.get("subject", "") or "",
            "relation": trip.get("relation", "") or "",
            "object": trip.get("object", "") or "",
        })
    rng = random.Random(seed)
    rng.shuffle(out)  # same shape as run_wikidata
    return out


def _sample_queries(triples, n_queries, seed):
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
    return cands[:n_queries]


def _rank_of(hit_ids: List[int], gold_id: int) -> int:
    for i, h in enumerate(hit_ids, start=1):
        if int(h) == gold_id:
            return i
    return 0


def main():
    print(f"=== Path B test: StructuralPipelineV13 on {N_TRIPLES:,} triples ===",
          flush=True)
    print(f"=== dim={DIM} k={K} remove_punct=False (atomic tokens preserved) ===\n",
          flush=True)

    t0 = time.perf_counter()
    triples = _load_triples(N_TRIPLES, SEED)
    print(f"loaded {len(triples):,} in {time.perf_counter()-t0:.1f}s",
          flush=True)

    all_qs = _sample_queries(triples, N_QUERIES + N_WARMUP, SEED + 1)
    bench_qs = all_qs[:N_QUERIES]
    warm_qs = all_qs[N_QUERIES:]
    print(f"sampled {len(bench_qs)} benchmark + {len(warm_qs)} warmup queries\n",
          flush=True)

    # Build StructuralPipelineV13 with remove_punct=False so compound
    # tokens (`lalit_kumar_goel`) stay atomic.
    cfg = build_structural_config(
        dim=DIM, k=K,
        max_slots=24,
        enable_bigram=True,
        enable_kv=True,
        enable_hebbian=True,
        hebbian_window=5,
        lowercase=True,
        remove_punct=False,   # KEY — preserve underscores
        use_stemming=False,   # also preserve exact token shape
        remove_stopwords=False,
    )
    pipe = ehc.StructuralPipelineV13(cfg)

    # Ingest: text = "subject relation object", doc_id = triple's sequential id.
    t0 = time.perf_counter()
    BATCH = 10_000
    texts = []
    ids = []
    for i, rec in enumerate(triples):
        text = f"{rec['subject']} {rec['relation']} {rec['object']}"
        texts.append(text)
        ids.append(i)
        if len(texts) >= BATCH:
            pipe.ingest_batch_parallel(texts, ids, 12)
            texts.clear()
            ids.clear()
            if (i + 1) % 500_000 == 0:
                print(f"  ingested {i+1:,}/{N_TRIPLES:,} in "
                      f"{time.perf_counter()-t0:.1f}s", flush=True)
    if texts:
        pipe.ingest_batch_parallel(texts, ids, 12)
    t_ingest = time.perf_counter() - t0
    print(f"\n  ingest done: {len(triples):,} in {t_ingest:.1f}s "
          f"({len(triples)/t_ingest:,.0f}/s)\n", flush=True)

    # Free the source triples list.
    del triples
    gc.collect()

    # Warmup
    print(f"running {len(warm_qs)} warmup queries (discarded)…", flush=True)
    t_w = time.perf_counter()
    with ThreadPoolExecutor(max_workers=12) as ex:
        def _warm(q):
            _, s, r, _o = q
            pipe.query_text_expanded(f"{s} {r}", TOP_K, HEBBIAN_TOPK)
        list(ex.map(_warm, warm_qs))
    print(f"  warmup done in {time.perf_counter()-t_w:.1f}s\n", flush=True)

    # Benchmark
    print(f"running {len(bench_qs)} benchmark queries…", flush=True)
    ranks = [0] * len(bench_qs)
    latencies = [0.0] * len(bench_qs)

    def _bench(item):
        i, (rid, s, r, _o) = item
        t_a = time.perf_counter()
        r_result = pipe.query_text_expanded(f"{s} {r}", TOP_K, HEBBIAN_TOPK)
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

    print(f"\n{'=' * 60}", flush=True)
    print(f"{'PATH B — StructuralPipelineV13 at 5M':^60}", flush=True)
    print(f"{'=' * 60}", flush=True)
    print(f"  encoder             : StructuralPipelineV13 (role+bigram+KV+Hebbian)",
          flush=True)
    print(f"  corpus              : {n} queries over {N_TRIPLES:,} triples",
          flush=True)
    print(f"  dim × k             : {DIM} × {K}", flush=True)
    print(f"  ingest time         : {t_ingest:.1f}s ({N_TRIPLES/t_ingest:,.0f}/s)",
          flush=True)
    print(f"  bench time          : {t_bench:.2f}s ({n/t_bench:.1f} q/s)", flush=True)
    print(f"  Hit@1               : {100.0*hit1/n:.2f}%", flush=True)
    print(f"  Hit@5               : {100.0*hit5/n:.2f}%", flush=True)
    print(f"  Hit@10              : {100.0*hit10/n:.2f}%", flush=True)
    print(f"  MRR                 : {mrr:.4f}", flush=True)
    print(f"  p50 latency         : {statistics.median(latencies):.2f} ms",
          flush=True)
    print(f"  p95 latency         : {_pct(95):.2f} ms", flush=True)
    print(f"  max latency         : {max(latencies):.2f} ms", flush=True)
    print(f"{'=' * 60}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
