#!/usr/bin/env python3
"""
G.A8 — Schema-Free Benchmark (Memory-Disciplined)

Memory discipline:
  - MmapCompactIndex (OS-managed pages, no heap bloat)
  - LRU shard cache (max 3 active shards)
  - Shared codebook (one build, not per-shard)
  - ehc.LRUCache for phrase encoding
  - Centroid routing before any shard touches RAM

Usage:
    python3 benchmark.py /path/to/a8_encoded --queries 500 --seed 42
"""

import argparse
import gc
import hashlib
import json
import math
import random
import sys
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np

# ── EHC import ──────────────────────────────────────────────
for _depth in (2, 3, 4):
    _ehc = Path(__file__).resolve().parents[_depth] / "EHC" / "build" / "bindings" / "python"
    if _ehc.exists():
        sys.path.insert(0, str(_ehc))
        break
import ehc

# Stop words (must match encode)
STOP_WORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "is", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "may", "might",
    "can", "shall", "must", "and", "but", "or", "not", "no", "so",
    "if", "then", "than", "that", "this", "it", "its", "with", "from",
    "by", "about", "as", "into", "through", "during",
})


def _hash_to_shard(text: str, n_shards: int) -> int:
    """Same hash as encode — deterministic subject routing."""
    h = hashlib.blake2b(text.encode(), digest_size=8).digest()
    return int.from_bytes(h, "little") % n_shards


def progress_bar(current, total, width=40, prefix="", extras=""):
    pct = current / max(total, 1)
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    line = f"\r  {prefix}[{bar}] {current:>{len(str(total))}}/{total} ({pct*100:5.1f}%)"
    if extras:
        line += f"  {extras}"
    sys.stderr.write(line)
    sys.stderr.flush()
    if current >= total:
        sys.stderr.write("\n")


# ═════════════════════════════════════════════════════════════
#  LRU SHARD CACHE
# ═════════════════════════════════════════════════════════════

class _LRUCache:
    """LRU cache for loaded shard indices. Evicts cold shards to control RSS."""
    def __init__(self, max_size):
        self._cache = OrderedDict()
        self._max = max_size

    def get(self, key):
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, key, value):
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = value
        while len(self._cache) > self._max:
            evicted_key, evicted = self._cache.popitem(last=False)
            # Release mmap resources
            if hasattr(evicted.get("index"), "release"):
                evicted["index"].release()
            del evicted
            gc.collect()


# ═════════════════════════════════════════════════════════════
#  INDEX LOADING (MmapCompactIndex preferred)
# ═════════════════════════════════════════════════════════════

def load_index(npz_path, dim=16384):
    """Load index as MmapCompactIndex (OS pages) with BSCCompactIndex fallback."""
    d = np.load(str(npz_path), allow_pickle=True)

    sign_scoring = int(d["use_sign_scoring"][0]) if "use_sign_scoring" in d else 1

    use_mmap = hasattr(ehc, "MmapCompactIndex")
    if use_mmap:
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

    # Fallback: heap-based
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



def _load_lsh_from_npz(npz_path, dim=16384, k=128):
    """Load pre-built BSCLSHIndex from npz. Zero .tolist() — numpy direct."""
    d = np.load(str(npz_path), allow_pickle=True)

    lsh_data = ehc.LSHIndexData()
    lsh_data.dim = int(d["dim"][0])
    lsh_data.k = int(d["k"][0])
    lsh_data.num_tables = int(d["num_tables"][0])
    lsh_data.hash_size = int(d["hash_size"][0])
    lsh_data.n_vectors = int(d["n_vectors"][0])
    # Numpy direct — no .tolist(), no Python list intermediary
    lsh_data.ids = np.ascontiguousarray(d["ids"], dtype=np.int64)
    lsh_data.vec_indices = np.ascontiguousarray(d["vec_indices"], dtype=np.int32)
    lsh_data.vec_signs = np.ascontiguousarray(d["vec_signs"], dtype=np.int8)
    lsh_data.vec_offsets = np.ascontiguousarray(d["vec_offsets"], dtype=np.int64)

    nt = lsh_data.num_tables
    # bucket arrays are small (~12K × 8 tables) — tolist() is acceptable
    lsh_data.bucket_ids = [d[f"bucket_ids_{t}"].tolist() for t in range(nt)]
    lsh_data.bucket_offsets = [d[f"bucket_offsets_{t}"].tolist() for t in range(nt)]

    lsh = ehc.BSCLSHIndex(dim, k)
    lsh.deserialize(lsh_data)
    return lsh


def load_shard_lazy(shard_dir, dim=16384, use_lsh=True):
    """Load shard: pre-built LSH (fast) + CompactIndex (fallback) + texts."""
    shard_dir = Path(shard_dir)
    k = int(math.sqrt(dim))

    # Prefer pre-built LSH (saved during encode)
    lsh = None
    lsh_path = shard_dir / "index" / "lsh_index.npz"
    if use_lsh and lsh_path.exists():
        lsh = _load_lsh_from_npz(lsh_path, dim, k)

    # CompactIndex as fallback
    idx = load_index(shard_dir / "index" / "chunk_index.npz", dim)

    with open(shard_dir / "texts.json") as f:
        texts = json.load(f)

    # Media paths (optional — present when multimodal encode was used)
    media_paths = None
    mp_file = shard_dir / "media_paths.json"
    if mp_file.exists():
        with open(mp_file) as f:
            media_paths = json.load(f)

    return {"index": idx, "lsh": lsh, "texts": texts, "media_paths": media_paths}


# ═════════════════════════════════════════════════════════════
#  QUERY ENCODING
# ═════════════════════════════════════════════════════════════

def _encode_tokens(words: list, codebook, phrase_cache=None):
    """Encode a list of tokens as superpose, with optional cache."""
    vecs = []
    for w in words:
        if phrase_cache is not None:
            cached = phrase_cache.get(w)
            if cached is not None:
                vecs.append(cached)
                continue
        try:
            v = codebook.encode_token(w)
            vecs.append(v)
            if phrase_cache is not None:
                phrase_cache.put(w, v)
        except Exception:
            pass
    if not vecs:
        return None
    return ehc.superpose(vecs) if len(vecs) > 1 else vecs[0]


def encode_query(text: str, codebook, phrase_cache=None,
                 subject: str = None):
    """Encode query as bind(S, R) — matches encode-time hybrid.

    If subject is provided, splits text into S and R tokens, binds them.
    Otherwise falls back to superpose of all tokens.
    """
    if subject:
        # Split into S tokens and R tokens (everything else)
        s_words = [w for w in subject.replace("_", " ").lower().split()
                    if w not in STOP_WORDS and len(w) > 1]
        all_words = [w for w in text.replace("_", " ").lower().split()
                     if w not in STOP_WORDS and len(w) > 1]
        # R tokens = all tokens minus S tokens
        s_set = set(s_words)
        r_words = [w for w in all_words if w not in s_set]

        s_vec = _encode_tokens(s_words, codebook, phrase_cache)
        r_vec = _encode_tokens(r_words, codebook, phrase_cache) if r_words else None

        if s_vec and r_vec:
            return ehc.bind_bsc(s_vec, r_vec)
        elif s_vec:
            return s_vec

    # Fallback: superpose all tokens
    words = [w for w in text.replace("_", " ").lower().split()
             if w not in STOP_WORDS and len(w) > 1]
    return _encode_tokens(words, codebook, phrase_cache)


# ═════════════════════════════════════════════════════════════
#  SAMPLE QUERIES
# ═════════════════════════════════════════════════════════════

def sample_queries(run_dir, n, seed=42):
    """Sample N queries via reservoir sampling — O(n) memory, not O(total)."""
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
        for ti, text in enumerate(texts):
            parts = text.strip().split()
            if len(parts) < 3:
                continue
            item = {
                "shard_id": sid,
                "text_idx": ti,
                "full_text": text,
                "query_tokens": " ".join(parts[:-1]),
                "gold": parts[-1],
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

    print(f"  Pool: {count:,} candidates → {len(reservoir)} sampled")
    return reservoir


# ═════════════════════════════════════════════════════════════
#  BENCHMARK
# ═════════════════════════════════════════════════════════════

def run_benchmark(queries, run_dir, action_clusters, shared_cb,
                  n_entity_buckets=36, n_action_clusters=50,
                  top_k=10, final_k=5, dim=16384,
                  preloaded_shards=None):
    """A8.1 two-tier benchmark: entity hash × action cluster → direct shard lookup."""
    n = len(queries)
    k = int(math.sqrt(dim))
    hit1 = hit5 = 0
    latencies = []

    # Use pre-loaded shards if available, else LRU
    shard_cache = preloaded_shards if preloaded_shards else _LRUCache(max_size=50)

    # C++ phrase cache
    phrase_cache = ehc.LRUCache(max_size=5000) if hasattr(ehc, "LRUCache") else None

    # Pre-build action cluster centroid vectors
    cluster_centroids = []
    for cd in action_clusters:
        ci = cd.get("centroid_indices", [])
        cs = cd.get("centroid_signs", [])
        if ci:
            cluster_centroids.append(ehc.SparseVector(dim,
                np.array(ci, dtype=np.int32),
                np.array(cs, dtype=np.int8)))
        else:
            cluster_centroids.append(None)

    # Shard directories
    shard_dirs = {}
    for sd in sorted(Path(run_dir).glob("shard_*")):
        sid = int(sd.name.split("_")[1])
        shard_dirs[sid] = sd

    print(f"\n  {'─' * 60}")
    print(f"  A8.1 BENCHMARK — {n:,} queries, {len(shard_dirs)} shards, "
          f"{n_entity_buckets}×{n_action_clusters} routing")
    print(f"  {'─' * 60}")

    for i, q in enumerate(queries):
        t0 = time.perf_counter()

        query_text = q["query_tokens"]
        gold = q["gold"].lower().replace(" ", "_")

        # Extract subject and relation from ground truth
        full_text = q.get("full_text", "")
        parts = full_text.split()
        subject = parts[0] if parts else ""
        # Relation = everything between subject and gold object
        relation = " ".join(parts[1:-1]) if len(parts) > 2 else ""

        qvec = encode_query(query_text, shared_cb, phrase_cache, subject=subject)
        if qvec is None:
            latencies.append(0)
            continue

        # Two-tier routing: entity hash + action cluster
        entity_bucket = _hash_to_shard(subject, n_entity_buckets)

        # Find top-3 action clusters via BSC cosine against centroids
        cluster_scores = []
        if cluster_centroids and relation:
            r_words = [w for w in relation.replace("_", " ").lower().split()
                       if w not in STOP_WORDS and len(w) > 1]
            if r_words:
                r_vecs = []
                for w in r_words:
                    try:
                        r_vecs.append(shared_cb.encode_token(w))
                    except Exception:
                        pass
                if r_vecs:
                    r_vec = ehc.superpose(r_vecs) if len(r_vecs) > 1 else r_vecs[0]
                    for ci, cent in enumerate(cluster_centroids):
                        if cent is None:
                            continue
                        sim = ehc.sparse_cosine(r_vec, cent)
                        cluster_scores.append((ci, sim))
                    cluster_scores.sort(key=lambda x: -x[1])

        # Search top-3 action clusters × entity bucket
        if cluster_scores:
            target_shards = [
                entity_bucket * n_action_clusters + ci
                for ci, _ in cluster_scores[:3]
            ]
        else:
            target_shards = [entity_bucket * n_action_clusters]

        # Query target shards (pre-loaded or LRU cached)
        all_results = []
        for sid in target_shards:
            if isinstance(shard_cache, dict):
                shard = shard_cache.get(sid)
            else:
                shard = shard_cache.get(sid)
                if shard is None and sid in shard_dirs:
                    shard = load_shard_lazy(shard_dirs[sid], dim, use_lsh=False)
                    shard_cache.put(sid, shard)
            if shard is None:
                continue

            # Two-level: LSH narrows candidates, then rank
            if shard.get("lsh"):
                result = shard["lsh"].knn_query(qvec, k=top_k)
            else:
                result = shard["index"].knn_query(qvec, k=top_k)
            for vid, score in zip(result.ids, result.scores):
                if vid < len(shard["texts"]):
                    all_results.append((score, shard["texts"][vid]))

        # Rank + dedup
        all_results.sort(key=lambda x: -x[0])
        answers = []
        seen = set()
        for score, text in all_results:
            parts = text.strip().split()
            if parts:
                obj = parts[-1].lower().replace(" ", "_")
                if obj not in seen:
                    seen.add(obj)
                    answers.append(obj)
            if len(answers) >= final_k:
                break

        elapsed_ms = (time.perf_counter() - t0) * 1000
        latencies.append(elapsed_ms)

        is_hit1 = len(answers) > 0 and answers[0] == gold
        is_hit5 = gold in answers[:final_k]
        hit1 += is_hit1
        hit5 += is_hit5

        if (i + 1) % 50 == 0 or i == n - 1:
            h1 = hit1 / (i + 1) * 100
            h5 = hit5 / (i + 1) * 100
            p50 = sorted(latencies)[len(latencies) // 2]
            progress_bar(i + 1, n, extras=f"Hit@1={h1:.1f}% Hit@5={h5:.1f}% p50={p50:.1f}ms")

    latencies_sorted = sorted(latencies)
    scorecard = {
        "type": "a8_schema_free_v2",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_queries": n,
        "n_shards": len(shard_dirs),
        "hit_at_1": hit1,
        "hit_at_5": hit5,
        "hit_at_1_pct": round(hit1 / n * 100, 2),
        "hit_at_5_pct": round(hit5 / n * 100, 2),
        "latency_p50_ms": round(latencies_sorted[len(latencies_sorted) // 2], 2),
        "latency_p95_ms": round(latencies_sorted[int(len(latencies_sorted) * 0.95)], 2),
        "latency_mean_ms": round(sum(latencies) / max(len(latencies), 1), 2),
        "routing": f"{n_entity_buckets}x{n_action_clusters}",
    }

    print(f"\n  {'═' * 60}")
    print(f"  RESULTS")
    print(f"  {'═' * 60}")
    print(f"  Hit@1:  {scorecard['hit_at_1_pct']:6.2f}%  ({hit1}/{n})")
    print(f"  Hit@5:  {scorecard['hit_at_5_pct']:6.2f}%  ({hit5}/{n})")
    print(f"  Latency p50:  {scorecard['latency_p50_ms']:6.2f} ms")
    print(f"  Latency p95:  {scorecard['latency_p95_ms']:6.2f} ms")
    print(f"  Latency mean: {scorecard['latency_mean_ms']:6.2f} ms")
    print(f"  {'═' * 60}")

    return scorecard


def main():
    parser = argparse.ArgumentParser(description="G.A8.1 Two-Tier Benchmark")
    parser.add_argument("run_dir", help="Path to A8.1 encoded output")
    parser.add_argument("--queries", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--final-k", type=int, default=5)
    parser.add_argument("--entity-buckets", type=int, default=36)
    parser.add_argument("--dim", type=int, default=16384)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    print("=" * 60)
    print("  G.A8.1 — Two-Tier Emergent Routing Benchmark")
    print("=" * 60)

    # Load action clusters
    clusters_path = run_dir / "action_clusters.json"
    if not clusters_path.exists():
        clusters_path = run_dir / "clusters.json"
    with open(clusters_path) as f:
        action_clusters = json.load(f)
    n_action_clusters = len(action_clusters)
    print(f"  Action clusters: {n_action_clusters}")
    print(f"  Entity buckets:  {args.entity_buckets}")
    print(f"  Total shards:    {args.entity_buckets * n_action_clusters}")

    # Build shared codebook (hash mode)
    cfg = ehc.CodebookConfig()
    cfg.dim = args.dim
    cfg.k = int(math.sqrt(args.dim))
    cfg.seed = 42
    shared_cb = ehc.TokenCodebook(cfg)
    shared_cb.build_from_vocabulary([])
    print(f"  Codebook: hash mode")

    # Pre-load all shards at startup (one-time cost, eliminates cold-load latency)
    print(f"\n  Pre-loading shards...")
    t0 = time.perf_counter()
    shard_dirs = {}
    preloaded_shards = {}
    for sd in sorted(run_dir.glob("shard_*")):
        sid = int(sd.name.split("_")[1])
        shard_dirs[sid] = sd
    # Only load shards that exist (many of 1,800 may be empty)
    for sid, sd in shard_dirs.items():
        if (sd / "index" / "chunk_index.npz").exists():
            preloaded_shards[sid] = load_shard_lazy(sd, args.dim, use_lsh=False)
    print(f"  {len(preloaded_shards)} shards loaded in {time.perf_counter()-t0:.1f}s")

    # Sample queries
    print(f"\n  Sampling {args.queries} queries (seed={args.seed})...")
    queries = sample_queries(run_dir, args.queries, seed=args.seed)

    # Run
    scorecard = run_benchmark(
        queries, run_dir, action_clusters, shared_cb,
        n_entity_buckets=args.entity_buckets,
        n_action_clusters=n_action_clusters,
        top_k=args.top_k, final_k=args.final_k,
        dim=args.dim,
        preloaded_shards=preloaded_shards,
    )

    out_path = run_dir / "a81_scorecard.json"
    with open(out_path, "w") as f:
        json.dump(scorecard, f, indent=2)
    print(f"\n  Scorecard: {out_path}")


if __name__ == "__main__":
    main()
