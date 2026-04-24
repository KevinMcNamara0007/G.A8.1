"""encode_unstructured.py — production encoder for narrative / free-text corpora.

WHEN TO USE THIS
================
Your data is unstructured text — social-media posts, free-text logs,
news articles, message bodies, document chunks. No discrete subject /
relation / object fields.

If your data IS structured triples, use `encode_triples.py` instead.

CONTRACT (v13.1 Tier-2 narrative)
=================================
  - Encode each record's full text via StructuralPipelineV13
  - Slot binding + bigram + KV  →  preserves token-order signal
  - Hebbian ON  (repeated co-occurrence helps narrative retrieval)
  - SimHash LSH for sub-linear query latency

EXPECTED INPUT (JSONL)
======================
One record per line, with at minimum:
    {"text": "..."}                    # the searchable content

Common metadata fields the edge_service shim consumes downstream:
    "doc_id"     (int — auto-assigned if absent)
    "raw"        (untruncated source text)
    "url"        (link to source)
    "author"     (string)
    "site"       (source platform)
    "timestamp"  (ISO-8601)
    "msg_id"     (native source id, e.g. tweet id)
    "native_id"  (platform-internal id)
    "media_url"  (image / video reference)
All other fields pass through to corpus.jsonl unchanged.

OUTPUT
======
Same on-disk layout as encode_triples.py — loadable by the same
decode/query.py shim:
    <output_dir>/
      structural_v13/
        structural_v13.cfg, lsh.bin, hebbian.bin
      corpus.jsonl           (sidecar with all source metadata)
      corpus_profile.json    (autotune audit)

USAGE
=====
    # Autotune on (default): profile picks D from {4096, 8192, 16384, 32768}
    python -m encode.encode_unstructured \
        --source /path/to/messages.jsonl \
        --output /path/to/out_dir

    # Pin geometry explicitly:
    python -m encode.encode_unstructured \
        --source /path/to/messages.jsonl \
        --output /path/to/out_dir \
        --dim 4096 --k 64
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import shutil
import sys
import time
from pathlib import Path
from typing import List, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

for _d in (1, 2, 3):
    _p = _HERE.parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc  # noqa: E402

from config import cfg, resolve_workers  # noqa: E402
from decode13 import build_structural_config  # noqa: E402
from encode._autotune import (  # noqa: E402
    predict_d_zone, append_discovery, atoms_for_unstructured,
    load_operator_queries,
)


DEFAULT_AUTOTUNE_GRID = (4096, 8192, 16384, 32768)


def parse_args():
    p = argparse.ArgumentParser(
        prog="encode_unstructured",
        description="Encode narrative / free-text corpora (Tier-2 contract).",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--source", required=True,
                   help="Path to JSONL corpus (one record per line, with a "
                        "'text' field).")
    p.add_argument("--output", required=True,
                   help="Output directory.")
    p.add_argument("--dim", type=int, default=None,
                   help="BSC dimension. Default: autotune from "
                        "{4096,8192,16384,32768}.")
    p.add_argument("--k", type=int, default=None,
                   help="BSC sparsity. Default: √dim (autotuned).")
    p.add_argument("--no-autotune", action="store_true",
                   help="Skip the D/k profiler; use cfg or explicit pins.")
    p.add_argument("--autotune-grid",
                   default=",".join(str(x) for x in DEFAULT_AUTOTUNE_GRID),
                   help=f"Comma-separated D values to sweep. "
                        f"Default: {','.join(str(x) for x in DEFAULT_AUTOTUNE_GRID)}.")
    p.add_argument("--workers", type=int, default=0,
                   help="Ingest threads. 0 = resolve via A81_CPU_FRACTION.")
    p.add_argument("--force", action="store_true",
                   help="Wipe output dir before encoding.")
    p.add_argument("--no-hebbian", action="store_true",
                   help="Disable Hebbian co-occurrence layer. Default ON for "
                        "narrative corpora; turn OFF for single-exposure data.")
    p.add_argument("--operator-queries", default=None,
                   help="JSONL of {query_text, gold_ids: [doc_id]} entries. "
                        "When supplied, autotune scores against THESE real "
                        "queries (recommended). Without this, autotune uses "
                        "a synthetic mask-first heuristic that systematically "
                        "under-scores narrative corpora. For edge-shape "
                        "corpora, generate the canonical 25-pattern set via "
                        "`python -m decode13.benchmark.build_edge_queries`.")
    return p.parse_args()


def _stream_records(source: Path):
    """Yield (text, full_record_dict) per source record. Source may be
    JSONL *or* a single JSON array; format is auto-detected by `_io`.
    Records without a non-empty 'text' field are skipped."""
    from ._io import iter_json_records
    for rec in iter_json_records(source):
        text = (rec.get("text", "") or "").strip()
        if not text:
            continue
        yield text, rec


def _count_records(source: Path) -> int:
    n = 0
    for _ in _stream_records(source):
        n += 1
    return n


def autotune_dk(source: Path, output: Path, grid: List[int],
                workers: int, hebbian: bool,
                operator_queries_path: str = None) -> Tuple[int, int, dict]:
    """D-sweep at a 200K sample with synthetic mask-one-token queries.

    For narrative corpora, autotune is more interpretable than for SRO:
    different D gives meaningfully different retrieval (per the v13.1.3
    plateau-aware analysis). We pick by best Hit@1, tiebreak smaller D.
    """
    # Autotune sample cap. Was 200K — too aggressive for narrative
    # corpora in the few-hundred-K range (D=4096 underestimates
    # because narrative is more sensitive to corpus completeness at
    # small dim). 1M cap matches encode_triples.py and means autotune
    # encodes the FULL corpus for anything under 1M records.
    sample_n = 1_000_000
    print(f"[autotune] full grid={grid}  sample_cap={sample_n:,}",
          flush=True)

    # One streaming pass: sample to disk + atoms-per-record histogram.
    sample_path = output / ".autotune_sample.jsonl"
    output.mkdir(parents=True, exist_ok=True)
    BUCKETS = 1024
    histogram = [0] * (BUCKETS + 1)
    n_sampled = 0
    n_total = 0
    with open(sample_path, "w", encoding="utf-8") as sf:
        for i, (text, raw_rec) in enumerate(_stream_records(source)):
            n_total += 1
            atoms = len(text.split())
            histogram[min(atoms, BUCKETS)] += 1
            if i < sample_n:
                # CRITICAL: write the SOURCE doc_id (not the post-skip
                # enumerate index) so the autotune index aligns with
                # operator-query gold_ids that reference original doc_ids.
                # Skipped records (empty text) shift enumerate but not
                # doc_id; misaligning here silently zeros Hit@1.
                doc_id = int(raw_rec.get("doc_id", i))
                sf.write(json.dumps({"i": doc_id, "t": text},
                                    ensure_ascii=False) + "\n")
                n_sampled = i + 1

    # p99 from histogram → predicted zone
    cum = 0
    target = 0.99 * sum(histogram)
    p99 = 0
    for idx, c in enumerate(histogram):
        cum += c
        if cum >= target:
            p99 = idx
            break
    has_op = bool(operator_queries_path)
    predicted_zone, rationale = predict_d_zone(p99, has_operator_queries=has_op)
    swept_zone = [d for d in predicted_zone if d in grid] or list(grid)
    print(f"[autotune] scanned {n_total:,} records ({n_sampled:,} sampled)",
          flush=True)
    print(f"[autotune] p99 atoms/record = {p99}  →  zone = {predicted_zone} "
          f"({rationale})", flush=True)
    print(f"[autotune] sweeping {swept_zone}  (skipped "
          f"{[d for d in grid if d not in swept_zone]})", flush=True)

    # Pick the autotune oracle. If operator queries are supplied, use
    # those (real-task scoring). Otherwise fall back to synthetic
    # mask-first queries — good enough for "is the pipeline running"
    # but biased upward in D for narrative corpora.
    if operator_queries_path:
        op_queries = load_operator_queries(operator_queries_path)
        # Each query: (gold_id, query_text, gold_id_set)
        queries = [(q["gold_ids"][0], q["query_text"], set(q["gold_ids"]))
                    for q in op_queries]
        print(f"[autotune] oracle: operator queries ({len(queries)} from "
              f"{operator_queries_path})", flush=True)
    else:
        import random
        rng = random.Random(42)
        qids = set(rng.sample(range(n_sampled), min(200, n_sampled)))
        queries = []
        with open(sample_path, "r", encoding="utf-8") as sf:
            for line in sf:
                rec = json.loads(line)
                if rec["i"] in qids:
                    toks = rec["t"].split()
                    if len(toks) >= 4:
                        cut = max(2, int(len(toks) * 0.6))
                        queries.append((rec["i"], " ".join(toks[:cut]),
                                         {rec["i"]}))
                    if len(queries) >= len(qids):
                        break
        print(f"[autotune] oracle: synthetic mask-first ({len(queries)} "
              f"queries; CEILING measurement — biased upward in D)",
              flush=True)

    results = []
    for dim in swept_zone:
        k = max(1, int(round(math.sqrt(dim))))
        cfg_ = build_structural_config(
            dim=dim, k=k, max_slots=24,
            enable_bigram=True, enable_kv=True,
            enable_hebbian=hebbian, hebbian_window=5,
        )
        pipe = ehc.StructuralPipelineV13(cfg_)
        BATCH = 1_000
        tx, ix = [], []
        # Re-stream the sample from disk; only one batch worth in memory.
        with open(sample_path, "r", encoding="utf-8") as sf:
            for line in sf:
                rec = json.loads(line)
                tx.append(rec["t"]); ix.append(int(rec["i"]))
                if len(tx) >= BATCH:
                    pipe.ingest_batch_parallel(tx, ix, workers); tx.clear(); ix.clear()
        if tx:
            pipe.ingest_batch_parallel(tx, ix, workers)
        # Warmup + bench
        for _qid, qt, _g in queries[:20]:
            (pipe.query_text_expanded(qt, 10, 3) if hebbian
             else pipe.query_text(qt, 10))
        t0 = time.perf_counter()
        hits = 0
        latencies = []
        for _qid, qt, gold_set in queries:
            ta = time.perf_counter()
            r = (pipe.query_text_expanded(qt, 10, 3) if hebbian
                 else pipe.query_text(qt, 10))
            latencies.append((time.perf_counter() - ta) * 1000.0)
            ids = list(r.ids)
            if ids and int(ids[0]) in gold_set:
                hits += 1
        bench_t = time.perf_counter() - t0
        latencies.sort()
        p50 = latencies[len(latencies)//2] if latencies else 0.0
        hit1 = 100.0 * hits / max(len(queries), 1)
        results.append({"dim": dim, "k": k, "Hit@1": hit1, "p50_ms": p50})
        print(f"[autotune]   D={dim:>5} k={k:>4}  Hit@1={hit1:>5.1f}%  "
              f"p50={p50:>5.2f}ms  bench={bench_t:.2f}s", flush=True)
        del pipe; gc.collect()

    # Pick winner: best Hit@1, tiebreak smallest D
    winner = sorted(results,
                    key=lambda r: (-r["Hit@1"], r["dim"], r["p50_ms"]))[0]
    print(f"\n[autotune] winner: D={winner['dim']}  k={winner['k']}  "
          f"(Hit@1={winner['Hit@1']:.2f}%, p50={winner['p50_ms']:.2f}ms)\n",
          flush=True)

    output.mkdir(parents=True, exist_ok=True)
    with open(output / "corpus_profile.json", "w") as f:
        json.dump({
            "full_grid": list(grid),
            "p99_atoms": p99,
            "predicted_zone": predicted_zone,
            "swept_zone": swept_zone,
            "results": results, "winner": winner,
            "policy": "unstructured_smallest_D_at_max_Hit@1",
            "queries_used": "synthetic_mask_first_60pct",
            "n_queries": len(queries),
        }, f, indent=2)
    # Clean up temp sample file
    try:
        sample_path.unlink()
    except Exception:
        pass
    discovery = {
        "n_records": n_total, "p99_atoms": p99,
        "predicted_zone": predicted_zone,
        "predicted_rationale": rationale,
        "swept_zone": swept_zone,
        "results": results, "winner": winner,
    }
    return int(winner["dim"]), int(winner["k"]), discovery


def encode_full(source: Path, output: Path, dim: int, k: int,
                workers: int, hebbian: bool):
    """Stream input → encode + write sidecar concurrently.

    Memory discipline: corpus.jsonl is opened for write at start; each
    record is appended as soon as it's batched into the C++ ingest.
    Python heap stays at one ingest-batch worth (~5 MB at BATCH=1K
    narrative records), independent of corpus size.
    """
    pipe_dir = output / "structural_v13"
    pipe_dir.mkdir(parents=True, exist_ok=True)

    cfg_ = build_structural_config(
        dim=dim, k=k, max_slots=24,
        enable_bigram=True, enable_kv=True,
        enable_hebbian=hebbian, hebbian_window=5,
    )
    pipe = ehc.StructuralPipelineV13(cfg_)
    print(f"[encode] D={dim}  k={k}  workers={workers}  hebbian={hebbian}",
          flush=True)

    cpath = output / "corpus.jsonl"
    t0 = time.perf_counter()
    BATCH = 1_000
    tx, ix = [], []
    n = 0

    # Stream input → ingest in batches → write sidecar inline.
    with open(cpath, "w", encoding="utf-8") as sidecar_f:
        for text, raw_rec in _stream_records(source):
            doc_id = int(raw_rec.get("doc_id", n))
            tx.append(text); ix.append(doc_id)
            out_rec = {"doc_id": doc_id, "text": text,
                       **{k_: v for k_, v in raw_rec.items()
                          if k_ not in ("doc_id", "text")}}
            sidecar_f.write(json.dumps(out_rec, ensure_ascii=False) + "\n")
            n += 1
            if len(tx) >= BATCH:
                pipe.ingest_batch_parallel(tx, ix, workers)
                tx.clear(); ix.clear()
                if n % 100_000 == 0:
                    el = time.perf_counter() - t0
                    print(f"[encode]   ingested {n:,} in {el:.1f}s "
                          f"({n/el:,.0f}/s)", flush=True)
        if tx:
            pipe.ingest_batch_parallel(tx, ix, workers)

    el = time.perf_counter() - t0
    print(f"[encode] ingest done: {n:,} records in {el:.1f}s "
          f"({n/el:,.0f}/s)", flush=True)

    pipe.save(str(pipe_dir))
    print(f"[encode] saved pipeline → {pipe_dir}", flush=True)
    print(f"[encode] wrote sidecar → {cpath} ({n:,} rows)", flush=True)
    return n


def main():
    args = parse_args()
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    hebbian = not args.no_hebbian

    if not source.exists():
        print(f"ERROR: source not found: {source}", file=sys.stderr)
        return 2

    if args.force and output.exists():
        for item in output.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        print(f"[wipe] cleared {output}", flush=True)
    output.mkdir(parents=True, exist_ok=True)

    workers = resolve_workers(args.workers)
    print(f"[input] source={source}  workers={workers}", flush=True)

    discovery = None
    if args.dim is not None and args.k is not None:
        dim, k = int(args.dim), int(args.k)
        print(f"[geometry] explicit pin: D={dim}  k={k}", flush=True)
    elif args.no_autotune:
        dim = int(args.dim) if args.dim else int(cfg.DIM)
        k = int(args.k) if args.k else int(cfg.K)
        print(f"[geometry] cfg defaults: D={dim}  k={k}", flush=True)
    else:
        grid = [int(x) for x in args.autotune_grid.split(",")]
        dim, k, discovery = autotune_dk(source, output, grid, workers,
                                          hebbian,
                                          operator_queries_path=args.operator_queries)

    n = encode_full(source, output, dim, k, workers, hebbian)

    if discovery is not None:
        log_path = append_discovery(
            corpus_name=output.name,
            encoder="encode_unstructured",
            source=str(source),
            n_records=discovery["n_records"],
            p99_atoms=discovery["p99_atoms"],
            predicted_zone=discovery["predicted_zone"],
            predicted_rationale=discovery["predicted_rationale"],
            swept_zone=discovery["swept_zone"],
            sweep_results=discovery["results"],
            winner=discovery["winner"],
        )
        print(f"[log]    appended discovery to {log_path}", flush=True)

    print(f"\n[done] encoded {n:,} records at D={dim}/k={k} → {output}",
          flush=True)
    print(f"[done] point A81_INDEX_PATH at {output} and restart the edge "
          f"service to query.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
