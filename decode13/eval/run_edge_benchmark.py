"""End-to-end benchmark: ingest MjolnirPhotonics edge/staged/, run queries.

Exercises the v13 structural pipeline at production-ish scale (~315K
tweets) against the closed-loop-style bag-shatter baseline on the SAME
corpus, using auto-labeled AND-of-tokens gold.

Everything heavy is C++: `StructuralPipelineV13.ingest_text()` for v13,
`SymbolicTextEncoder.encode()` + `BSCLSHIndex` for the baseline.

Gold labeling is token-AND — a query-token set that must all appear in
the tweet. Same method used in the 200-tweet smoke eval. Lenient but
reproducible; user can hand-refine later.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import re
import resource
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Set, Tuple

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
for _d in (0, 1, 2):
    _p = _ROOT.parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc  # noqa: E402


STAGED = Path("/Users/stark/Quantum_Computing_Lab/MjolnirPhotonics/"
              "product.edge.analyst.bsc_old/edge_service/staged")

# Query set used against the full corpus. AND semantics on required_tokens.
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


def ascii_clean(s: str) -> str:
    return s.encode("ascii", "ignore").decode("ascii")


def first_sentence(raw: str) -> str:
    t = re.sub(r"(https?://\S+|@\w+|#\w+)", "", raw).strip()
    if not t:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", t)
    return parts[0][:400].strip()


def load_corpus(paths: List[Path], dedupe: bool = True,
                max_records: int | None = None):
    """Stream msgs.jsonl files. Returns list of dicts with 'doc_id','text'
    plus native_id/msg_id carry-through so downstream consumers (edge
    UI, detail lookups) can resolve back to the source record."""
    seen: Set[str] = set()
    out: List[dict] = []
    did = 0
    for p in paths:
        with open(p) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                raw = (rec.get("message_text_translated") or
                       rec.get("message_text") or "")
                text = ascii_clean(first_sentence(raw))
                if len(text) < 20:
                    continue
                if dedupe:
                    if text in seen:
                        continue
                    seen.add(text)

                # author may be dict OR string in this corpus.
                a = rec.get("author")
                if isinstance(a, dict):
                    author = (a.get("username") or a.get("name")
                              or a.get("entity_id") or "")
                else:
                    author = str(a or "")

                media_files = rec.get("media_filenames") or rec.get("media_files") or []
                media_url = media_files[0] if isinstance(media_files, list) and media_files else ""

                out.append({
                    "doc_id":     did,
                    "text":       text,
                    "raw":        raw[:500],
                    "url":        rec.get("url", ""),
                    "author":     author,
                    "site":       rec.get("site", rec.get("type", "")),
                    "posted_at":  rec.get("posted_at", ""),
                    "msg_id":     rec.get("id", ""),
                    "native_id":  rec.get("native_id", ""),
                    "media_url":  media_url,
                })
                did += 1
                if max_records and did >= max_records:
                    return out
    return out


def build_gold(corpus: List[dict], queries: List[Tuple[str, List[str]]]
               ) -> List[dict]:
    tokens_by_doc = {
        r["doc_id"]: set(re.findall(r"[a-z0-9]+", r["text"].lower()))
        for r in corpus
    }
    out: List[dict] = []
    for qid, (text, req) in enumerate(queries):
        # Token-AND semantics with prefix match: "regim" matches "regime".
        def has_all(doc_toks: Set[str]) -> bool:
            for r in req:
                # Exact or prefix presence
                if r in doc_toks:
                    continue
                if any(t.startswith(r) for t in doc_toks):
                    continue
                return False
            return True

        gold = [did for did, toks in tokens_by_doc.items() if has_all(toks)]
        out.append({"qid": qid, "text": text, "required_tokens": req,
                    "gold_doc_ids": gold, "gold_count": len(gold)})
    return out


# ─── Encoders ────────────────────────────────────────────────────────────

class BagShatter:
    """Baseline: SymbolicTextEncoder default (lowercased whitespace shatter)."""
    name = "B1_bag_shatter"
    def __init__(self, dim, k):
        self.enc = ehc.SymbolicTextEncoder(dim, k, False, 2, False, 42)
        self.idx = ehc.BSCLSHIndex(dim, k, 8, 16, True)
        self.dim = dim
    def ingest_batch(self, texts, ids, batch=1000):
        for bs in range(0, len(texts), batch):
            be = min(bs + batch, len(texts))
            vecs = self.enc.encode_batch(texts[bs:be])
            self.idx.add_items(vecs, ids[bs:be])
    def query(self, text, k=10):
        v = self.enc.encode(text)
        r = self.idx.knn_query(v, k)
        return list(r.ids), list(r.scores)


class StructuralV13:
    """v13 structural pipeline (slot + bigram + KV + Hebbian).

    Config flows through decode13.build_structural_config, so A81_DIM /
    A81_K / A81_LSH_* from config.env take effect here unless a CLI
    override forces a value.
    """
    def __init__(self, dim=None, k=None, enable_hebbian=True,
                 label="C_structural_v13_hebbian", n_threads=0,
                 hebbian_topk=3):
        self.name = label
        self.n_threads = int(n_threads)
        self.enable_hebbian = bool(enable_hebbian)
        self.hebbian_topk = int(hebbian_topk)
        from decode13 import build_structural_config
        cfg = build_structural_config(
            dim=dim, k=k,
            max_slots=24,
            enable_bigram=True,
            enable_kv=True,
            enable_hebbian=self.enable_hebbian,
            hebbian_window=5,
        )
        self.cfg = cfg
        self.pipe = ehc.StructuralPipelineV13(cfg)
    def ingest_batch(self, texts, ids, batch=10000):
        # Use the parallel path — concurrent encode + serial index write.
        for bs in range(0, len(texts), batch):
            be = min(bs + batch, len(texts))
            self.pipe.ingest_batch_parallel(texts[bs:be], ids[bs:be],
                                             self.n_threads)
    def query(self, text, k=10):
        if self.enable_hebbian:
            r = self.pipe.query_text_expanded(text, k, self.hebbian_topk)
        else:
            r = self.pipe.query_text(text, k)
        return list(r.ids), list(r.scores)


# ─── Metrics ─────────────────────────────────────────────────────────────

def recall_at_k(ret, gold, k):
    if not gold: return 0.0
    hits = sum(1 for r in ret[:k] if r in gold)
    return hits / min(len(gold), k)

def reciprocal_rank(ret, gold):
    for i, r in enumerate(ret, 1):
        if r in gold: return 1.0 / i
    return 0.0

def ndcg_at_k(ret, gold, k):
    if not gold: return 0.0
    dcg = sum(1.0 / math.log2(i + 1) for i, r in enumerate(ret[:k], 1)
              if r in gold)
    ideal = min(len(gold), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal + 1))
    return dcg / idcg if idcg > 0 else 0.0


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024


def run_encoder(enc, corpus, queries, top_k=10, progress_every=20_000):
    texts = [r["text"] for r in corpus]
    ids   = [r["doc_id"] for r in corpus]
    t0 = time.perf_counter()
    # Progress during ingest
    B = 1000
    for bs in range(0, len(texts), B):
        be = min(bs + B, len(texts))
        enc.ingest_batch(texts[bs:be], ids[bs:be], batch=B)
        if be % progress_every == 0 or be == len(texts):
            el = time.perf_counter() - t0
            rate = be / el if el > 0 else 0
            print(f"    [{enc.name}] ingested {be:>7,}/{len(texts):,} "
                  f"({el:.1f}s, {rate:,.0f} doc/s)  RSS={rss_mb():.0f} MB",
                  flush=True)
    t_ingest = time.perf_counter() - t0

    q_lat = []
    per_q = []
    for q in queries:
        gold = set(q["gold_doc_ids"])
        t_a = time.perf_counter()
        ret, _ = enc.query(q["text"], top_k)
        q_lat.append((time.perf_counter() - t_a) * 1000.0)
        per_q.append({
            "qid": q["qid"], "text": q["text"], "gold_count": len(gold),
            "retrieved": ret,
            "recall@10": recall_at_k(ret, gold, 10),
            "mrr":       reciprocal_rank(ret, gold),
            "ndcg@10":   ndcg_at_k(ret, gold, 10),
        })

    mean = lambda xs: statistics.mean(xs) if xs else 0.0
    return {
        "encoder": enc.name,
        "n_docs": len(corpus),
        "ingest_total_s": round(t_ingest, 2),
        "ingest_rate_per_s": round(len(corpus)/t_ingest if t_ingest else 0, 1),
        "ingest_ms_per_doc": round(t_ingest*1000/max(len(corpus),1), 3),
        "query_p50_ms":  round(statistics.median(q_lat), 2) if q_lat else 0.0,
        "query_p85_ms":  (round(statistics.quantiles(q_lat, n=100)[84], 2)
                          if len(q_lat) >= 100 else round(max(q_lat), 2)),
        "query_mean_ms": round(mean(q_lat), 2),
        "recall@10_mean": round(mean(p["recall@10"] for p in per_q), 4),
        "mrr_mean":       round(mean(p["mrr"]       for p in per_q), 4),
        "ndcg@10_mean":   round(mean(p["ndcg@10"]   for p in per_q), 4),
        "peak_rss_mb":    round(rss_mb(), 0),
        "per_query":      per_q,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dim", type=int, default=None,
                    help="Override A81_DIM from config.env (default: use config)")
    ap.add_argument("--k", type=int, default=None,
                    help="Override A81_K from config.env (default: use config)")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--max-records", type=int, default=0,
                    help="0 = use all; otherwise cap corpus size")
    ap.add_argument("--skip-baseline", action="store_true",
                    help="Only run the v13 structural encoder.")
    ap.add_argument("--hebbian", action="store_true",
                    help="Enable Hebbian co-occurrence layer + query expansion.")
    ap.add_argument("--threads", type=int, default=0,
                    help="Thread count for parallel ingest (0 = HW concurrency)")
    ap.add_argument("--out", type=str, default=None,
                    help="Persist v13 pipeline (cfg + hebbian + lsh) to this "
                         "directory. If omitted, reads A81_INDEX_PATH or "
                         "falls back to skipping persistence.")
    args = ap.parse_args()

    # Resolve dim/k from config.env when not overridden on CLI.
    if args.dim is None or args.k is None:
        try:
            sys.path.insert(0, str(_ROOT))
            from config import cfg as _cfg  # noqa: E402
            args.dim = args.dim if args.dim is not None else _cfg.DIM
            args.k   = args.k   if args.k   is not None else _cfg.K
        except Exception:
            args.dim = args.dim or 16384
            args.k   = args.k   or 128
    print(f"[config] dim={args.dim} k={args.k} hebbian={args.hebbian} "
          f"threads={args.threads or 'auto'}")

    paths = [STAGED / "msgs.jsonl", STAGED / "data3" / "msgs.jsonl"]
    paths = [p for p in paths if p.exists()]
    print(f"sources: {[str(p) for p in paths]}")

    t0 = time.perf_counter()
    corpus = load_corpus(paths, dedupe=True,
                          max_records=args.max_records or None)
    t_load = time.perf_counter() - t0
    print(f"loaded {len(corpus):,} unique first-sentences in {t_load:.1f}s "
          f"(RSS {rss_mb():.0f} MB)")

    queries = build_gold(corpus, QUERIES)
    usable = [q for q in queries if 2 <= q["gold_count"] <= 0.3 * len(corpus)]
    dropped = [q for q in queries if q not in usable]
    print(f"queries: {len(usable)} usable (2 ≤ gold ≤ 30%), "
          f"{len(dropped)} dropped")
    for q in dropped:
        print(f"  dropped q{q['qid']} {q['text']!r}: gold={q['gold_count']}")
    for q in usable:
        print(f"  q{q['qid']:2d}  gold={q['gold_count']:5d}  {q['text']!r}")
    print()

    results = []

    if not args.skip_baseline:
        print(f"══════ B1 bag_shatter ═══════════════════════════════════")
        enc = BagShatter(args.dim, args.k)
        results.append(run_encoder(enc, corpus, usable, args.top_k))
        del enc; gc.collect()
        print()

    label = "C_structural_v13_hebbian" if args.hebbian else "C-_structural_v13"
    print(f"══════ {label} (threads={args.threads or 'auto'}) ═════════════")
    enc = StructuralV13(args.dim, args.k, enable_hebbian=args.hebbian,
                         label=label, n_threads=args.threads)
    results.append(run_encoder(enc, corpus, usable, args.top_k))
    print()

    # Summary
    print("=" * 108)
    print(f"{'encoder':<34}  {'n_docs':>8}  {'ingest_rate/s':>14}  "
          f"{'ms/doc':>7}  {'q_p50':>7}  {'Recall@10':>10}  {'MRR':>7}  "
          f"{'nDCG@10':>7}")
    print("-" * 108)
    for r in results:
        print(f"{r['encoder']:<34}  {r['n_docs']:>8,}  "
              f"{r['ingest_rate_per_s']:>12,.0f}/s  "
              f"{r['ingest_ms_per_doc']:>6.2f}  "
              f"{r['query_p50_ms']:>5.2f}ms  "
              f"{r['recall@10_mean']:>10.4f}  {r['mrr_mean']:>7.4f}  "
              f"{r['ndcg@10_mean']:>7.4f}")
    print("=" * 108)

    # Per-query details for v13 (the result that matters)
    print("\nPER-QUERY detail (v13):")
    v13 = next(r for r in results if r["encoder"].startswith("C"))
    for p in v13["per_query"]:
        print(f"  q{p['qid']:2d}  gold={p['gold_count']:>5}  "
              f"R@10={p['recall@10']:.3f}  MRR={p['mrr']:.3f}  "
              f"nDCG@10={p['ndcg@10']:.3f}  |  {p['text']}")

    # Persistence: save the v13 pipeline + doc_id-aligned corpus sidecar
    # to --out (or A81_INDEX_PATH). Sidecar is consumed by the edge-compat
    # QueryService shim at G.A8.1/decode/query_service.py for metadata
    # lookup (the pipeline itself only stores vectors + ids).
    persist_dir = args.out or os.environ.get("A81_INDEX_PATH") or ""
    if persist_dir:
        v13_enc = next((e for e in [enc] if hasattr(e, "pipe")), None)
        if v13_enc is None:
            print(f"  [persist] no v13 encoder in run; skipping")
        else:
            pdir = Path(persist_dir) / "structural_v13"
            pdir.mkdir(parents=True, exist_ok=True)
            t_p = time.perf_counter()
            v13_enc.pipe.save(str(pdir))
            print(f"  [persist] saved pipeline to {pdir} in "
                  f"{time.perf_counter()-t_p:.1f}s")

            t_c = time.perf_counter()
            cpath = Path(persist_dir) / "corpus.jsonl"
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
            print(f"  [persist] wrote corpus sidecar ({len(corpus):,} rows) "
                  f"to {cpath} in {time.perf_counter()-t_c:.1f}s")

    out = Path(__file__).resolve().parent / "edge_benchmark_results.json"
    with open(out, "w") as f:
        json.dump({"corpus_size": len(corpus), "results": results}, f, indent=2)
    print(f"\nfull results: {out}")


if __name__ == "__main__":
    sys.exit(main())
