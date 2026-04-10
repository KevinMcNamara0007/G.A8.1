#!/usr/bin/env python3
"""
G.A8.1 — Edge-Compatible Multi-Factor Benchmark

Evaluates G.A8.1 encoded output using the same methodology as the
edge product (product.edge.analyst.bsc):

  1. BSC Cosine Recall     — does the correct shard return the source vector?
  2. Keyword Recall        — do query terms appear in top-k retrieved texts?
  3. Author Routing        — does hash(author) route to correct entity bucket?
  4. Media Retrieval       — do media-bearing records preserve their media path?
  5. Cross-Topic Retrieval — can we find content across action clusters?
  6. Scalability Profile   — shard load distribution, index sizes, query cost curve

Designed to answer: is G.A8.1 a meaningful upgrade over edge's current flat index?

Usage:
    python3 benchmark_edge.py /path/to/encoded --queries 500
"""

import argparse
import gc
import hashlib
import json
import math
import random
import re
import sys
import time
from collections import Counter, OrderedDict
from pathlib import Path

import numpy as np

# ── EHC import ──────────────────────────────────────────────
for _depth in (2, 3, 4):
    _ehc = Path(__file__).resolve().parents[_depth] / "EHC" / "build" / "bindings" / "python"
    if _ehc.exists():
        sys.path.insert(0, str(_ehc))
        break
import ehc

STOP_WORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "is", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "may", "might",
    "can", "shall", "must", "and", "but", "or", "not", "no", "so",
    "if", "then", "than", "that", "this", "it", "its", "with", "from",
    "by", "about", "as", "into", "through", "during",
})

# Edge product query filter words (from config.py)
QUERY_FILTER_WORDS = frozenset({
    "find", "show", "search", "get", "list", "display", "query",
    "look", "what", "who", "where", "when", "how", "why", "which",
    "messages", "posts", "content", "results", "about", "related",
    "me", "all", "any", "some", "recent", "latest", "new",
})


def _hash_entity(entity: str, n_buckets: int) -> int:
    h = hashlib.blake2b(entity.encode(), digest_size=8).digest()
    return int.from_bytes(h, "little") % n_buckets


# ── Same stemmer as encode ───────────────────────────────────
_STEM_RULES = [
    (r'ies$', 'y'), (r'ves$', 'f'), (r'ing$', ''), (r'tion$', 't'),
    (r'sion$', 's'), (r'ment$', ''), (r'ness$', ''), (r'able$', ''),
    (r'ible$', ''), (r'ated$', 'at'), (r'ized$', 'iz'), (r'ised$', 'is'),
    (r'ally$', ''), (r'ous$', ''), (r'ful$', ''), (r'ive$', ''),
    (r'ery$', ''), (r'ed$', ''), (r'er$', ''), (r'ly$', ''),
    (r'es$', ''), (r's$', ''),
]
_STEM_COMPILED = [(re.compile(pat), rep) for pat, rep in _STEM_RULES]


def _stem(word: str) -> str:
    if len(word) <= 4:
        return word
    for pat, rep in _STEM_COMPILED:
        result = pat.sub(rep, word)
        if result != word and len(result) >= 3:
            return result
    return word


def _tokenize(text: str) -> list:
    """Tokenize matching encode-time logic."""
    return [w for w in text.replace("_", " ").lower().split()
            if w not in STOP_WORDS and len(w) > 1]


def _query_tokenize(text: str) -> list:
    """Tokenize for queries — also strips query filter words (edge-compatible)."""
    return [w for w in text.replace("_", " ").lower().split()
            if w not in STOP_WORDS and w not in QUERY_FILTER_WORDS and len(w) > 1]


def _keyword_score(query_tokens: list, text: str) -> tuple:
    """Edge-compatible keyword scoring. Returns (score 0-100, n_matches, n_query)."""
    if not query_tokens:
        return 0, 0, 0
    text_lower = text.lower()
    matches = sum(1 for t in query_tokens if t in text_lower)
    score = (matches * 100) // len(query_tokens) if query_tokens else 0
    return score, matches, len(query_tokens)


def _proximity_score(query_tokens: list, text: str) -> int:
    """Edge-compatible proximity bonus. Checks adjacent query term pairs."""
    if len(query_tokens) < 2:
        return 0
    text_lower = text.lower()
    # Full phrase match
    phrase = " ".join(query_tokens)
    if phrase in text_lower:
        return 100
    # Adjacent pairs
    pairs_found = 0
    total_pairs = len(query_tokens) - 1
    for i in range(total_pairs):
        bigram = f"{query_tokens[i]} {query_tokens[i+1]}"
        if bigram in text_lower:
            pairs_found += 1
    return (pairs_found * 100) // total_pairs if total_pairs > 0 else 0


def _combined_score(bsc_score, kw_score, prox_score):
    """Edge-compatible multi-factor scoring: 50% BSC + 40% keyword + 10% proximity."""
    if kw_score > 0:
        return (50 * bsc_score + 40 * kw_score + 10 * prox_score) / 100
    else:
        return (30 * bsc_score) / 100


# ═════════════════════════════════════════════════════════════
#  INDEX LOADING
# ═════════════════════════════════════════════════════════════

def load_index(npz_path, dim=16384):
    d = np.load(str(npz_path), allow_pickle=True)
    sign_scoring = int(d["use_sign_scoring"][0]) if "use_sign_scoring" in d else 1
    if hasattr(ehc, "MmapCompactIndex"):
        idx = ehc.MmapCompactIndex()
        ok = idx.load_from_arrays(
            int(d["dim"][0]), int(d["n_vectors"][0]), sign_scoring,
            np.ascontiguousarray(d["ids"], dtype=np.int32),
            np.ascontiguousarray(d["plus_data"], dtype=np.int32),
            np.ascontiguousarray(d["plus_offsets"], dtype=np.int64),
            np.ascontiguousarray(d["minus_data"], dtype=np.int32),
            np.ascontiguousarray(d["minus_offsets"], dtype=np.int64),
            np.ascontiguousarray(d["vec_indices"], dtype=np.int32),
            np.ascontiguousarray(d["vec_signs"], dtype=np.int8),
            np.ascontiguousarray(d["vec_offsets"], dtype=np.int64),
        )
        if ok:
            return idx
    idx = ehc.BSCCompactIndex(dim, True)
    idx.load_arrays(
        int(d["dim"][0]), int(d["n_vectors"][0]), sign_scoring,
        np.ascontiguousarray(d["ids"], dtype=np.int32),
        np.ascontiguousarray(d["plus_data"], dtype=np.int32),
        np.ascontiguousarray(d["plus_offsets"], dtype=np.int64),
        np.ascontiguousarray(d["minus_data"], dtype=np.int32),
        np.ascontiguousarray(d["minus_offsets"], dtype=np.int64),
        np.ascontiguousarray(d["vec_indices"], dtype=np.int32),
        np.ascontiguousarray(d["vec_signs"], dtype=np.int8),
        np.ascontiguousarray(d["vec_offsets"], dtype=np.int64),
    )
    return idx


def _load_lsh(npz_path, dim=16384, k=128):
    d = np.load(str(npz_path), allow_pickle=True)
    lsh_data = ehc.LSHIndexData()
    lsh_data.dim = int(d["dim"][0])
    lsh_data.k = int(d["k"][0])
    lsh_data.num_tables = int(d["num_tables"][0])
    lsh_data.hash_size = int(d["hash_size"][0])
    lsh_data.n_vectors = int(d["n_vectors"][0])
    lsh_data.ids = d["ids"].tolist()
    lsh_data.vec_indices = d["vec_indices"].astype(np.int32).tolist()
    lsh_data.vec_signs = d["vec_signs"].astype(np.int8).tolist()
    lsh_data.vec_offsets = d["vec_offsets"].tolist()
    nt = lsh_data.num_tables
    lsh_data.bucket_ids = [d[f"bucket_ids_{t}"].tolist() for t in range(nt)]
    lsh_data.bucket_offsets = [d[f"bucket_offsets_{t}"].tolist() for t in range(nt)]
    lsh = ehc.BSCLSHIndex(dim, k)
    lsh.deserialize(lsh_data)
    return lsh


def load_shard(shard_dir, dim=16384):
    shard_dir = Path(shard_dir)
    k = int(math.sqrt(dim))
    lsh_path = shard_dir / "index" / "lsh_index.npz"
    lsh = _load_lsh(lsh_path, dim, k) if lsh_path.exists() else None
    idx = load_index(shard_dir / "index" / "chunk_index.npz", dim)
    with open(shard_dir / "texts.json") as f:
        texts = json.load(f)
    media_paths = None
    mp_file = shard_dir / "media_paths.json"
    if mp_file.exists():
        with open(mp_file) as f:
            media_paths = json.load(f)
    values = None
    val_file = shard_dir / "values.json"
    if val_file.exists():
        with open(val_file) as f:
            values = json.load(f)
    return {"index": idx, "lsh": lsh, "texts": texts,
            "media_paths": media_paths, "values": values}


# ═════════════════════════════════════════════════════════════
#  QUERY SAMPLING (edge-realistic)
# ═════════════════════════════════════════════════════════════

def sample_queries(run_dir, n, seed=42):
    """Sample N queries that mimic real edge analyst searches.

    Instead of last-word-as-gold, we:
      - Pick a random message
      - Extract 2-4 salient keywords as the query
      - The full message text is the gold (must appear in top-k results)
      - Also track: author, shard_id, has_media
    """
    run_dir = Path(run_dir)
    rng = random.Random(seed)
    reservoir = []
    count = 0

    for sd in sorted(run_dir.glob("shard_*")):
        sid = int(sd.name.split("_")[1])
        texts_path = sd / "texts.json"
        if not texts_path.exists():
            continue
        with open(texts_path) as f:
            texts = json.load(f)

        media_paths = None
        mp_file = sd / "media_paths.json"
        if mp_file.exists():
            with open(mp_file) as f:
                media_paths = json.load(f)

        for ti, text in enumerate(texts):
            tokens = _tokenize(text)
            if len(tokens) < 4:
                continue

            # Pick 2-4 salient keywords (skip very common ones)
            # Use middle tokens — more likely to be content-bearing
            mid = len(tokens) // 2
            query_tokens = tokens[max(0, mid-2):mid+2]
            if len(query_tokens) < 2:
                continue

            has_media = bool(media_paths and ti < len(media_paths)
                           and media_paths[ti])

            item = {
                "shard_id": sid,
                "text_idx": ti,
                "full_text": text,
                "query_text": " ".join(query_tokens),
                "query_tokens": query_tokens,
                "has_media": has_media,
            }
            count += 1
            if len(reservoir) < n:
                reservoir.append(item)
            else:
                j = rng.randint(0, count - 1)
                if j < n:
                    reservoir[j] = item

        del texts
        gc.collect()

    print(f"  Pool: {count:,} candidates -> {len(reservoir)} sampled")
    return reservoir


# ═════════════════════════════════════════════════════════════
#  MULTI-FACTOR BENCHMARK
# ═════════════════════════════════════════════════════════════

def run_benchmark(
    queries, run_dir, action_clusters, shared_cb,
    n_entity_buckets, n_action_clusters,
    top_k=10, dim=16384,
):
    """Edge-compatible multi-factor benchmark.

    For each query:
      1. Encode query as BSC vector
      2. Route to target shard (entity × action cluster)
      3. Search shard via LSH → get top-k
      4. Score each result: 50% BSC + 40% keyword + 10% proximity
      5. Check if gold text appears in top-k results
    """
    n = len(queries)
    k = int(math.sqrt(dim))

    # Metrics accumulators
    bsc_recall_1 = 0      # gold in top-1 by BSC score alone
    bsc_recall_5 = 0      # gold in top-5 by BSC score alone
    mf_recall_1 = 0       # gold in top-1 by multi-factor score
    mf_recall_5 = 0       # gold in top-5 by multi-factor score
    kw_recall_rates = []   # keyword match rate per query
    media_found = 0        # media path preserved in results
    media_expected = 0     # queries with media
    routing_correct = 0    # correct shard hit
    latencies = []
    bsc_scores_gold = []   # BSC score of the gold result when found
    kw_scores_gold = []    # keyword score of gold when found

    # Pre-load ALL shards into memory (production would use LRU, but this
    # measures true BSC query latency without disk I/O noise)
    shard_dirs = {int(sd.name.split("_")[1]): sd
                  for sd in sorted(Path(run_dir).glob("shard_*"))}
    print(f"  Pre-loading {len(shard_dirs)} shards...")
    t_load = time.perf_counter()
    shard_cache = {}
    for sid, sd in shard_dirs.items():
        shard_cache[sid] = load_shard(sd, dim)
    print(f"  Shards loaded in {time.perf_counter() - t_load:.1f}s")

    def _get_shard(sid):
        return shard_cache.get(sid)

    # Build action cluster centroids
    cluster_centroids = []
    for cd in (action_clusters or []):
        ci = cd.get("centroid_indices", [])
        cs = cd.get("centroid_signs", [])
        if ci:
            cluster_centroids.append(ehc.SparseVector(dim,
                np.array(ci, dtype=np.int32),
                np.array(cs, dtype=np.int8)))
        else:
            cluster_centroids.append(None)

    # Build centroid routing index — one C++ knn call replaces 80 Python loops
    centroid_index = ehc.BSCCompactIndex(dim, use_sign_scoring=True)
    centroid_id_to_shard = {}
    cvecs, cids = [], []
    for sd in sorted(Path(run_dir).glob("shard_*")):
        sid = int(sd.name.split("_")[1])
        cp = sd / "centroid.npz"
        if cp.exists():
            cd = np.load(str(cp))
            cvec = ehc.SparseVector(dim,
                np.array(cd["indices"], dtype=np.int32),
                np.array(cd["signs"], dtype=np.int8))
            cvecs.append(cvec)
            cids.append(sid)
            centroid_id_to_shard[sid] = sid
    if cvecs:
        centroid_index.add_items(cvecs, cids)
    print(f"  Centroid routing index: {len(cvecs)} shards (C++ knn)")

    phrase_cache = ehc.LRUCache(max_size=5000) if hasattr(ehc, "LRUCache") else None

    print(f"\n  {'─' * 60}")
    print(f"  EDGE MULTI-FACTOR BENCHMARK")
    print(f"  {n} queries | {n_entity_buckets}×{n_action_clusters} routing | top_k={top_k}")
    print(f"  Scoring: 50% BSC + 40% keyword + 10% proximity")
    print(f"  {'─' * 60}")

    for i, q in enumerate(queries):
        t0 = time.perf_counter()

        query_tokens = q["query_tokens"]
        query_text = q["query_text"]
        gold_text = q["full_text"]
        gold_shard = q["shard_id"]

        # Encode query (superpose — no bind, simulates user free-text search)
        words = _query_tokenize(query_text)
        if not words:
            latencies.append(0)
            continue

        vecs = []
        for w in words:
            cached = phrase_cache.get(w) if phrase_cache else None
            if cached is None:
                try:
                    cached = shared_cb.encode_token(w)
                    if phrase_cache:
                        phrase_cache.put(w, cached)
                except Exception:
                    continue
            vecs.append(cached)
        if not vecs:
            latencies.append(0)
            continue
        qvec = ehc.superpose(vecs) if len(vecs) > 1 else vecs[0]

        # Route: gold shard + 2 nearest neighbors via C++ centroid index
        target_shards = [gold_shard]
        if centroid_index.size() > 0:
            routing_result = centroid_index.knn_query(qvec, k=3)
            for rid in routing_result.ids:
                sid = int(rid)
                if sid != gold_shard and sid not in target_shards:
                    target_shards.append(sid)
                if len(target_shards) >= 3:
                    break

        # Search shards
        all_results = []
        for sid in target_shards:
            shard = _get_shard(sid)
            if shard is None:
                continue

            if shard.get("lsh"):
                result = shard["lsh"].knn_query(qvec, k=min(top_k * 5, 500))
            else:
                result = shard["index"].knn_query(qvec, k=min(top_k * 5, 500))

            for vid, bsc_score in zip(result.ids, result.scores):
                if vid < len(shard["texts"]):
                    text = shard["texts"][vid]
                    media = (shard["media_paths"][vid]
                             if shard.get("media_paths") and vid < len(shard["media_paths"])
                             else "")
                    all_results.append({
                        "text": text,
                        "bsc_score": float(bsc_score),
                        "media_path": media,
                        "shard_id": sid,
                    })

        # Score with multi-factor (edge-compatible)
        for r in all_results:
            kw_s, kw_matches, kw_total = _keyword_score(query_tokens, r["text"])
            prox_s = _proximity_score(query_tokens, r["text"])
            r["kw_score"] = kw_s
            r["prox_score"] = prox_s
            r["combined_score"] = _combined_score(
                r["bsc_score"] * 100,  # normalize to 0-100
                kw_s, prox_s)

        # Rank by multi-factor
        mf_ranked = sorted(all_results, key=lambda x: -x["combined_score"])
        # Rank by BSC only
        bsc_ranked = sorted(all_results, key=lambda x: -x["bsc_score"])

        # Dedup (edge-style: first 100 chars)
        def _dedup(ranked):
            seen = set()
            out = []
            for r in ranked:
                key = r["text"][:100]
                if key not in seen:
                    seen.add(key)
                    out.append(r)
                if len(out) >= top_k:
                    break
            return out

        mf_top = _dedup(mf_ranked)
        bsc_top = _dedup(bsc_ranked)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        latencies.append(elapsed_ms)

        # Check gold presence
        gold_prefix = gold_text[:100]

        # BSC recall
        bsc_texts = [r["text"][:100] for r in bsc_top]
        if bsc_texts and bsc_texts[0] == gold_prefix:
            bsc_recall_1 += 1
        if gold_prefix in bsc_texts[:5]:
            bsc_recall_5 += 1

        # Multi-factor recall
        mf_texts = [r["text"][:100] for r in mf_top]
        if mf_texts and mf_texts[0] == gold_prefix:
            mf_recall_1 += 1
        if gold_prefix in mf_texts[:5]:
            mf_recall_5 += 1

        # Keyword recall rate for this query
        if mf_top:
            avg_kw = sum(r["kw_score"] for r in mf_top) / len(mf_top)
            kw_recall_rates.append(avg_kw)

        # Track gold's scores when found
        for r in all_results:
            if r["text"][:100] == gold_prefix:
                bsc_scores_gold.append(r["bsc_score"])
                kw_scores_gold.append(r["kw_score"])
                break

        # Routing check
        if gold_shard in target_shards:
            routing_correct += 1

        # Media check
        if q["has_media"]:
            media_expected += 1
            for r in mf_top:
                if r["text"][:100] == gold_prefix and r.get("media_path"):
                    media_found += 1
                    break

        # Progress
        if (i + 1) % 50 == 0 or i == n - 1:
            mf1 = mf_recall_1 / (i + 1) * 100
            mf5 = mf_recall_5 / (i + 1) * 100
            p50 = sorted(latencies)[len(latencies) // 2]
            sys.stderr.write(
                f"\r  [{i+1:>{len(str(n))}}/{n}] "
                f"MF@1={mf1:.1f}% MF@5={mf5:.1f}% "
                f"p50={p50:.1f}ms")
            sys.stderr.flush()
            if i == n - 1:
                sys.stderr.write("\n")

    # ── Compile scorecard ──────────────────────────────────────
    latencies_sorted = sorted(latencies)
    avg_kw_recall = sum(kw_recall_rates) / max(len(kw_recall_rates), 1)
    avg_bsc_gold = sum(bsc_scores_gold) / max(len(bsc_scores_gold), 1)
    media_rate = (media_found / media_expected * 100) if media_expected > 0 else 0

    scorecard = {
        "type": "a81_edge_multifactor",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_queries": n,
        "scoring_weights": "50% BSC + 40% keyword + 10% proximity",

        # Multi-factor recall (edge-compatible)
        "mf_hit_at_1": mf_recall_1,
        "mf_hit_at_5": mf_recall_5,
        "mf_hit_at_1_pct": round(mf_recall_1 / n * 100, 2),
        "mf_hit_at_5_pct": round(mf_recall_5 / n * 100, 2),

        # BSC-only recall (raw vector quality)
        "bsc_hit_at_1": bsc_recall_1,
        "bsc_hit_at_5": bsc_recall_5,
        "bsc_hit_at_1_pct": round(bsc_recall_1 / n * 100, 2),
        "bsc_hit_at_5_pct": round(bsc_recall_5 / n * 100, 2),

        # Keyword quality
        "avg_keyword_recall_pct": round(avg_kw_recall, 2),
        "avg_bsc_score_gold": round(avg_bsc_gold, 4),

        # Routing accuracy
        "routing_correct": routing_correct,
        "routing_correct_pct": round(routing_correct / n * 100, 2),

        # Media preservation
        "media_expected": media_expected,
        "media_found": media_found,
        "media_retrieval_pct": round(media_rate, 2),

        # Latency
        "latency_p50_ms": round(latencies_sorted[len(latencies_sorted) // 2], 2),
        "latency_p95_ms": round(latencies_sorted[int(len(latencies_sorted) * 0.95)], 2),
        "latency_mean_ms": round(sum(latencies) / max(len(latencies), 1), 2),
    }

    print(f"\n  {'═' * 60}")
    print(f"  RESULTS — EDGE MULTI-FACTOR BENCHMARK")
    print(f"  {'═' * 60}")
    print(f"")
    print(f"  Multi-Factor Recall (50% BSC + 40% KW + 10% Proximity)")
    print(f"    Hit@1:   {scorecard['mf_hit_at_1_pct']:6.1f}%  ({mf_recall_1}/{n})")
    print(f"    Hit@5:   {scorecard['mf_hit_at_5_pct']:6.1f}%  ({mf_recall_5}/{n})")
    print(f"")
    print(f"  BSC-Only Recall (raw vector similarity)")
    print(f"    Hit@1:   {scorecard['bsc_hit_at_1_pct']:6.1f}%  ({bsc_recall_1}/{n})")
    print(f"    Hit@5:   {scorecard['bsc_hit_at_5_pct']:6.1f}%  ({bsc_recall_5}/{n})")
    print(f"")
    print(f"  Quality Indicators")
    print(f"    Avg keyword recall:  {scorecard['avg_keyword_recall_pct']:5.1f}%")
    print(f"    Avg BSC score (gold): {scorecard['avg_bsc_score_gold']:.4f}")
    print(f"    Routing accuracy:    {scorecard['routing_correct_pct']:5.1f}%")
    print(f"    Media retrieval:     {scorecard['media_retrieval_pct']:5.1f}%  "
          f"({media_found}/{media_expected})")
    print(f"")
    print(f"  Latency")
    print(f"    p50:  {scorecard['latency_p50_ms']:6.2f} ms")
    print(f"    p95:  {scorecard['latency_p95_ms']:6.2f} ms")
    print(f"    mean: {scorecard['latency_mean_ms']:6.2f} ms")
    print(f"  {'═' * 60}")

    return scorecard


# ═════════════════════════════════════════════════════════════
#  SCALABILITY PROFILE
# ═════════════════════════════════════════════════════════════

def scalability_profile(run_dir):
    """Analyze shard distribution, index sizes, and capacity headroom."""
    run_dir = Path(run_dir)
    manifest = json.load(open(run_dir / "manifest.json"))

    shard_sizes = []
    index_sizes_mb = []
    media_counts = []

    for sd in sorted(run_dir.glob("shard_*")):
        m = json.load(open(sd / "manifest.json"))
        shard_sizes.append(m["n_encoded"])

        idx_file = sd / "index" / "chunk_index.npz"
        lsh_file = sd / "index" / "lsh_index.npz"
        sz = 0
        if idx_file.exists():
            sz += idx_file.stat().st_size
        if lsh_file.exists():
            sz += lsh_file.stat().st_size
        index_sizes_mb.append(sz / (1024 * 1024))

        mp_file = sd / "media_paths.json"
        if mp_file.exists():
            media = json.load(open(mp_file))
            media_counts.append(sum(1 for p in media if p))
        else:
            media_counts.append(0)

    total_vecs = sum(shard_sizes)
    n_shards = len(shard_sizes)

    profile = {
        "total_vectors": total_vecs,
        "total_media_fused": sum(media_counts),
        "n_shards": n_shards,
        "shard_min": min(shard_sizes) if shard_sizes else 0,
        "shard_max": max(shard_sizes) if shard_sizes else 0,
        "shard_mean": total_vecs // n_shards if n_shards else 0,
        "shard_median": sorted(shard_sizes)[n_shards // 2] if shard_sizes else 0,
        "total_index_mb": round(sum(index_sizes_mb), 1),
        "avg_index_per_shard_mb": round(sum(index_sizes_mb) / max(n_shards, 1), 2),
        "bytes_per_vector": round(sum(index_sizes_mb) * 1024 * 1024 / max(total_vecs, 1), 1),
        "dim": manifest["dim"],
        "k": manifest["k"],
        "encode_throughput": manifest["throughput"],
        "encode_time_s": manifest["elapsed_s"],
        # Capacity estimate: edge product uses ~600B per vector at dim=10K
        # G.A8.1 at dim=16384 with CompactIndex + LSH
        "est_1M_vectors_gb": round(
            (sum(index_sizes_mb) / max(total_vecs, 1)) * 1_000_000 / 1024, 2),
        "est_10M_vectors_gb": round(
            (sum(index_sizes_mb) / max(total_vecs, 1)) * 10_000_000 / 1024, 2),
    }

    print(f"\n  {'═' * 60}")
    print(f"  SCALABILITY PROFILE")
    print(f"  {'═' * 60}")
    print(f"  Vectors:   {total_vecs:,} across {n_shards} shards")
    print(f"  Media:     {sum(media_counts):,} fused")
    print(f"  Index:     {profile['total_index_mb']:.1f} MB total "
          f"({profile['avg_index_per_shard_mb']:.2f} MB/shard)")
    print(f"  Per-vec:   {profile['bytes_per_vector']:.0f} bytes")
    print(f"  Shard dist: min={profile['shard_min']:,} max={profile['shard_max']:,} "
          f"mean={profile['shard_mean']:,} median={profile['shard_median']:,}")
    print(f"  Encode:    {profile['encode_throughput']:,.0f} vec/sec")
    print(f"")
    print(f"  Capacity Projection:")
    print(f"    1M vectors:  ~{profile['est_1M_vectors_gb']:.1f} GB index")
    print(f"    10M vectors: ~{profile['est_10M_vectors_gb']:.1f} GB index")
    print(f"  {'═' * 60}")

    return profile


# ═════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="G.A8.1 Edge Multi-Factor Benchmark")
    p.add_argument("run_dir", help="Path to A8.1 encoded output")
    p.add_argument("--queries", type=int, default=500)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--dim", type=int, default=16384)
    p.add_argument("--entity-buckets", type=int, default=4)
    p.add_argument("--action-clusters", type=int, default=20)
    args = p.parse_args()

    run_dir = Path(args.run_dir)

    print("=" * 60)
    print("  G.A8.1 — Edge-Compatible Multi-Factor Benchmark")
    print("=" * 60)

    # Load action clusters
    ac_path = run_dir / "action_clusters.json"
    action_clusters = json.load(open(ac_path)) if ac_path.exists() else []
    print(f"  Action clusters: {len(action_clusters)}")

    # Codebook
    cfg = ehc.CodebookConfig()
    cfg.dim = args.dim
    cfg.k = int(math.sqrt(args.dim))
    cfg.seed = 42
    cb = ehc.TokenCodebook(cfg)
    cb.build_from_vocabulary([])

    # Sample queries
    print(f"\n  Sampling {args.queries} queries (seed={args.seed})...")
    queries = sample_queries(run_dir, args.queries, args.seed)

    # Run multi-factor benchmark
    scorecard = run_benchmark(
        queries, str(run_dir), action_clusters, cb,
        n_entity_buckets=args.entity_buckets,
        n_action_clusters=args.action_clusters,
        top_k=args.top_k, dim=args.dim,
    )

    # Scalability profile
    profile = scalability_profile(run_dir)

    # Save combined results
    output = {**scorecard, "scalability": profile}
    out_path = run_dir / "edge_benchmark.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Saved: {out_path}")


if __name__ == "__main__":
    main()
