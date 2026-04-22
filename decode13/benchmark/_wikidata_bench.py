"""Wikidata Hit@1 / Hit@10 / MRR benchmark against a persisted
StructuralPipelineV13 index at OUT-WIKI/structural_v13/.

Methodology mirrors run_wikidata.py:
  1. Scan corpus.jsonl once to find (subject, relation) pairs that are
     unique in the full 21.3M corpus. Only these pairs admit an
     unambiguous gold record — otherwise competing records at the same
     (s, r) could outrank the source and deflate Hit@1 spuriously.
  2. Sample N queries uniformly from the unique-pair set.
  3. Load the pipeline. For each query, encode text = "subject relation"
     (spaces, matching the ingest-side text field), call
     query_text_expanded with Hebbian on, measure rank of source doc_id.
  4. Report Hit@1, Hit@10, MRR, per-query latency.
"""

from __future__ import annotations

import gc
import json
import random
import resource
import statistics
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent))

for _d in (2, 3, 4):
    _p = _HERE.parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc  # noqa: E402


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024


def _text_from(subject: str, relation: str, obj: str = "") -> str:
    """Ingest-side text representation: lowercase spaces, underscores removed."""
    parts = [p for p in (subject, relation, obj) if p]
    return " ".join(parts).replace("_", " ")


def build_unique_sr_pairs(corpus_path: Path, progress_every: int = 1_000_000):
    """One-pass: map (subject, relation) → list of doc_ids, filter to
    entries with exactly one doc_id (unique in the full corpus).

    Memory: ~150 bytes per unique pair in a dict of tuple→int list.
    For 21M records the pair set is up to 21M entries → ~3GB peak;
    finalized set of unique pairs is typically 60-80% of that.
    """
    counts: dict = {}  # (s, r) -> doc_id_if_first_seen, or -1 when duplicate
    n = 0
    t0 = time.perf_counter()
    with open(corpus_path, "rb") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            s = r.get("subject", "") or ""
            rel = r.get("relation", "") or ""
            key = (s, rel)
            did = int(r.get("doc_id", n))
            prev = counts.get(key)
            if prev is None:
                counts[key] = did
            else:
                counts[key] = -1   # duplicate seen, mark as non-unique
            n += 1
            if n % progress_every == 0:
                el = time.perf_counter() - t0
                rate = n / el if el > 0 else 0
                print(f"  [scan] {n:,}/{21_354_359:,} in {el:.0f}s "
                      f"({rate:,.0f}/s) unique_so_far≈"
                      f"{sum(1 for v in counts.values() if v >= 0):,} "
                      f"RSS={rss_mb():.0f}MB",
                      file=sys.stderr, flush=True)

    # Collect unique pairs.
    uniques = []
    for (s, rel), did in counts.items():
        if did >= 0:
            uniques.append((s, rel, did))
    print(f"[scan] total={n:,} unique_pairs={len(uniques):,} in "
          f"{time.perf_counter()-t0:.1f}s", file=sys.stderr, flush=True)
    return uniques, n


def load_record(corpus_path: Path, doc_ids: list) -> dict:
    """For a small set of doc_ids, stream once and collect their records
    (needed to recover `object` for the query text methodology)."""
    want = set(int(d) for d in doc_ids)
    out: dict = {}
    with open(corpus_path, "rb") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            did = int(r.get("doc_id", -1))
            if did in want:
                out[did] = r
                if len(out) == len(want):
                    break
    return out


def main():
    corpus_path = Path("/Users/stark/Quantum_Computing_Lab/OUT-WIKI/corpus.jsonl")
    pipe_dir = Path("/Users/stark/Quantum_Computing_Lab/OUT-WIKI/structural_v13")
    n_queries = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42

    # ── Step 1: find unique (subject, relation) pairs ──
    print(f"[bench] scanning {corpus_path} for unique (s, r) pairs…",
          file=sys.stderr, flush=True)
    uniques, total_records = build_unique_sr_pairs(corpus_path)

    # ── Step 2: sample N query records ──
    rng = random.Random(seed)
    rng.shuffle(uniques)
    queries = uniques[:n_queries]
    print(f"[bench] sampled {len(queries)} queries from "
          f"{len(uniques):,} unique pairs (seed={seed})",
          file=sys.stderr, flush=True)

    # We need text and object from each query record — fetch in one pass.
    sample_dids = [did for (_, _, did) in queries]
    records_by_id = load_record(corpus_path, sample_dids)

    # ── Step 3: load pipeline and run queries ──
    print(f"[bench] loading pipeline from {pipe_dir}…",
          file=sys.stderr, flush=True)
    t_load = time.perf_counter()
    pipe = ehc.StructuralPipelineV13.load(str(pipe_dir))
    print(f"[bench] loaded in {time.perf_counter()-t_load:.2f}s "
          f"RSS={rss_mb():.0f}MB", file=sys.stderr, flush=True)

    latencies = []
    hits_at_1 = 0
    hits_at_10 = 0
    mrr_sum = 0.0
    top_k = 10

    t_q0 = time.perf_counter()
    for qi, (s, rel, did) in enumerate(queries):
        qt = _text_from(s, rel)  # "subject relation" with underscores→spaces
        t_a = time.perf_counter()
        r = pipe.query_text_expanded(qt, top_k, 3)  # hebbian_topk=3
        latencies.append((time.perf_counter() - t_a) * 1000.0)
        ids = list(r.ids)
        if ids:
            if ids[0] == did:
                hits_at_1 += 1
                hits_at_10 += 1
                mrr_sum += 1.0
            else:
                for rank, hit in enumerate(ids[:top_k], 1):
                    if hit == did:
                        hits_at_10 += 1
                        mrr_sum += 1.0 / rank
                        break

    q_time = time.perf_counter() - t_q0
    n = len(queries)

    result = {
        "dim": 8192,
        "k": 90,
        "n_queries": n,
        "total_records": total_records,
        "unique_sr_pairs": len(uniques),
        "Hit@1": round(hits_at_1 / n, 4) if n else 0.0,
        "Hit@10": round(hits_at_10 / n, 4) if n else 0.0,
        "MRR": round(mrr_sum / n, 4) if n else 0.0,
        "query_time_total_s": round(q_time, 2),
        "query_p50_ms": round(statistics.median(latencies), 2) if latencies else 0,
        "query_p95_ms": (round(statistics.quantiles(latencies, n=100)[94], 2)
                        if len(latencies) >= 100 else round(max(latencies), 2)),
        "query_mean_ms": round(statistics.mean(latencies), 2) if latencies else 0,
    }

    print("\n" + "=" * 60, file=sys.stderr)
    print(f"{'WIKIDATA D=8192 k=90 BENCHMARK':^60}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    for k, v in result.items():
        print(f"  {k:<22} : {v}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    out_path = Path("/Users/stark/Quantum_Computing_Lab/OUT-WIKI/benchmark_results.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nresults written to {out_path}", file=sys.stderr)

    del pipe
    gc.collect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
