#!/usr/bin/env python3
"""extract_to_triples.py — narrative JSONL → triples JSONL.

Runs `SpacyNERGazetteerExtractor` over a narrative source corpus and
materializes one or more (subject, relation, object, …passthrough)
triples per source record. Output is the input format `encode_triples.py`
expects, so the next step is just:

    python -m encode.encode_triples \\
        --source /path/to/extracted_triples.jsonl \\
        --output /path/to/encoded \\
        --dim 4096 --k 64

Per source record, the extractor emits up to MAX_ENTITIES_PER_SENTENCE
triples (one per entity, sharing the same `r` and `o`). Each output row
keeps a `source_doc_id` pointer back to the original record so the bench
can map gold_ids correctly.

Records that produce no triple (no entity / extraction confidence below
floor) are dropped from the output by default. Use --keep-fallback to
emit a single (entity?, mentions, text) row per dropped record so they
remain reachable through bag-of-text retrieval.

Row shape (matches encode_triples.py's expected input):
  {
    "subject":        "iran",
    "relation":       "protested",
    "object":         "<full original text>",       ← O'
    "doc_id":         <output row id, 0-indexed>,   ← encoded
    "source_doc_id":  <original record id>,          ← for bench gold_id mapping
    "extractor":      "spacy_ner_gazetteer",
    "extractor_v":    "v1",
    "confidence":     0.80,
    "extracted_o":    "regime_today_streets",        ← object slug from extractor
    "extracted_from": "edge_relation_gazetteer.json",
    ...passthrough from source record (author, site, timestamp, url, etc.)
  }
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# repo-root onto path
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import spacy                                                  # noqa: E402
from decode13.extractors_ner_gazetteer import (              # noqa: E402
    SpacyNERGazetteerExtractor, CONFIDENCE_MENTIONS_FALLBACK,
)


def parse_args():
    p = argparse.ArgumentParser(
        prog="extract_to_triples",
        description="Narrative JSONL → triples JSONL for encode_triples.")
    p.add_argument("--source", required=True,
                   help="Path to narrative JSONL (records with `text` field).")
    p.add_argument("--output", required=True,
                   help="Output JSONL (one triple per line).")
    p.add_argument("--gazetteer", required=True,
                   help="Path to relation-gazetteer JSON.")
    p.add_argument("--spacy-model", default="en_core_web_sm",
                   help="spaCy model (default en_core_web_sm).")
    p.add_argument("--keep-fallback", action="store_true",
                   help="Keep `mentions`-fallback rows (conf=0.55) instead "
                        "of dropping records with no high-confidence triple.")
    p.add_argument("--limit", type=int, default=0,
                   help="Stop after this many source records (0 = all).")
    return p.parse_args()


def main():
    args = parse_args()

    src = Path(args.source).resolve()
    out = Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        print(f"ERROR: source not found: {src}", file=sys.stderr)
        return 2

    print(f"[extract] loading spaCy {args.spacy_model} …", flush=True)
    nlp = spacy.load(args.spacy_model)
    with open(args.gazetteer) as f:
        gaz = json.load(f)
    extractor = SpacyNERGazetteerExtractor(nlp, gaz)
    gaz_name = Path(args.gazetteer).name
    print(f"[extract] gazetteer: {gaz_name}  "
          f"({len(gaz['relations'])} canonical relations)", flush=True)
    print(f"[extract] keep_fallback={args.keep_fallback}", flush=True)
    print(f"[extract] source={src}", flush=True)
    print(f"[extract] output={out}\n", flush=True)

    n_source = 0
    n_records_with_triple = 0
    n_records_dropped     = 0
    n_triples_written     = 0
    n_high_conf           = 0
    n_fallback            = 0
    output_doc_id = 0

    t0 = time.perf_counter()
    with open(src, "r", encoding="utf-8") as fin, \
         open(out, "w", encoding="utf-8") as fout:
        for i, line in enumerate(fin):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = (rec.get("text", "") or "").strip()
            if not text:
                continue
            n_source += 1
            src_doc_id = int(rec.get("doc_id", i))

            triples = extractor.extract(text)

            # filter to high-confidence unless --keep-fallback
            if not args.keep_fallback:
                triples = [t for t in triples
                           if t.confidence > CONFIDENCE_MENTIONS_FALLBACK]
            if not triples:
                n_records_dropped += 1
                continue
            n_records_with_triple += 1

            # passthrough metadata (everything except text/doc_id since we
            # re-stamp those)
            meta = {k: v for k, v in rec.items()
                    if k not in ("text", "doc_id", "subject", "relation",
                                  "object")}

            for t in triples:
                row = {
                    "subject":        t.subject,
                    "relation":       t.relation,
                    "object":         text,                    # ← O' = full text
                    "doc_id":         output_doc_id,
                    "source_doc_id":  src_doc_id,
                    "extractor":      t.extractor,
                    "extractor_v":    extractor.version,
                    "confidence":     t.confidence,
                    "extracted_o":    t.obj,
                    "extracted_from": gaz_name,
                    **meta,
                }
                fout.write(json.dumps(row, ensure_ascii=False) + "\n")
                output_doc_id += 1
                n_triples_written += 1
                if t.confidence > CONFIDENCE_MENTIONS_FALLBACK:
                    n_high_conf += 1
                else:
                    n_fallback += 1

            if args.limit and n_source >= args.limit:
                break

            if n_source % 25000 == 0:
                el = time.perf_counter() - t0
                print(f"[extract]   {n_source:,} src records → "
                      f"{n_triples_written:,} triples  "
                      f"({n_source/el:,.0f} rec/s)", flush=True)

    elapsed = time.perf_counter() - t0
    print(f"\n[extract] done in {elapsed:.1f}s "
          f"({n_source/max(elapsed,0.001):,.0f} rec/s)")
    print(f"  source records seen           : {n_source:,}")
    print(f"  records → ≥1 triple kept      : {n_records_with_triple:,}  "
          f"({100*n_records_with_triple/max(n_source,1):.1f}%)")
    print(f"  records dropped (no triple)   : {n_records_dropped:,}  "
          f"({100*n_records_dropped/max(n_source,1):.1f}%)")
    print(f"  total triples written         : {n_triples_written:,}")
    print(f"    high-confidence (gazetteer match): {n_high_conf:,}")
    print(f"    fallback ('mentions')            : {n_fallback:,}")
    if n_records_with_triple:
        print(f"  mean triples / kept-record    : "
              f"{n_triples_written/n_records_with_triple:.2f}")
    print(f"\n  output → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
