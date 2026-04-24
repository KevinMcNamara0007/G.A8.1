"""Streaming encode of the wikidata corpus.jsonl into a single
StructuralPipelineV13 saved under OUT-WIKI/structural_v13/.

Reuses the benchmark's persistence shape (matches the edge-shim
contract: `structural_v13/` dir + `corpus.jsonl` sidecar). Streams
records in 10K-text batches to keep Python memory bounded; EHC owns
the encoded vectors.

Reads DIM and K from A81_DIM / A81_K (the profiler's recommended
values exported by the caller). Hebbian on by default.
"""

from __future__ import annotations

import gc
import json
import os
import resource
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent))  # G.A8.1

# _HERE.parents: [0]=decode13, [1]=G.A8.1, [2]=Quantum_Computing_Lab
for _d in (2, 3, 4):
    _p = _HERE.parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc  # noqa: E402

from decode13 import build_structural_config  # noqa: E402


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024


def main():
    if len(sys.argv) != 3:
        print("usage: _wikidata_encode.py <corpus_jsonl> <out_dir>",
              file=sys.stderr)
        return 2
    corpus_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    pipe_dir = out_dir / "structural_v13"
    pipe_dir.mkdir(parents=True, exist_ok=True)

    dim = int(os.environ.get("A81_DIM", 16384))
    k = int(os.environ.get("A81_K", 128))
    threads_env = int(os.environ.get("A81_THREADS", 0))
    print(f"[wiki-encode] dim={dim} k={k} threads={threads_env or 'auto'}",
          file=sys.stderr)

    cfg = build_structural_config(
        dim=dim, k=k,
        max_slots=24,
        enable_bigram=True,
        enable_kv=True,
        enable_hebbian=True,
        hebbian_window=5,
    )
    pipe = ehc.StructuralPipelineV13(cfg)

    BATCH = 10_000
    t0 = time.perf_counter()
    buf_texts = []
    buf_ids = []
    n = 0
    with open(corpus_path, "rb") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            # "text" field is present from the converter; fall back to
            # S R O join if not.
            text = r.get("text") or " ".join(
                str(r.get(f, "") or "") for f in ("subject", "relation", "object")
            ).strip()
            if not text:
                continue
            buf_texts.append(text)
            buf_ids.append(int(r.get("doc_id", n)))
            n += 1
            if len(buf_texts) >= BATCH:
                pipe.ingest_batch_parallel(buf_texts, buf_ids, threads_env)
                buf_texts.clear()
                buf_ids.clear()
                if n % 500_000 == 0:
                    el = time.perf_counter() - t0
                    print(f"  ingested {n:,} in {el:.1f}s "
                          f"({n/el:,.0f}/s) RSS={rss_mb():.0f}MB",
                          file=sys.stderr)
    if buf_texts:
        pipe.ingest_batch_parallel(buf_texts, buf_ids, threads_env)
        buf_texts.clear()
        buf_ids.clear()

    el = time.perf_counter() - t0
    print(f"[wiki-encode] ingested {n:,} in {el:.1f}s "
          f"({n/el:,.0f}/s) RSS={rss_mb():.0f}MB",
          file=sys.stderr)

    t_save = time.perf_counter()
    pipe.save(str(pipe_dir))
    print(f"[wiki-encode] saved pipeline to {pipe_dir} in "
          f"{time.perf_counter()-t_save:.1f}s", file=sys.stderr)

    summary = {
        "n_records": n,
        "dim": dim,
        "k": k,
        "ingest_time_s": round(el, 2),
        "ingest_rate_per_s": round(n / el if el > 0 else 0, 1),
        "rss_mb": round(rss_mb(), 0),
    }
    with open(out_dir / "encode_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"[wiki-encode] summary: {summary}", file=sys.stderr)

    del pipe
    gc.collect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
