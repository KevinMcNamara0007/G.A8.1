"""encode_triples.py — production encoder for SRO (subject/relation/object) corpora.

WHEN TO USE THIS
================
Your data is structured atomic triples — each record has discrete
`subject`, `relation`, and `object` fields. Knowledge graphs, Wikidata,
DBpedia, structured event logs, genomics symbols, ontologies.

CONTRACT (PlanC v13.1.3 — Tier-1 SRO)
=====================================
  - Encode each record with text = "{subject} {relation}"  (the KEY)
  - Keep full (s, r, o) in a sidecar (corpus.jsonl) for result presentation
  - Query with text = "{subject} {relation}"  → exact self-identity match
  - Atomic tokens preserved: lalit_kumar_goel stays one token
  - Hebbian off (single-exposure data; correlation noise hurts)
  - Bigram + KV binding on (role-binding gives query ⊂ gold subspace)

EXPECTED INPUT (JSONL)
======================
One record per line, with at minimum:
    {"subject": "...", "relation": "...", "object": "..."}

Extra metadata fields (e.g. timestamp, source, confidence) are passed
through to the corpus.jsonl sidecar verbatim.

OUTPUT
======
    <output_dir>/
      structural_v13/
        structural_v13.cfg     (geometry, tokenization, Hebbian state)
        lsh.bin                (LSH index for fast retrieval)
        hebbian.bin            (Hebbian co-occurrence — small if disabled)
      corpus.jsonl             (one row per doc_id with full s/r/o + metadata)
      corpus_profile.json      (when autotune is on — D/k decision audit)

LOAD-AT-QUERY-TIME
==================
The output above is loaded by `decode/query.py::QueryService`. It's the
same on-disk layout edge_service consumes via the shim. After encoding,
point A81_INDEX_PATH at <output_dir> and queries route through the
existing shim.

USAGE
=====
    # Autotune on (default): profile picks D from {4096, 8192, 16384, 32768}
    python -m encode.encode_triples \
        --source /path/to/triples.jsonl \
        --output /path/to/out_dir

    # Pin geometry explicitly (skips autotune):
    python -m encode.encode_triples \
        --source /path/to/triples.jsonl \
        --output /path/to/out_dir \
        --dim 4096 --k 64
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

# EHC import probe — same pattern as decode13/structural_encoder.py
for _d in (1, 2, 3):
    _p = _HERE.parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc  # noqa: E402

from config import cfg, resolve_workers  # noqa: E402
from decode13 import (  # noqa: E402
    build_sro_tier1_config, sro_tier1_encode_text,
)
from encode._autotune import (  # noqa: E402
    predict_d_zone, append_discovery, atoms_for_sro_tier1,
    load_operator_queries,
)


DEFAULT_AUTOTUNE_GRID = (4096, 8192, 16384, 32768)


def parse_args():
    p = argparse.ArgumentParser(
        prog="encode_triples",
        description="Encode SRO atomic triples (Tier-1 contract).",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--source", required=True,
                   help="Path to JSONL corpus (one record per line, with "
                        "subject/relation/object fields).")
    p.add_argument("--output", required=True,
                   help="Output directory. Created if missing. Will contain "
                        "structural_v13/, corpus.jsonl, corpus_profile.json.")
    p.add_argument("--dim", type=int, default=None,
                   help="BSC dimension. Default: autotune from "
                        "{4096,8192,16384,32768}. Pin to skip autotune.")
    p.add_argument("--k", type=int, default=None,
                   help="BSC sparsity. Default: √dim (autotuned).")
    p.add_argument("--no-autotune", action="store_true",
                   help="Skip the D/k profiler. Uses cfg defaults or "
                        "explicit --dim/--k. Faster for known-good corpora.")
    p.add_argument("--autotune-grid",
                   default=",".join(str(x) for x in DEFAULT_AUTOTUNE_GRID),
                   help=f"Comma-separated D values to sweep. "
                        f"Default: {','.join(str(x) for x in DEFAULT_AUTOTUNE_GRID)}.")
    p.add_argument("--workers", type=int, default=0,
                   help="Ingest threads. 0 = resolve via A81_CPU_FRACTION.")
    p.add_argument("--force", action="store_true",
                   help="Wipe output dir before encoding.")
    # NOTE: SRO Tier-1 autotune uses unique-(s,r) self-identity as the
    # oracle today — already a real-task scoring path. --operator-queries
    # is exposed in encode_unstructured.py where it's load-bearing; here
    # it's deferred until a real workload requires overriding self-id.
    return p.parse_args()


def _stream_triples(source: Path):
    """Yield (subject, relation, object, full_record_dict) per source
    record. Source may be JSONL *or* a single JSON array (Wikidata /
    DBpedia dumps ship that way); format is auto-detected by `_io`."""
    from ._io import iter_json_records
    for rec in iter_json_records(source):
        yield (
            rec.get("subject", "") or "",
            rec.get("relation", "") or "",
            rec.get("object", "") or "",
            rec,
        )


def _count_records(source: Path) -> int:
    from ._io import count_records
    return count_records(source)


def autotune_dk(source: Path, output: Path, full_grid: List[int],
                workers: int) -> Tuple[int, int, dict]:
    """Atom-aware autotune. Returns (dim, k, discovery_dict).

    Step 1 — single streaming pass: materialize 1M-record sample to a
    temp file, count atoms-per-record (s + r tokens) into a histogram,
    extract p99.

    Step 2 — predict the D zone from p99 (typically 2 candidates from
    the 4-value full grid; saves 50% of sweep cost).

    Step 3 — sweep only the predicted zone, picking the winner.

    Memory discipline: histogram is bounded (1024 buckets); sample
    lives on disk; query set is small (≤220 records). Python heap stays
    at one batch worth regardless of corpus size.
    """
    print(f"[autotune] full grid={full_grid}  sample_cap=1M",
          flush=True)

    sample_n = 1_000_000
    sample_path = output / ".autotune_sample.jsonl"

    # Single streaming pass: sample to disk + atoms histogram + sr_count.
    # We do the sr_count inline here (sample-scoped) so we can pick query
    # records right after this pass.
    output.mkdir(parents=True, exist_ok=True)
    BUCKETS = 1024
    histogram = [0] * (BUCKETS + 1)
    sr_count: dict = {}
    n_total = 0
    n_sampled = 0
    with open(sample_path, "w", encoding="utf-8") as sf:
        for i, (s, r, o, _) in enumerate(_stream_triples(source)):
            n_total += 1
            atoms = len(s.split()) + len(r.split())
            histogram[min(atoms, BUCKETS)] += 1
            if i < sample_n:
                sf.write(json.dumps({"i": i, "s": s, "r": r, "o": o},
                                    ensure_ascii=False) + "\n")
                sr_count[(s, r)] = sr_count.get((s, r), 0) + 1
                n_sampled = i + 1

    # p99 atoms from histogram
    cum = 0
    target = 0.99 * sum(histogram)
    p99 = 0
    for idx, c in enumerate(histogram):
        cum += c
        if cum >= target:
            p99 = idx
            break

    # Predict zone from p99
    predicted_zone, rationale = predict_d_zone(p99)
    swept_zone = [d for d in predicted_zone if d in full_grid] or list(full_grid)
    print(f"[autotune] scanned {n_total:,} records ({n_sampled:,} sampled)",
          flush=True)
    print(f"[autotune] p99 atoms/record = {p99}  →  zone = {predicted_zone} "
          f"({rationale})", flush=True)
    print(f"[autotune] sweeping {swept_zone}  (skipped "
          f"{[d for d in full_grid if d not in swept_zone]})",
          flush=True)

    # Build query set from the sample file (one more streaming pass).
    # Query records are small enough to hold in memory.
    unique_qs = []
    with open(sample_path, "r", encoding="utf-8") as sf:
        for line in sf:
            rec = json.loads(line)
            if sr_count.get((rec["s"], rec["r"]), 0) == 1:
                unique_qs.append((rec["i"], rec["s"], rec["r"], rec["o"]))
                if len(unique_qs) >= 220:
                    break
    if len(unique_qs) < 50:
        print(f"[autotune] WARNING: only {len(unique_qs)} unique-(s,r) "
              f"queries — sweep signal will be weak", flush=True)
    bench = unique_qs[:200]
    warmup = unique_qs[200:220] if len(unique_qs) > 220 else bench[:20]
    del sr_count  # release the dict; query set is now self-contained

    from ._autotune import derive_k_constants
    results = []
    for dim in swept_zone:
        k = max(1, int(round(math.sqrt(dim))))
        consts = derive_k_constants(k)
        cfg_ = build_sro_tier1_config(dim=dim, k=k,
                                       max_slots=consts["max_slots"])
        pipe = ehc.StructuralPipelineV13(cfg_)
        # Ingest by re-streaming the temp sample file. Ingest batch is the
        # only Python state held alongside the C++ pipeline.
        BATCH = 10_000
        tx, ix = [], []
        with open(sample_path, "r", encoding="utf-8") as sf:
            for line in sf:
                rec = json.loads(line)
                tx.append(sro_tier1_encode_text(rec["s"], rec["r"]))
                ix.append(int(rec["i"]))
                if len(tx) >= BATCH:
                    pipe.ingest_batch_parallel(tx, ix, workers); tx.clear(); ix.clear()
        if tx:
            pipe.ingest_batch_parallel(tx, ix, workers)
        # Warmup + bench (small in-memory query set is fine)
        for _i, s, r, _o in warmup:
            pipe.query_text(sro_tier1_encode_text(s, r), 10)
        t0 = time.perf_counter()
        hits = 0
        latencies = []
        for did, s, r, _o in bench:
            ta = time.perf_counter()
            r_res = pipe.query_text(sro_tier1_encode_text(s, r), 10)
            latencies.append((time.perf_counter() - ta) * 1000.0)
            ids = list(r_res.ids)
            if ids and int(ids[0]) == did:
                hits += 1
        bench_t = time.perf_counter() - t0
        latencies.sort()
        p50 = latencies[len(latencies)//2] if latencies else 0.0
        hit1 = 100.0 * hits / max(len(bench), 1)
        results.append({"dim": dim, "k": k, "Hit@1": hit1, "p50_ms": p50,
                        "max_slots": consts["max_slots"],
                        "salient_tokens": consts["salient_tokens"]})
        print(f"[autotune]   D={dim:>5} k={k:>4}  slots={consts['max_slots']:>3}  "
              f"Hit@1={hit1:>5.1f}%  p50={p50:>5.2f}ms  bench={bench_t:.2f}s",
              flush=True)
        del pipe; gc.collect()

    # Pick winner: highest Hit@1, then smallest D, then lowest p50
    winner = sorted(results,
                    key=lambda r: (-r["Hit@1"], r["dim"], r["p50_ms"]))[0]
    print(f"\n[autotune] winner: D={winner['dim']}  k={winner['k']}  "
          f"(Hit@1={winner['Hit@1']:.2f}%, p50={winner['p50_ms']:.2f}ms)\n",
          flush=True)

    # Write per-corpus profile JSON for audit (in the output dir)
    (output / "corpus_profile.json").parent.mkdir(parents=True, exist_ok=True)
    with open(output / "corpus_profile.json", "w") as f:
        json.dump({
            "full_grid": list(full_grid),
            "p99_atoms": p99,
            "predicted_zone": predicted_zone,
            "swept_zone": swept_zone,
            "results": results,
            "winner": winner,
            "derived": derive_k_constants(int(winner["k"])),
            "policy": "sro_tier1_smallest_D_at_max_Hit@1",
        }, f, indent=2)

    # Clean up temp sample file
    try:
        sample_path.unlink()
    except Exception:
        pass

    winner_consts = derive_k_constants(int(winner["k"]))
    discovery = {
        "n_records": n_total, "p99_atoms": p99,
        "predicted_zone": predicted_zone,
        "predicted_rationale": rationale,
        "swept_zone": swept_zone,
        "results": results, "winner": winner,
        "derived": winner_consts,
    }
    return int(winner["dim"]), int(winner["k"]), discovery


def encode_full(source: Path, output: Path, dim: int, k: int, workers: int):
    """Stream the full corpus → encode + write sidecar concurrently.

    Memory discipline: NEVER materializes the full sidecar in Python.
    The corpus.jsonl file is opened for write at start and each record
    is appended immediately after it goes into the C++ ingest batch.
    Python heap stays at one ingest-batch worth (~5 MB at BATCH=10K),
    independent of corpus size — a 21M-record encode runs in roughly
    the same RAM as a 21K-record encode.
    """
    pipe_dir = output / "structural_v13"
    pipe_dir.mkdir(parents=True, exist_ok=True)

    from ._autotune import derive_k_constants
    consts = derive_k_constants(k)
    pipe = ehc.StructuralPipelineV13(
        build_sro_tier1_config(dim=dim, k=k, max_slots=consts["max_slots"]))
    print(f"[encode] D={dim}  k={k}  max_slots={consts['max_slots']}  "
          f"salient_tokens={consts['salient_tokens']}  workers={workers}",
          flush=True)

    cpath = output / "corpus.jsonl"
    t0 = time.perf_counter()
    BATCH = 10_000
    tx, ix = [], []
    n = 0

    # Stream input → ingest in batches → write sidecar inline. Single
    # file handle for the sidecar; OS handles flushing.
    with open(cpath, "w", encoding="utf-8") as sidecar_f:
        for s, r, o, raw_rec in _stream_triples(source):
            tx.append(sro_tier1_encode_text(s, r))
            ix.append(n)
            # Build per-record sidecar dict, write immediately, drop it.
            sidecar_rec = {"doc_id": n, "subject": s, "relation": r,
                            "object": o,
                            "text": sro_tier1_encode_text(s, r),
                            **{k_: v for k_, v in raw_rec.items()
                               if k_ not in ("subject", "relation", "object")}}
            sidecar_f.write(json.dumps(sidecar_rec, ensure_ascii=False) + "\n")
            n += 1
            if len(tx) >= BATCH:
                pipe.ingest_batch_parallel(tx, ix, workers)
                tx.clear(); ix.clear()
                if n % 1_000_000 == 0:
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
    n_records = _count_records(source)
    print(f"[input] source={source}  records={n_records:,}  workers={workers}",
          flush=True)

    # Decide (D, k)
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
        dim, k, discovery = autotune_dk(source, output, grid, workers)

    n = encode_full(source, output, dim, k, workers)

    # Append the discovery to the universal constants log so future
    # encodes can reason from precedent.
    if discovery is not None:
        log_path = append_discovery(
            corpus_name=output.name,
            encoder="encode_triples",
            source=str(source),
            n_records=discovery["n_records"],
            p99_atoms=discovery["p99_atoms"],
            predicted_zone=discovery["predicted_zone"],
            predicted_rationale=discovery["predicted_rationale"],
            swept_zone=discovery["swept_zone"],
            sweep_results=discovery["results"],
            winner=discovery["winner"],
            derived=discovery.get("derived"),
        )
        print(f"[log]    appended discovery to {log_path}", flush=True)

    print(f"\n[done] encoded {n:,} triples at D={dim}/k={k} → {output}",
          flush=True)
    print(f"[done] point A81_INDEX_PATH at {output} and restart the edge "
          f"service to query.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
