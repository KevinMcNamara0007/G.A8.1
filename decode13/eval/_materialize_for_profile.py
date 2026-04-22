"""One-shot helper: materialize the filtered edge corpus + operator
calibration queries on disk so the v13.1 profiler can score against
the same corpus the benchmark will see.

Reads `run_edge_benchmark.STAGED` through `load_corpus` + `build_gold`,
writes `OUT/calibration_corpus.jsonl` (one filtered record per line,
sequential doc_id) and `OUT/calibration_queries.jsonl` (one query per
line with `query_text` + `gold_ids`).

Not a fixture for tests — lives here because it uses the benchmark's
private filter logic. Delete after the v13.1 validation lands.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from decode13.eval.run_edge_benchmark import (  # noqa: E402
    QUERIES, STAGED, build_gold, load_corpus,
)


def main(out_dir: str = "/Users/stark/Quantum_Computing_Lab/OUT",
         max_records: int = 0) -> int:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    corpus_path = out / "calibration_corpus.jsonl"
    queries_path = out / "calibration_queries.jsonl"

    paths = [STAGED / "msgs.jsonl", STAGED / "data3" / "msgs.jsonl"]
    paths = [p for p in paths if p.exists()]
    print(f"sources: {[str(p) for p in paths]}", file=sys.stderr)

    import time
    t0 = time.perf_counter()
    corpus = load_corpus(paths, dedupe=True,
                         max_records=max_records or None)
    print(f"loaded {len(corpus):,} filtered docs in "
          f"{time.perf_counter()-t0:.1f}s", file=sys.stderr)

    t1 = time.perf_counter()
    with open(corpus_path, "w", encoding="utf-8") as f:
        for r in corpus:
            f.write(json.dumps({
                "doc_id": r["doc_id"],
                "text": r["text"],
            }, ensure_ascii=False) + "\n")
    print(f"wrote {corpus_path} ({corpus_path.stat().st_size // 1024} KiB) "
          f"in {time.perf_counter()-t1:.1f}s", file=sys.stderr)

    t2 = time.perf_counter()
    gold = build_gold(corpus, QUERIES)
    usable = [q for q in gold if 2 <= q["gold_count"] <= 0.3 * len(corpus)]
    with open(queries_path, "w", encoding="utf-8") as f:
        for q in usable:
            f.write(json.dumps({
                "query_text": q["text"],
                "gold_ids": q["gold_doc_ids"],
            }, ensure_ascii=False) + "\n")
    print(f"wrote {queries_path} ({len(usable)} usable queries of "
          f"{len(gold)}) in {time.perf_counter()-t2:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
