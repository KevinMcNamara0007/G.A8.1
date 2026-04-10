"""
G.A8.1 — Action Cluster Discovery

Discovers emergent relation families from the corpus via BSC k-means.
No predefined vocabulary. The data defines its own schema.

For structured triples: ACTION = the relation field directly.
For unstructured text: ACTION = SRL-extracted verb/predicate.

Output: clusters.json — centroid vectors + example phrases per cluster.

Usage:
    python discover_clusters.py --source triples.json --n-clusters 50 --output clusters.json
"""

import argparse
import gc
import json
import math
import random
import sys
import time
import numpy as np
from pathlib import Path

for _d in (2, 3, 4):
    _p = Path(__file__).resolve().parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc

STOP_WORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "is", "are",
    "was", "were", "be", "been", "have", "has", "had", "do", "does", "did",
    "and", "or", "not", "no", "so", "but", "if", "then", "than",
})


def extract_actions(source: str, sample_size: int, seed: int = 42) -> list:
    """Extract ACTION phrases from corpus.

    For structured triples: ACTION = relation field (no SRL needed).
    For unstructured text: falls back to SRL.
    """
    rng = random.Random(seed)

    with open(source) as f:
        data = json.load(f)

    # Detect structured triples
    if isinstance(data, list) and data and "relation" in data[0]:
        # Structured: relation field IS the action — no SRL overhead
        sample = rng.sample(data, min(sample_size, len(data)))
        actions = []
        for t in sample:
            r = t.get("relation", "").strip()
            if r and len(r) > 1:
                words = [w for w in r.replace("_", " ").lower().split()
                         if w not in STOP_WORDS and len(w) > 1]
                if words:
                    actions.append(" ".join(words))
        del data, sample
        gc.collect()
        return actions

    # Unstructured: use SRL
    from eh import LightweightSRL
    srl = LightweightSRL(use_spacy=False)
    sample = rng.sample(data, min(sample_size, len(data)))
    actions = []
    for item in sample:
        text = str(item) if not isinstance(item, str) else item
        roles = srl.extract_roles(text)
        action = roles.get("ACTION", "").strip()
        if action and len(action) > 1:
            words = [w for w in action.lower().split()
                     if w not in STOP_WORDS and len(w) > 1]
            if words:
                actions.append(" ".join(words))
    del data, sample
    gc.collect()
    return actions


def encode_actions(actions: list, dim=16384, k=128):
    """Encode unique action phrases as BSC superpose vectors."""
    cfg = ehc.CodebookConfig()
    cfg.dim = dim
    cfg.k = k
    cfg.seed = 42
    cb = ehc.TokenCodebook(cfg)
    cb.build_from_vocabulary([])

    idx_mat = np.zeros((len(actions), k), dtype=np.int32)
    sgn_mat = np.zeros((len(actions), k), dtype=np.int8)

    for i, action in enumerate(actions):
        words = action.split()
        vecs = []
        for w in words:
            try:
                vecs.append(cb.encode_token(w))
            except Exception:
                pass
        if not vecs:
            continue
        vec = ehc.superpose(vecs) if len(vecs) > 1 else vecs[0]
        inds = list(vec.indices)[:k]
        sgns = list(vec.signs)[:k]
        idx_mat[i, :len(inds)] = inds
        sgn_mat[i, :len(sgns)] = sgns

    return idx_mat, sgn_mat


def cluster_actions(actions, idx_mat, sgn_mat, n_clusters=50,
                    n_iter=5, dim=16384, k=128):
    """BSC k-means clustering of action phrases.

    Returns list of cluster dicts with centroids + example phrases.
    """
    n = len(actions)
    rng = np.random.default_rng(42)

    # Seed centroids from well-spaced samples
    seed_indices = rng.choice(n, min(n_clusters, n), replace=False)
    centroid_idx = idx_mat[seed_indices].copy()
    centroid_sgn = sgn_mat[seed_indices].copy()
    actual_k = min(n_clusters, n)

    assignments = np.full(n, -1, dtype=np.int32)

    for iteration in range(n_iter):
        # Assign each action to nearest centroid
        new_assignments = np.zeros(n, dtype=np.int32)
        for i in range(n):
            best_c, best_sim = 0, -2.0
            a_inds = idx_mat[i]
            a_sgns = sgn_mat[i]
            a_nz = np.count_nonzero(a_inds)
            if a_nz == 0:
                continue
            a_vec = ehc.SparseVector(dim,
                np.ascontiguousarray(a_inds[:a_nz]),
                np.ascontiguousarray(a_sgns[:a_nz]))
            for c in range(actual_k):
                c_nz = np.count_nonzero(centroid_idx[c])
                if c_nz == 0:
                    continue
                c_vec = ehc.SparseVector(dim,
                    np.ascontiguousarray(centroid_idx[c, :c_nz]),
                    np.ascontiguousarray(centroid_sgn[c, :c_nz]))
                sim = ehc.sparse_cosine(a_vec, c_vec)
                if sim > best_sim:
                    best_sim, best_c = sim, c
            new_assignments[i] = best_c

        # Update centroids via superpose of members
        for c in range(actual_k):
            members = np.where(new_assignments == c)[0]
            if len(members) == 0:
                continue
            member_vecs = []
            for m in members[:200]:  # cap for speed
                nz = np.count_nonzero(idx_mat[m])
                if nz > 0:
                    member_vecs.append(ehc.SparseVector(dim,
                        np.ascontiguousarray(idx_mat[m, :nz]),
                        np.ascontiguousarray(sgn_mat[m, :nz])))
            if member_vecs:
                centroid_vec = ehc.superpose(member_vecs)
                ci = list(centroid_vec.indices)[:k]
                cs = list(centroid_vec.signs)[:k]
                centroid_idx[c] = 0
                centroid_sgn[c] = 0
                centroid_idx[c, :len(ci)] = ci
                centroid_sgn[c, :len(cs)] = cs

        changed = np.sum(new_assignments != assignments)
        assignments = new_assignments
        print(f"  Iteration {iteration + 1}/{n_iter}: {changed:,} reassignments")
        if changed == 0:
            break

    # Build output
    from collections import Counter
    clusters = []
    for c in range(actual_k):
        members = [actions[i] for i in np.where(assignments == c)[0]]
        if not members:
            continue
        label = Counter(members).most_common(1)[0][0]
        nz = np.count_nonzero(centroid_idx[c])
        clusters.append({
            "cluster_id": c,
            "label": label,
            "size": len(members),
            "examples": list(set(members))[:10],
            "centroid_indices": centroid_idx[c, :nz].tolist(),
            "centroid_signs": centroid_sgn[c, :nz].tolist(),
        })

    clusters.sort(key=lambda x: -x["size"])
    return clusters


def main():
    p = argparse.ArgumentParser(description="G.A8.1 Action Cluster Discovery")
    p.add_argument("--source", required=True)
    p.add_argument("--sample", type=int, default=200000)
    p.add_argument("--n-clusters", type=int, default=50)
    p.add_argument("--output", default="clusters.json")
    p.add_argument("--dim", type=int, default=16384)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    print("=" * 60)
    print("  G.A8.1 — Action Cluster Discovery")
    print("=" * 60)
    t0 = time.perf_counter()

    k = int(math.sqrt(args.dim))

    print(f"\n  Extracting actions from {args.sample:,} samples...")
    actions = extract_actions(args.source, args.sample, args.seed)
    print(f"  Raw actions: {len(actions):,}")

    # Deduplicate
    unique = list(dict.fromkeys(actions))
    print(f"  Unique: {len(unique):,}")

    print(f"\n  Encoding as BSC vectors...")
    idx_mat, sgn_mat = encode_actions(unique, args.dim, k)

    print(f"\n  Clustering into {args.n_clusters} groups...")
    clusters = cluster_actions(unique, idx_mat, sgn_mat,
                               n_clusters=args.n_clusters,
                               dim=args.dim, k=k)

    with open(args.output, "w") as f:
        json.dump(clusters, f, indent=2)

    elapsed = time.perf_counter() - t0
    print(f"\n  {len(clusters)} clusters discovered in {elapsed:.1f}s")
    print(f"\n  Top 15 clusters:")
    for c in clusters[:15]:
        print(f"    [{c['cluster_id']:3d}] {c['label']:35s} ({c['size']:,} phrases)")
    print(f"\n  Saved: {args.output}")
    print("=" * 60)


if __name__ == "__main__":
    main()
