"""One-shot converter: triples_21M.json (JSON array) → corpus.jsonl.

Streams via triples_reader.stream_triples so memory stays O(1) in file
size. Each output line is a JSON dict with `doc_id` (sequential) +
`subject` + `relation` + `object` + `text` (= "S R O" concatenation, so
the profiler's mask-one-field synthetic-query path works). Also builds
a "text" field used by the edge-shim at query time — harmless for
structured-only retrieval.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent))

from decode13.benchmark.triples_reader import stream_triples


def main():
    if len(sys.argv) != 3:
        print("usage: _wikidata_to_jsonl.py <src_json> <dst_jsonl>",
              file=sys.stderr)
        return 2
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    dst.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    n = 0
    with open(dst, "w", encoding="utf-8") as f:
        for trip in stream_triples(str(src)):
            s = trip.get("subject", "") or ""
            r = trip.get("relation", "") or ""
            o = trip.get("object", "") or ""
            text = " ".join(x for x in (s, r, o) if x).replace("_", " ")
            f.write(json.dumps({
                "doc_id": n,
                "subject": s,
                "relation": r,
                "object": o,
                "text": text,
            }, ensure_ascii=False) + "\n")
            n += 1
            if n % 1_000_000 == 0:
                el = time.perf_counter() - t0
                print(f"  converted {n:,} in {el:.1f}s "
                      f"({n/el:,.0f}/s)", file=sys.stderr)
    el = time.perf_counter() - t0
    print(f"done: {n:,} records → {dst} in {el:.1f}s",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
