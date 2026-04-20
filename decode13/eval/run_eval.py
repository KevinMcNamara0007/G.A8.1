"""decode13 eval harness — runs 4 encoders over the same corpus + queries.

Corpus: tweets_200.jsonl (first English sentence from each tweet, cleaned)
Queries: queries_20.jsonl (auto-labeled gold — user may refine)

Encoders under test:

    B1 bag_shatter          SymbolicTextEncoder default (bag of whitespace tokens,
                            lowercased — what closed-loop canonical produces)
    B2 norm_stem_bag        TextNormalizer.tokenize() + PorterStemmer.stem_batch()
                            then SymbolicTextEncoder superpose — a better bag
                            baseline because it canonicalizes morphology
    C  structural_v13       StructuralPipelineV13 (slot-binding + optional bigram
                            + optional KV + optional Hebbian)
    C- structural_no_heb    Same, Hebbian disabled (pure structural baseline)

Metrics per query: Recall@10, MRR, nDCG@10.  Aggregate: mean across queries.
Latency: per-record encode cost (ms) and per-query cost (ms).

All heavy lifting is C++. Python just orchestrates + reports.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

# Prefer the freshly built EHC binary.
for _d in (0, 1, 2):
    _p = _ROOT.parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc  # noqa: E402


HERE = Path(__file__).resolve().parent
TWEETS_PATH  = HERE / "tweets_200.jsonl"
QUERIES_PATH = HERE / "queries_20.jsonl"


def _ascii_clean(s: str) -> str:
    """Strip non-ASCII codepoints. C++ TextNormalizer assumes ASCII-safe input
    and throws on embedded 4-byte UTF-8 (emoji, Arabic, etc.). Both encode and
    query paths pass through this same function — contract preserved."""
    return s.encode("ascii", "ignore").decode("ascii")


def load_tweets() -> List[dict]:
    out = []
    with open(TWEETS_PATH) as f:
        for line in f:
            rec = json.loads(line)
            rec["text"] = _ascii_clean(rec.get("text", ""))
            out.append(rec)
    return out


def load_queries() -> List[dict]:
    out = []
    with open(QUERIES_PATH) as f:
        for line in f:
            out.append(json.loads(line))
    return out


# ─── Encoder adapters — all same shape: build, ingest, query ────────────

class Encoder:
    name = "base"
    def __init__(self, dim=4096, k=64): ...
    def ingest(self, texts: List[str], doc_ids: List[int]) -> None: ...
    def query(self, text: str, k: int) -> Tuple[List[int], List[float]]: ...


class BagShatterEncoder(Encoder):
    """B1 — SymbolicTextEncoder default (whitespace shatter, lowercase)."""
    name = "B1_bag_shatter"
    def __init__(self, dim=4096, k=64):
        self.dim, self.k = dim, k
        self.enc = ehc.SymbolicTextEncoder(dim, k, False, 2, False, 42)
        self.idx = ehc.BSCLSHIndex(dim, k, 8, 16, True)
        self.stored: Dict[int, str] = {}
    def ingest(self, texts, doc_ids):
        vecs = self.enc.encode_batch(list(texts))
        self.idx.add_items(vecs, list(doc_ids))
    def query(self, text, k):
        v = self.enc.encode(text)
        r = self.idx.knn_query(v, k)
        return list(r.ids), list(r.scores)


class NormStemBagEncoder(Encoder):
    """B2 — TextNormalizer.tokenize → PorterStemmer.stem_batch → encode_token."""
    name = "B2_norm_stem_bag"
    def __init__(self, dim=4096, k=64):
        self.dim, self.k = dim, k
        self.normalizer = ehc.TextNormalizer(True, True, True, False)
        self.encoder = ehc.SymbolicTextEncoder(dim, k, False, 2, False, 42)
        self.idx = ehc.BSCLSHIndex(dim, k, 8, 16, True)
    def _encode(self, text):
        toks = self.normalizer.tokenize(text)
        if not toks:
            return ehc.SparseVector(self.dim)
        vecs = [self.encoder.encode_token(t) for t in toks]
        return ehc.superpose(vecs) if len(vecs) > 1 else vecs[0]
    def ingest(self, texts, doc_ids):
        vecs = [self._encode(t) for t in texts]
        self.idx.add_items(vecs, list(doc_ids))
    def query(self, text, k):
        v = self._encode(text)
        r = self.idx.knn_query(v, k)
        return list(r.ids), list(r.scores)


class StructuralEncoder(Encoder):
    """C — v13 structural pipeline (slot + bigram + KV + optional Hebbian)."""
    def __init__(self, dim=4096, k=64, enable_hebbian=True, label="C_structural_v13"):
        self.name = label
        cfg = ehc.StructuralConfig()
        cfg.dim = dim; cfg.k = k; cfg.max_slots = 24
        cfg.enable_bigram = True
        cfg.enable_kv = True
        cfg.enable_hebbian = bool(enable_hebbian)
        cfg.hebbian_window = 5
        cfg.remove_stopwords = False
        self.pipe = ehc.StructuralPipelineV13(cfg)
    def ingest(self, texts, doc_ids):
        self.pipe.ingest_batch(list(texts), list(doc_ids))
    def query(self, text, k):
        r = self.pipe.query_text(text, k)
        return list(r.ids), list(r.scores)


# ─── Metrics ────────────────────────────────────────────────────────────

def recall_at_k(retrieved: List[int], gold: set, k: int) -> float:
    if not gold: return 0.0
    hits = sum(1 for rid in retrieved[:k] if rid in gold)
    return hits / min(len(gold), k)

def reciprocal_rank(retrieved: List[int], gold: set) -> float:
    for i, rid in enumerate(retrieved, start=1):
        if rid in gold:
            return 1.0 / i
    return 0.0

def ndcg_at_k(retrieved: List[int], gold: set, k: int) -> float:
    if not gold: return 0.0
    dcg = 0.0
    for i, rid in enumerate(retrieved[:k], start=1):
        if rid in gold:
            dcg += 1.0 / math.log2(i + 1)
    ideal_count = min(len(gold), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_count + 1))
    return dcg / idcg if idcg > 0 else 0.0


# ─── Runner ─────────────────────────────────────────────────────────────

def run_encoder(enc: Encoder, tweets: List[dict], queries: List[dict],
                top_k: int = 10) -> dict:
    # Ingest
    t0 = time.perf_counter()
    enc.ingest([t["text"] for t in tweets], [t["doc_id"] for t in tweets])
    t_ingest = (time.perf_counter() - t0) * 1000.0
    per_doc_ms = t_ingest / max(len(tweets), 1)

    # Query
    per_query = []
    q_lat = []
    for q in queries:
        gold = set(q["gold_doc_ids"])
        t_a = time.perf_counter()
        ids, scores = enc.query(q["text"], top_k)
        q_lat.append((time.perf_counter() - t_a) * 1000.0)
        per_query.append({
            "qid": q["qid"],
            "text": q["text"],
            "gold_count": len(gold),
            "retrieved": ids,
            "recall@10": recall_at_k(ids, gold, 10),
            "mrr":       reciprocal_rank(ids, gold),
            "ndcg@10":   ndcg_at_k(ids, gold, 10),
        })

    mean = lambda xs: statistics.mean(xs) if xs else 0.0

    return {
        "encoder": enc.name,
        "ingest_total_ms": round(t_ingest, 2),
        "ingest_ms_per_doc": round(per_doc_ms, 3),
        "query_p50_ms": round(statistics.median(q_lat), 3) if q_lat else 0.0,
        "query_mean_ms": round(mean(q_lat), 3),
        "recall@10_mean": round(mean(p["recall@10"] for p in per_query), 4),
        "mrr_mean":       round(mean(p["mrr"]       for p in per_query), 4),
        "ndcg@10_mean":   round(mean(p["ndcg@10"]   for p in per_query), 4),
        "per_query": per_query,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dim", type=int, default=4096)
    ap.add_argument("--k",   type=int, default=64)
    ap.add_argument("--top-k", type=int, default=10)
    args = ap.parse_args()

    tweets  = load_tweets()
    queries = load_queries()
    print(f"corpus: {len(tweets)} tweets, {len(queries)} queries, "
          f"dim={args.dim} k={args.k}\n")

    results = []
    for enc_factory in [
        lambda: BagShatterEncoder(args.dim, args.k),
        lambda: NormStemBagEncoder(args.dim, args.k),
        lambda: StructuralEncoder(args.dim, args.k, enable_hebbian=False,
                                    label="C-_structural_no_hebbian"),
        lambda: StructuralEncoder(args.dim, args.k, enable_hebbian=True,
                                    label="C_structural_v13_hebbian"),
    ]:
        enc = enc_factory()
        print(f"=== {enc.name} ===")
        r = run_encoder(enc, tweets, queries, args.top_k)
        results.append(r)
        print(f"  ingest: {r['ingest_total_ms']:>7.1f} ms total, "
              f"{r['ingest_ms_per_doc']:>6.3f} ms/doc")
        print(f"  query : p50 {r['query_p50_ms']:>5.2f} ms,  "
              f"mean {r['query_mean_ms']:>5.2f} ms")
        print(f"  retrieval: Recall@10={r['recall@10_mean']:.4f}  "
              f"MRR={r['mrr_mean']:.4f}  nDCG@10={r['ndcg@10_mean']:.4f}")
        print()

    # Summary table
    print("=" * 88)
    print(f"{'encoder':<32}  {'Recall@10':>10}  {'MRR':>8}  "
          f"{'nDCG@10':>8}  {'ingest/doc':>11}  {'q_p50':>8}")
    print("-" * 88)
    for r in results:
        print(f"{r['encoder']:<32}  {r['recall@10_mean']:>10.4f}  "
              f"{r['mrr_mean']:>8.4f}  {r['ndcg@10_mean']:>8.4f}  "
              f"{r['ingest_ms_per_doc']:>9.3f} ms  {r['query_p50_ms']:>6.2f} ms")
    print("=" * 88)

    # Dump JSON for later inspection
    out = HERE / "results.json"
    with open(out, "w") as f:
        json.dump({"tweets": len(tweets), "queries": len(queries),
                   "results": results}, f, indent=2)
    print(f"\nfull per-query results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
