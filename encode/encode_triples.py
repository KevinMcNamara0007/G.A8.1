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
    # Autotune on (default): profile picks D from {256, 512, 1024, 2048, 4096, 8192, 16384}
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


DEFAULT_AUTOTUNE_GRID = (256, 512, 1024, 2048, 4096, 8192, 16384)


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
                        "{256,512,1024,2048,4096,8192,16384}. Pin to skip autotune.")
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
    p.add_argument("--lift-for-p99", action="store_true",
                   help="Per-corpus opt-in: derive max_slots as "
                        "max(round(2·√k), p99_atoms) instead of the universal "
                        "law default. SRO triples typically have p99=2 so the "
                        "lift doesn't fire; this flag exists for symmetry with "
                        "encode_unstructured.py.")
    p.add_argument("--ensemble-seeds", default=None,
                   help="Comma-separated codebook seeds for ensemble encoding "
                        "(e.g. '42,56,64,96,104,116'). Encodes one pipeline "
                        "per seed under structural_v13_seedN/, shares "
                        "corpus.jsonl, writes ensemble.json. The decoder "
                        "auto-detects ensemble.json and fans queries across "
                        "all seeds, fusing via merge_top10. Spread seeds "
                        "(non-consecutive) for the best Hit@1 lift.")
    # NOTE: SRO Tier-1 autotune uses unique-(s,r) self-identity as the
    # oracle today — already a real-task scoring path. --operator-queries
    # is exposed in encode_unstructured.py where it's load-bearing; here
    # it's deferred until a real workload requires overriding self-id.
    return p.parse_args()


def _stream_triples(source: Path):
    """Yield (subject, relation, object, full_record_dict) per source
    record. Source may be JSONL *or* a single JSON array (Wikidata /
    DBpedia dumps ship that way); format is auto-detected by `_io`."""
    # BUG-G81-06: absolute import via the encode package — works both
    # as `python -m encode.encode_triples` and `python encode/encode_triples.py`
    # because sys.path was extended with _HERE.parent at the top of this file.
    from encode._io import iter_json_records
    for rec in iter_json_records(source):
        yield (
            rec.get("subject", "") or "",
            rec.get("relation", "") or "",
            rec.get("object", "") or "",
            rec,
        )


def _count_records(source: Path) -> int:
    from encode._io import count_records  # BUG-G81-06
    return count_records(source)


def _quick_p99_atoms_sro(source: Path, sample_n: int = 1_000_000) -> int:
    """Sample-bounded p99 of atom count (s+r tokens) per record. Used on
    the --no-autotune / explicit-pin path so max_slots derivation still
    has a p99 signal. Bounded at sample_n records — for SRO atomic
    corpora the sample's p99 is a tight estimator of full p99, and
    scanning past it would re-introduce the full-corpus scan we already
    eliminated from the autotune path."""
    # BUG-G81-06: see _stream_triples comment for the absolute-import rationale.
    from encode._autotune import atoms_for_sro_tier1
    from encode._io import iter_json_records
    counts = []
    for i, rec in enumerate(iter_json_records(source)):
        counts.append(atoms_for_sro_tier1(rec))
        if i + 1 >= sample_n:
            break
    if not counts:
        return 0
    counts.sort()
    idx = max(0, int(round(0.99 * (len(counts) - 1))))
    return counts[idx]


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
            atoms = len(s.split()) + len(r.split())
            histogram[min(atoms, BUCKETS)] += 1
            sf.write(json.dumps({"i": i, "s": s, "r": r, "o": o},
                                ensure_ascii=False) + "\n")
            sr_count[(s, r)] = sr_count.get((s, r), 0) + 1
            n_sampled = i + 1
            n_total = n_sampled
            if n_sampled >= sample_n:
                # Don't keep streaming the source past the sample — for
                # SRO atomic corpora the sample's atom histogram is a
                # statistically-tight estimator of the full p99 and the
                # full scan added ~5 min on a 21M-record source.
                break

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

    from encode._autotune import derive_k_constants  # BUG-G81-06
    results = []
    for dim in swept_zone:
        k = max(1, int(round(math.sqrt(dim))))
        consts = derive_k_constants(k, p99_atoms=p99)
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

    winner_consts = derive_k_constants(int(winner["k"]), p99_atoms=p99)
    discovery = {
        "n_records": n_total, "p99_atoms": p99,
        "predicted_zone": predicted_zone,
        "predicted_rationale": rationale,
        "swept_zone": swept_zone,
        "results": results, "winner": winner,
        "derived": winner_consts,
    }
    return int(winner["dim"]), int(winner["k"]), p99, discovery


def encode_full(source: Path, output: Path, dim: int, k: int,
                p99_atoms: Optional[int], workers: int):
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

    from encode._autotune import derive_k_constants  # BUG-G81-06
    consts = derive_k_constants(k, p99_atoms=p99_atoms)
    pipe = ehc.StructuralPipelineV13(
        build_sro_tier1_config(dim=dim, k=k, max_slots=consts["max_slots"]))
    p99_tag = f"p99={p99_atoms}" if p99_atoms is not None else "p99=(unscanned)"
    print(f"[encode] D={dim}  k={k}  {p99_tag}  "
          f"max_slots={consts['max_slots']}  "
          f"salient_tokens={consts['salient_tokens']}  workers={workers}",
          flush=True)

    cpath = output / "corpus.jsonl"
    t0 = time.perf_counter()
    # BATCH = 50_000: large enough that the C++ ingest workers stay busy
    # between hand-offs, small enough that memory for the in-flight batch
    # stays bounded. C++ workers process each batch in milliseconds at
    # D=512 with AVX-512.
    BATCH = 50_000

    # Path B (key-only): encode (s, r) into the vector; o lives in the
    # sidecar only. Forward (s,r → o) retrieval works through LSH;
    # reverse (o,r) is undefined (object never entered the vector).
    #
    # Two-thread pipeline running on top of the EHC C++ kernels. Both
    # downstream kernels release the GIL, so the main thread can keep
    # building the next batch while either is in flight.
    #
    #   main thread     — streams the source, computes the SRO key text,
    #                     accumulates parallel batches for ingest + sidecar,
    #                     hands each off to the respective queue.
    #   ingest_thread   — drains batch_q → pipe.ingest_batch_parallel(...).
    #   sidecar_thread  — drains sidecar_q → ehc.JsonlSidecarAppender.
    #                     The C++ appender formats AND writes the JSONL
    #                     line entirely off-GIL (BUG-G81-03 upstream fix
    #                     from EHC@230c9f7). Replaces the prior Python
    #                     json.dumps + file write that bottlenecked encode
    #                     at the GIL.
    #
    # Queue depth = 4 keeps ~3 batches ahead of each C++ side at all
    # times. The SRO key text is cached per-record (was computed twice
    # — once for tx, once for the sidecar payload).
    import queue, threading
    appender = ehc.JsonlSidecarAppender(str(cpath))
    sidecar_q: "queue.Queue" = queue.Queue(maxsize=4)
    batch_q: "queue.Queue" = queue.Queue(maxsize=4)
    writer_err: list = []
    ingest_err: list = []

    def _sidecar_writer():
        try:
            while True:
                item = sidecar_q.get()
                if item is None:
                    appender.flush()
                    appender.close()
                    sidecar_q.task_done()
                    return
                doc_ids_b, subjects_b, relations_b, objects_b, extras_b = item
                appender.append_sro_batch(
                    doc_ids_b, subjects_b, relations_b, objects_b, extras_b)
                sidecar_q.task_done()
        except Exception as exc:  # surface to main thread
            writer_err.append(exc)

    def _ingest_worker():
        try:
            while True:
                item = batch_q.get()
                if item is None:
                    batch_q.task_done()
                    return
                t_batch, i_batch = item
                pipe.ingest_batch_parallel(t_batch, i_batch, workers)
                batch_q.task_done()
        except Exception as exc:
            ingest_err.append(exc)

    writer_thread = threading.Thread(target=_sidecar_writer, daemon=True)
    ingest_thread = threading.Thread(target=_ingest_worker, daemon=True)
    writer_thread.start()
    ingest_thread.start()

    tx, ix = [], []
    doc_ids_b, subjects_b, relations_b, objects_b, extras_b = [], [], [], [], []
    n = 0

    try:
        for s, r, o, raw_rec in _stream_triples(source):
            sro_text = sro_tier1_encode_text(s, r)
            tx.append(sro_text)
            ix.append(n)
            doc_ids_b.append(n)
            subjects_b.append(s)
            relations_b.append(r)
            objects_b.append(o)
            # extras_json contract (JsonlSidecarAppender): the appender
            # writes `{"doc_id":N,"subject":S,"relation":R,"object":O,"text":"S R"EXTRAS}`
            # — note `text` is written by the appender itself (Tier-1 SRO
            # contract), so don't include it here. EXTRAS must begin with
            # `,` and contain valid JSON key:value pairs. Empty string = no
            # extras (e.g. records with only s/r/o fields).
            extras = {k_: v for k_, v in raw_rec.items()
                      if k_ not in ("subject", "relation", "object")}
            if extras:
                extras_b.append("," + json.dumps(extras, ensure_ascii=False)[1:-1])
            else:
                extras_b.append("")
            n += 1
            if len(tx) >= BATCH:
                # Hand off list ownership to the threads; allocate fresh.
                batch_q.put((tx, ix))
                sidecar_q.put((doc_ids_b, subjects_b, relations_b, objects_b, extras_b))
                tx, ix = [], []
                doc_ids_b, subjects_b, relations_b, objects_b, extras_b = [], [], [], [], []
                if n % 1_000_000 == 0:
                    el = time.perf_counter() - t0
                    print(f"[encode]   queued {n:,} in {el:.1f}s "
                          f"({n/el:,.0f}/s)", flush=True)
        if tx:
            batch_q.put((tx, ix))
            sidecar_q.put((doc_ids_b, subjects_b, relations_b, objects_b, extras_b))
    finally:
        # Drain ingest first so pipe is fully populated before save.
        batch_q.put(None)
        ingest_thread.join()
        if ingest_err:
            raise ingest_err[0]
        # Then flush + close the C++ appender.
        sidecar_q.put(None)
        writer_thread.join()
        if writer_err:
            raise writer_err[0]

    el = time.perf_counter() - t0
    print(f"[encode] ingest done: {n:,} records in {el:.1f}s "
          f"({n/el:,.0f}/s)", flush=True)

    pipe.save(str(pipe_dir))
    print(f"[encode] saved pipeline → {pipe_dir}", flush=True)
    print(f"[encode] wrote sidecar → {cpath} ({n:,} rows)", flush=True)
    return n


def encode_ensemble(source: Path, output: Path, dim: int, k: int,
                     p99_atoms: Optional[int], workers: int,
                     lift_for_p99: bool, seeds: List[int]):
    """Ensemble encode for SRO triples: one source pass → N seeded pipes
    + one shared C++ JsonlSidecarAppender.

    Threading model:
      main thread     — streams source, builds (tx, ix) batches + sidecar
                        payload batches, hands each off via queues.
      ingest_thread   — drains batch_q and fans each batch across ALL N
                        pipes sequentially. ehc.ingest_batch_parallel
                        releases the GIL and uses `workers` C++ threads
                        internally; the per-pipe iteration in Python is
                        serial, but the C++ side stays saturated.
      sidecar_thread  — unchanged from encode_full. ONE shared
                        JsonlSidecarAppender writes corpus.jsonl off-GIL.

    Output layout matches encode_unstructured.encode_ensemble:
        <output>/ensemble.json
        <output>/corpus.jsonl
        <output>/structural_v13_seed{N}/structural_v13.cfg, lsh.bin, hebbian.bin
    """
    output.mkdir(parents=True, exist_ok=True)
    from encode._autotune import derive_k_constants
    consts = derive_k_constants(k, p99_atoms=p99_atoms,
                                 lift_for_p99=lift_for_p99)

    pipes = []
    pipe_dirs = []
    for s in seeds:
        pdir = output / f"structural_v13_seed{s}"
        pdir.mkdir(parents=True, exist_ok=True)
        cfg_ = build_sro_tier1_config(
            dim=dim, k=k, max_slots=consts["max_slots"],
            codebook_seed=int(s),
        )
        pipes.append(ehc.StructuralPipelineV13(cfg_))
        pipe_dirs.append(pdir)

    lift_tag = " lift_for_p99=ON" if lift_for_p99 else ""
    p99_tag = f"p99={p99_atoms}" if p99_atoms is not None else "p99=(unscanned)"
    print(f"[encode-ensemble] seeds={seeds}  D={dim}  k={k}  {p99_tag}  "
          f"max_slots={consts['max_slots']}  "
          f"salient_tokens={consts['salient_tokens']}  "
          f"workers={workers}{lift_tag}", flush=True)

    cpath = output / "corpus.jsonl"
    t0 = time.perf_counter()
    BATCH = 50_000

    import queue, threading
    appender = ehc.JsonlSidecarAppender(str(cpath))
    sidecar_q: "queue.Queue" = queue.Queue(maxsize=4)
    batch_q: "queue.Queue" = queue.Queue(maxsize=4)
    writer_err: list = []
    ingest_err: list = []

    def _sidecar_writer():
        try:
            while True:
                item = sidecar_q.get()
                if item is None:
                    appender.flush()
                    appender.close()
                    sidecar_q.task_done()
                    return
                doc_ids_b, subjects_b, relations_b, objects_b, extras_b = item
                appender.append_sro_batch(
                    doc_ids_b, subjects_b, relations_b, objects_b, extras_b)
                sidecar_q.task_done()
        except Exception as exc:
            writer_err.append(exc)

    def _ingest_worker():
        try:
            while True:
                item = batch_q.get()
                if item is None:
                    batch_q.task_done()
                    return
                t_batch, i_batch = item
                # Fan the batch across all N pipes. Each call releases the
                # GIL and saturates `workers` C++ threads; iterating in
                # Python is fine because Python is just dispatching.
                for pipe in pipes:
                    pipe.ingest_batch_parallel(t_batch, i_batch, workers)
                batch_q.task_done()
        except Exception as exc:
            ingest_err.append(exc)

    writer_thread = threading.Thread(target=_sidecar_writer, daemon=True)
    ingest_thread = threading.Thread(target=_ingest_worker, daemon=True)
    writer_thread.start()
    ingest_thread.start()

    tx, ix = [], []
    doc_ids_b, subjects_b, relations_b, objects_b, extras_b = [], [], [], [], []
    n = 0

    try:
        for s, r, o, raw_rec in _stream_triples(source):
            sro_text = sro_tier1_encode_text(s, r)
            tx.append(sro_text); ix.append(n)
            doc_ids_b.append(n)
            subjects_b.append(s); relations_b.append(r); objects_b.append(o)
            extras = {k_: v for k_, v in raw_rec.items()
                      if k_ not in ("subject", "relation", "object")}
            if extras:
                extras_b.append("," + json.dumps(extras, ensure_ascii=False)[1:-1])
            else:
                extras_b.append("")
            n += 1
            if len(tx) >= BATCH:
                batch_q.put((tx, ix))
                sidecar_q.put((doc_ids_b, subjects_b, relations_b, objects_b, extras_b))
                tx, ix = [], []
                doc_ids_b, subjects_b, relations_b, objects_b, extras_b = [], [], [], [], []
                if n % 1_000_000 == 0:
                    el = time.perf_counter() - t0
                    print(f"[encode-ensemble]   queued {n:,} in {el:.1f}s "
                          f"({n/el:,.0f}/s into {len(pipes)} pipes)", flush=True)
        if tx:
            batch_q.put((tx, ix))
            sidecar_q.put((doc_ids_b, subjects_b, relations_b, objects_b, extras_b))
    finally:
        batch_q.put(None)
        ingest_thread.join()
        if ingest_err:
            raise ingest_err[0]
        sidecar_q.put(None)
        writer_thread.join()
        if writer_err:
            raise writer_err[0]

    el = time.perf_counter() - t0
    print(f"[encode-ensemble] ingest done: {n:,} records × {len(pipes)} "
          f"pipes in {el:.1f}s", flush=True)

    for pipe, pdir in zip(pipes, pipe_dirs):
        pipe.save(str(pdir))
    print(f"[encode-ensemble] saved {len(pipes)} pipelines under {output}/",
          flush=True)
    print(f"[encode-ensemble] wrote sidecar → {cpath} ({n:,} rows)", flush=True)

    manifest = {
        "version": 1,
        "encoder": "encode_triples",
        "seeds": [int(s) for s in seeds],
        "dim": int(dim),
        "k": int(k),
        "max_slots": int(consts["max_slots"]),
        "salient_tokens": int(consts["salient_tokens"]),
        "p99_atoms": (None if p99_atoms is None else int(p99_atoms)),
        "lift_for_p99": bool(lift_for_p99),
        "fusion": "merge_top10",
        "n_records": int(n),
    }
    with open(output / "ensemble.json", "w") as mf:
        json.dump(manifest, mf, indent=2)
    print(f"[encode-ensemble] wrote {output}/ensemble.json", flush=True)
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
    # Skip the up-front _count_records pass — on a 1.9 GB / 21M source
    # that scan alone burns ~5 min of wall time before any real work.
    # The encode pass below counts records as it ingests; we report the
    # final tally with [encode] ingest done.
    print(f"[input] source={source}  workers={workers}", flush=True)

    # Decide (D, k, p99)
    discovery = None
    p99 = None
    if args.dim is not None and args.k is not None:
        dim, k = int(args.dim), int(args.k)
        print(f"[geometry] explicit pin: D={dim}  k={k}", flush=True)
    elif args.no_autotune:
        dim = int(args.dim) if args.dim else int(cfg.DIM)
        k = int(args.k) if args.k else int(cfg.K)
        print(f"[geometry] cfg defaults: D={dim}  k={k}", flush=True)
    else:
        grid = [int(x) for x in args.autotune_grid.split(",")]
        dim, k, p99, discovery = autotune_dk(source, output, grid, workers)

    # If we skipped autotune, do a cheap p99 scan so max_slots can still
    # be p99-aware. Small cost (~1-3 s per 1M records) vs the clear win
    # of not silently truncating long records.
    if p99 is None:
        print("[scan] quick p99 atoms scan (for max_slots derivation)…",
              flush=True)
        p99 = _quick_p99_atoms_sro(source)
        print(f"[scan] p99 atoms/record = {p99}", flush=True)

    if args.ensemble_seeds:
        seeds = [int(s.strip()) for s in args.ensemble_seeds.split(",")
                 if s.strip()]
        if len(seeds) < 2:
            print("ERROR: --ensemble-seeds needs at least 2 seeds; got "
                  f"{seeds}. Drop the flag for single-seed encoding.",
                  file=sys.stderr)
            return 2
        if len(set(seeds)) != len(seeds):
            print(f"ERROR: duplicate seeds in {seeds}", file=sys.stderr)
            return 2
        n = encode_ensemble(source, output, dim, k, p99, workers,
                            lift_for_p99=args.lift_for_p99, seeds=seeds)
    else:
        n = encode_full(source, output, dim, k, p99, workers)

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
