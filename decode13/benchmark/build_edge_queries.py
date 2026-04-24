"""build_edge_queries.py — materialize the canonical 25-pattern edge
operator query set against any narrative source corpus.

Produces a JSONL where each line is `{query_text, gold_ids: [doc_id]}`
with gold built via AND-of-tokens matching (with prefix tolerance) over
the source `text` field. Output is the operator-query oracle for
`encode_unstructured.py --operator-queries`.

WHEN TO USE
===========
You're encoding edge-shape narrative data (social posts, conversations,
short messages — Iran/intelligence vocabulary in our reference setup).
You want the autotune to score against real task patterns instead of
the synthetic mask-first fallback.

EXPECTED INPUT
==============
A source JSONL with at minimum:
    {"doc_id": int, "text": "..."}
The same shape `encode_unstructured.py` consumes.

OUTPUT
======
A JSONL ready to feed to `encode_unstructured.py --operator-queries`:
    {"query_text": "Iran protests violence",
     "gold_ids": [3942, 18762, 39102, ...]}

Queries are filtered to those with 2 ≤ gold_count ≤ 30% of corpus,
matching the run_edge_benchmark usability criterion.

USAGE
=====
    python -m decode13.benchmark.build_edge_queries \\
        --source /path/to/corpus.jsonl \\
        --output /path/to/edge_queries.jsonl

For other domain corpora (different vocabulary), copy this file and
edit `QUERIES` / `_normalize_token` to match your patterns.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Set, Tuple


# Canonical 25-pattern set used by the legacy run_edge_benchmark.py.
# Each entry is (query_text, [required_token_stems]). Gold is the set
# of docs whose text contains ALL required tokens (with prefix-match).
QUERIES: List[Tuple[str, List[str]]] = [
    ("Iran protests violence",            ["iran", "protest"]),
    ("Khamenei supreme leader",           ["khamenei"]),
    ("Ali Khamenei",                      ["khamenei", "ali"]),
    ("Hezbollah statement",               ["hezbollah"]),
    ("Israeli Mossad operations",         ["mossad"]),
    ("Trump Iran sanctions",              ["trump", "iran"]),
    ("missile strike attack",             ["missile", "strike"]),
    ("Tehran city",                       ["tehran"]),
    ("Revolutionary Guard",               ["revolutionary", "guard"]),
    ("Iranian Foreign Minister",          ["foreign", "minister"]),
    ("Netanyahu Israel",                  ["netanyahu", "israel"]),
    ("Larijani politics",                 ["larijani"]),
    ("Kurdish forces",                    ["kurdish"]),
    ("nuclear program Iran",              ["nuclear", "iran"]),
    ("Iranian regime",                    ["iranian", "regim"]),
    ("women rights Iran",                 ["women", "iran"]),
    ("Lebanon Hezbollah",                 ["lebanon", "hezbollah"]),
    ("oil price energy",                  ["oil"]),
    ("prisoners jail",                    ["prisoner"]),
    ("Khomeini religious",                ["khomeini"]),
    ("Saudi Arabia UAE",                  ["saudi"]),
    ("Assad Syria war",                   ["syria"]),
    ("drone military",                    ["drone"]),
    ("uranium enrichment",                ["uranium"]),
    ("economic sanctions",                ["sanction"]),
]


def _tokenize(text: str) -> Set[str]:
    """Lowercase + alphanumeric token split. Matches build_gold semantics."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _has_all(doc_tokens: Set[str], required: List[str]) -> bool:
    """All required tokens present (prefix tolerance: 'regim' matches
    'regime', 'regimes', etc.)."""
    for r in required:
        if r in doc_tokens:
            continue
        if any(t.startswith(r) for t in doc_tokens):
            continue
        return False
    return True


def main():
    ap = argparse.ArgumentParser(
        prog="build_edge_queries",
        description="Generate the canonical 25-pattern edge operator query set.",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--source", required=True,
                    help="Source corpus JSONL with {doc_id, text} fields.")
    ap.add_argument("--output", required=True,
                    help="Output JSONL for autotune oracle.")
    ap.add_argument("--max-fraction", type=float, default=0.30,
                    help="Drop queries whose gold > this fraction of corpus. "
                         "Default 0.30 (matches run_edge_benchmark).")
    ap.add_argument("--min-gold", type=int, default=2,
                    help="Drop queries with fewer than this many gold docs.")
    args = ap.parse_args()

    source = Path(args.source).resolve()
    output = Path(args.output).resolve()

    if not source.exists():
        print(f"ERROR: source not found: {source}", file=sys.stderr)
        return 2

    # Stream corpus once; tokenize each record's text; check against all
    # 25 query patterns simultaneously. RAM stays at one record's
    # tokens at a time (plus the per-query gold lists).
    print(f"[scan] reading {source}", flush=True)
    t0 = time.perf_counter()
    n_total = 0
    gold_per_query: Dict[int, List[int]] = {qi: [] for qi in range(len(QUERIES))}
    with open(source, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = rec.get("text", "") or ""
            if not text:
                continue
            doc_id = int(rec.get("doc_id", n_total))
            n_total += 1
            doc_tokens = _tokenize(text)
            for qi, (_qtext, req) in enumerate(QUERIES):
                if _has_all(doc_tokens, req):
                    gold_per_query[qi].append(doc_id)
    print(f"[scan] {n_total:,} records in {time.perf_counter()-t0:.1f}s",
          flush=True)

    # Filter usable queries
    usable = []
    dropped = []
    for qi, (qtext, req) in enumerate(QUERIES):
        gold = gold_per_query[qi]
        gc = len(gold)
        if gc < args.min_gold or gc > args.max_fraction * n_total:
            dropped.append((qtext, gc))
            continue
        usable.append({"query_text": qtext, "required_tokens": req,
                       "gold_ids": gold, "gold_count": gc})

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        for q in usable:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    print(f"\n[output] wrote {len(usable)} queries → {output}", flush=True)
    if dropped:
        print(f"[output] dropped {len(dropped)} queries "
              f"(gold < {args.min_gold} or > {int(100*args.max_fraction)}% "
              f"of corpus):", flush=True)
        for qtext, gc in dropped:
            print(f"  - {qtext!r}: gold={gc}", flush=True)
    print(f"[output] usable queries (top 5 by gold count):", flush=True)
    for q in sorted(usable, key=lambda r: -r["gold_count"])[:5]:
        print(f"  {q['gold_count']:>5}  {q['query_text']!r}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
