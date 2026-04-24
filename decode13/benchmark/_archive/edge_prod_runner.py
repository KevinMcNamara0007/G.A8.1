"""v13.1 edge-corpus prod runner — D ∈ {4K, 8K, 16K} sweep via shim.

Same three-phase shape as wikidata_prod_runner, but calibrated for edge
shape (Tier-2 narrative text, not SRO structured triples):

  - Encoder: StructuralPipelineV13 with Hebbian ON, bigram+KV ON,
    remove_punct=True, use_stemming=True (the decode13 default
    `build_structural_config`, NOT the SRO Tier-1 variant).
  - Query path: shim → pipe.query_text_expanded(text, top_k, hebbian_topk=3).
    The shim reads the saved pipeline + corpus.jsonl; config is persisted
    in the pipeline so encode↔decode can't drift.

Flow:
  For each D in {4096, 8192, 16384}:
    1. Build pipe at (D, k=√D), ingest 220K edge docs.
    2. Save pipeline + corpus.jsonl to OUT/ (overwriting prior iter).
    3. Load via the edge shim (G.A8.1/decode/query_service.py).
    4. 20 warmup queries + 25 benchmark queries via shim.query().
    5. Record Hit@1/Hit@10/MRR + p50/p95 latency.

After the loop, winner is whatever is last written to OUT/ (we pick
by Hit@1, tiebreak p50). We re-save the winner at the end so OUT/ is
left in a known-good production state.
"""

from __future__ import annotations

import gc
import json
import random
import shutil
import statistics
import sys
import time
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

from decode13 import build_structural_config  # noqa: E402
from decode13.eval.run_edge_benchmark import (  # noqa: E402
    STAGED, QUERIES, load_corpus, build_gold, rss_mb,
)


OUT_DIR = Path("/Users/stark/Quantum_Computing_Lab/OUT")
SHIM_PATH = Path("/Users/stark/Quantum_Computing_Lab/G.A8.1/decode")

D_GRID = [4096, 8192, 16384]
SEED = 42
TOP_K = 10
HEBBIAN_TOPK = 3
N_WARMUP = 20


def _rank_of(hit_ids: List[int], gold: set) -> int:
    for i, h in enumerate(hit_ids, 1):
        if int(h) in gold:
            return i
    return 0


def _pct(xs, p):
    try:
        return statistics.quantiles(xs, n=100)[p - 1]
    except Exception:
        return max(xs) if xs else 0.0


def wipe_out_dir():
    if OUT_DIR.exists():
        for item in OUT_DIR.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        print(f"wiped contents of {OUT_DIR}", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def encode_edge(corpus, dim: int, k: int) -> ehc.StructuralPipelineV13:
    """Encode corpus via prod edge config (Hebbian ON, bigram+KV, default
    tokenizer). Returns the populated pipeline."""
    cfg = build_structural_config(
        dim=dim, k=k,
        max_slots=24,
        enable_bigram=True,
        enable_kv=True,
        enable_hebbian=True,    # HELPS on edge (repeated token patterns)
        hebbian_window=5,
        # tokenizer defaults from build_structural_config:
        # lowercase=True, remove_punct=True, use_stemming=True,
        # remove_stopwords=False — match run_edge_benchmark.
    )
    pipe = ehc.StructuralPipelineV13(cfg)

    t0 = time.perf_counter()
    BATCH = 1_000
    tx, ix = [], []
    for r in corpus:
        tx.append(r["text"])
        ix.append(int(r["doc_id"]))
        if len(tx) >= BATCH:
            pipe.ingest_batch_parallel(tx, ix, 12); tx.clear(); ix.clear()
    if tx:
        pipe.ingest_batch_parallel(tx, ix, 12)
    t_ingest = time.perf_counter() - t0
    print(f"    ingested {len(corpus):,} in {t_ingest:.1f}s "
          f"({len(corpus)/t_ingest:,.0f}/s)  RSS={rss_mb():.0f}MB",
          flush=True)
    return pipe, t_ingest


def save_to_out(pipe, corpus, dim: int, k: int):
    pipe_dir = OUT_DIR / "structural_v13"
    pipe_dir.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    pipe.save(str(pipe_dir))
    t_save = time.perf_counter() - t

    t = time.perf_counter()
    cpath = OUT_DIR / "corpus.jsonl"
    with open(cpath, "w", encoding="utf-8") as f:
        for r in corpus:
            f.write(json.dumps({
                "doc_id":    r["doc_id"],
                "text":      r["text"],
                "raw":       r.get("raw", ""),
                "url":       r.get("url", ""),
                "author":    r.get("author", ""),
                "site":      r.get("site", ""),
                "timestamp": r.get("posted_at", ""),
                "msg_id":    r.get("msg_id", ""),
                "native_id": r.get("native_id", ""),
                "media_url": r.get("media_url", ""),
            }, ensure_ascii=False) + "\n")
    t_corpus = time.perf_counter() - t
    print(f"    saved pipeline in {t_save:.1f}s  corpus.jsonl in "
          f"{t_corpus:.1f}s", flush=True)
    return t_save + t_corpus


def bench_via_shim(queries, n_warmup: int) -> dict:
    """Load OUT/ via the shim, warmup, run benchmark queries. Measures
    end-to-end prod-contract latency."""
    if str(SHIM_PATH) not in sys.path:
        sys.path.insert(0, str(SHIM_PATH))
    # Fresh import each call so the shim reloads OUT/ state.
    import importlib
    if "query_service" in sys.modules:
        importlib.reload(sys.modules["query_service"])
    from query_service import QueryService  # type: ignore

    t = time.perf_counter()
    svc = QueryService(str(OUT_DIR))
    t_load = time.perf_counter() - t
    print(f"    shim loaded in {t_load:.2f}s  stats={svc.stats}",
          flush=True)

    # Warmup — reuse first N benchmark queries (discarded).
    t = time.perf_counter()
    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(lambda q: svc.query(q["text"], k=TOP_K),
                     queries[:n_warmup]))
    t_warm = time.perf_counter() - t
    print(f"    warmup {n_warmup} queries in {t_warm:.2f}s", flush=True)

    # Bench
    ranks = [0] * len(queries)
    lats = [0.0] * len(queries)

    def _bench(item):
        i, q = item
        gold = set(q["gold_doc_ids"])
        ta = time.perf_counter()
        res = svc.query(q["text"], k=TOP_K)
        hits = []
        for h in res.get("results", []):
            try:
                hits.append(int(h.get("id", -1)))
            except Exception:
                pass
        return i, _rank_of(hits, gold), (time.perf_counter() - ta) * 1000.0

    t = time.perf_counter()
    with ThreadPoolExecutor(max_workers=12) as ex:
        for i, rank, lat in ex.map(_bench, list(enumerate(queries))):
            ranks[i] = rank; lats[i] = lat
    t_bench = time.perf_counter() - t

    n = len(queries)
    hit1 = sum(1 for r in ranks if r == 1)
    hit5 = sum(1 for r in ranks if 1 <= r <= 5)
    hit10 = sum(1 for r in ranks if 1 <= r <= 10)
    mrr = sum((1.0 / r) for r in ranks if r > 0) / n if n else 0.0

    result = {
        "load_s": round(t_load, 2),
        "warmup_s": round(t_warm, 2),
        "bench_s": round(t_bench, 2),
        "Hit@1": round(100 * hit1 / n, 2),
        "Hit@5": round(100 * hit5 / n, 2),
        "Hit@10": round(100 * hit10 / n, 2),
        "MRR": round(mrr, 4),
        "p50_ms": round(statistics.median(lats), 2),
        "p95_ms": round(_pct(lats, 95), 2),
        "max_ms": round(max(lats), 2),
    }
    # Drop the svc so the next iteration's reload sees a clean OUT/.
    del svc
    gc.collect()
    return result


def main():
    print(f"=== v13.1 edge prod runner: D ∈ {D_GRID} ===", flush=True)

    # ── load corpus + gold ONCE ───────────────────────────
    paths = [STAGED / "msgs.jsonl", STAGED / "data3" / "msgs.jsonl"]
    paths = [p for p in paths if p.exists()]
    print(f"sources: {[str(p) for p in paths]}", flush=True)

    t = time.perf_counter()
    corpus = load_corpus(paths, dedupe=True)
    print(f"loaded {len(corpus):,} dedupe-filtered edge docs in "
          f"{time.perf_counter()-t:.1f}s", flush=True)

    gold_all = build_gold(corpus, QUERIES)
    usable = [q for q in gold_all if 2 <= q["gold_count"] <= 0.3 * len(corpus)]
    print(f"queries: {len(usable)} usable (2 ≤ gold ≤ 30%)\n", flush=True)

    # ── wipe OUT/ ─────────────────────────────────────────
    wipe_out_dir()
    print("", flush=True)

    # ── D sweep: full encode → save → bench-via-shim per D ─
    results = []
    for dim in D_GRID:
        k = max(1, int(round(dim ** 0.5)))
        print(f"══════ D={dim}, k={k} ══════", flush=True)

        pipe, t_ingest = encode_edge(corpus, dim, k)
        t_save = save_to_out(pipe, corpus, dim, k)
        # Release before loading via shim (shim creates its own pipe).
        del pipe; gc.collect()

        bench = bench_via_shim(usable, N_WARMUP)
        row = {"dim": dim, "k": k, "ingest_s": round(t_ingest, 1),
               "save_s": round(t_save, 1), **bench}
        print(f"    → Hit@1={row['Hit@1']}%  Hit@10={row['Hit@10']}%  "
              f"MRR={row['MRR']}  p50={row['p50_ms']}ms  "
              f"p95={row['p95_ms']}ms\n", flush=True)
        results.append(row)

        # Clear OUT/ before next iter so we don't leave stale state
        # (except for the final iter — we'll pick winner there).
        if dim != D_GRID[-1]:
            wipe_out_dir()
            print("", flush=True)

    # ── pick winner, re-save so OUT/ reflects it ─────────
    winner = sorted(results,
                    key=lambda r: (-r["Hit@1"], r["p50_ms"]))[0]
    print(f"══════ winner: D={winner['dim']}, k={winner['k']} ══════",
          flush=True)
    print(f"  Hit@1={winner['Hit@1']}%  MRR={winner['MRR']}  "
          f"p50={winner['p50_ms']}ms", flush=True)

    # If the winner is not the last iter, re-encode and save so OUT/
    # holds the winning geometry.
    if winner["dim"] != D_GRID[-1]:
        print(f"\nre-saving winner to OUT/…", flush=True)
        wipe_out_dir()
        pipe, _ = encode_edge(corpus, winner["dim"], winner["k"])
        save_to_out(pipe, corpus, winner["dim"], winner["k"])
        del pipe; gc.collect()

    # ── final table ───────────────────────────────────────
    print(f"\n{'=' * 90}", flush=True)
    print(f"{'EDGE PROD RUNNER — ' + str(len(corpus)) + ' docs × 25 queries':^90}",
          flush=True)
    print(f"{'=' * 90}", flush=True)
    print(f"  {'D':>5}  {'k':>4}  {'Hit@1':>7}  {'Hit@5':>7}  "
          f"{'Hit@10':>7}  {'MRR':>7}  {'p50 ms':>8}  {'p95 ms':>8}  "
          f"{'ingest s':>9}", flush=True)
    print(f"  {'-' * 86}", flush=True)
    for r in results:
        tag = " ←" if r["dim"] == winner["dim"] else "  "
        print(f"  {r['dim']:>5}  {r['k']:>4}  {r['Hit@1']:>6.2f}%  "
              f"{r['Hit@5']:>6.2f}%  {r['Hit@10']:>6.2f}%  "
              f"{r['MRR']:>7.4f}  {r['p50_ms']:>7.2f}  "
              f"{r['p95_ms']:>7.2f}  {r['ingest_s']:>8.1f}{tag}",
              flush=True)
    print(f"{'=' * 90}", flush=True)

    with open(OUT_DIR / "edge_prod_bench.json", "w") as f:
        json.dump({
            "n_docs": len(corpus),
            "n_queries": len(usable),
            "grid": D_GRID,
            "results": results,
            "winner": winner,
        }, f, indent=2)
    print(f"\nsummary: {OUT_DIR / 'edge_prod_bench.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
