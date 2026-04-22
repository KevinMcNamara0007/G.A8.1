"""Two diagnostics on top of _wikidata_structural_test:

  (a) Confirm whether underscores survive the C++ tokenizer. Ingest 3
      fixture records; inspect what tokens the pipeline says it saw
      via an empty-corpus query that returns the raw tokenization.

  (b) Compare query_text vs query_text_expanded Hit@1 on 5M to isolate
      whether Hebbian query expansion is the noise source.

Runs on a smaller (1M) corpus to move fast — we're isolating signal,
not measuring final prod performance.
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
from typing import List

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
N_TRIPLES = 1_000_000
N_QUERIES = 200
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


def diag_a_tokenization():
    """Check if underscores survive. Build a tiny pipeline, ingest 3
    records, then query each with the EXACT same text — if tokenization
    matches the ingest perfectly, Hit@1 = 100% on 3/3."""
    print("\n── Diag A: tokenizer preserves underscores? ──", flush=True)
    cfg = build_structural_config(
        dim=DIM, k=K,
        remove_punct=False, use_stemming=False, remove_stopwords=False,
    )
    p = ehc.StructuralPipelineV13(cfg)
    fixtures = [
        ("lalit_kumar_goel instance_of human", 0),
        ("koji_yamamoto_(baseball) instance_of human", 1),
        ("berthold_graf_schenk_von_stauffenberg conflict world_war_ii", 2),
    ]
    p.ingest_batch_parallel([t for t, _ in fixtures],
                             [i for _, i in fixtures], 1)
    hits = 0
    for text, rid in fixtures:
        r = p.query_text(text, TOP_K)
        ids = list(r.ids)
        if ids and ids[0] == rid:
            hits += 1
        print(f"  ingest='{text}'  gold_id={rid}  top_hit={ids[:3]}",
              flush=True)
    print(f"  self-identity Hit@1: {hits}/3", flush=True)


def diag_b_hebbian_vs_plain(triples, queries):
    """Build a full pipeline. Run both query_text and query_text_expanded
    against the same corpus+queries. If Hebbian expansion hurts, the
    expanded version will be worse."""
    print("\n── Diag B: query_text vs query_text_expanded ──", flush=True)
    cfg = build_structural_config(
        dim=DIM, k=K,
        remove_punct=False, use_stemming=False, remove_stopwords=False,
        enable_hebbian=True, hebbian_window=5,
    )
    pipe = ehc.StructuralPipelineV13(cfg)
    t0 = time.perf_counter()
    BATCH = 10_000
    tx, ix = [], []
    for i, rec in enumerate(triples):
        tx.append(f"{rec['subject']} {rec['relation']} {rec['object']}")
        ix.append(i)
        if len(tx) >= BATCH:
            pipe.ingest_batch_parallel(tx, ix, 12)
            tx.clear(); ix.clear()
    if tx:
        pipe.ingest_batch_parallel(tx, ix, 12)
    print(f"  ingested {len(triples):,} in {time.perf_counter()-t0:.1f}s",
          flush=True)

    # Plain query
    t = time.perf_counter()
    plain_hits = 0
    for rid, s, r, _o in queries:
        hit = pipe.query_text(f"{s} {r}", TOP_K)
        if list(hit.ids) and list(hit.ids)[0] == rid:
            plain_hits += 1
    print(f"  plain query_text   : Hit@1 = {100.0*plain_hits/len(queries):.1f}%  "
          f"({time.perf_counter()-t:.2f}s)", flush=True)

    # Expanded query
    t = time.perf_counter()
    exp_hits = 0
    for rid, s, r, _o in queries:
        hit = pipe.query_text_expanded(f"{s} {r}", TOP_K, 3)
        if list(hit.ids) and list(hit.ids)[0] == rid:
            exp_hits += 1
    print(f"  query_text_expanded: Hit@1 = {100.0*exp_hits/len(queries):.1f}%  "
          f"({time.perf_counter()-t:.2f}s)", flush=True)

    # And — compare to ingesting the WHOLE gold text as a query
    t = time.perf_counter()
    full_hits = 0
    for rid, s, r, o in queries:
        hit = pipe.query_text(f"{s} {r} {o}", TOP_K)
        if list(hit.ids) and list(hit.ids)[0] == rid:
            full_hits += 1
    print(f"  query w/ full S R O: Hit@1 = {100.0*full_hits/len(queries):.1f}%  "
          f"({time.perf_counter()-t:.2f}s)", flush=True)
    print(f"  ← this is the UPPER bound: if gold text exactly matches its "
          f"ingest, recall measures 'self-identity cosine'", flush=True)


def main():
    print(f"=== Structural pipeline diagnostic on {N_TRIPLES:,} triples ===",
          flush=True)

    # Diag A — tokenizer check on 3 fixture triples.
    diag_a_tokenization()

    # Diag B — Hebbian on/off on the 1M corpus.
    t0 = time.perf_counter()
    triples = _load_triples(N_TRIPLES, SEED)
    print(f"\nloaded {len(triples):,} in {time.perf_counter()-t0:.1f}s",
          flush=True)
    qs = _sample_queries(triples, N_QUERIES, SEED + 1)
    print(f"sampled {len(qs)} unique-(s,r) queries", flush=True)
    diag_b_hebbian_vs_plain(triples, qs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
