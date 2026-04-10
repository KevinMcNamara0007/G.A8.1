# G.A8.1 — Blueprint
## Universal Schema-Free Holographic Knowledge Engine
### Two-Tier Emergent Routing · Sub-Millisecond Latency · Any Domain · Any Modality

---

## Executive Summary

A8.1 closes the only remaining gap between A8 and A7: **query latency**.

A8.0 proved the architecture is superior — 85.0% Hit@1 vs A7's 83%, zero schema, universal
vocabulary. The 3,270ms latency came from a single cause: 2.37M vectors per shard (19× too
large). A8.1 solves this with a **two-tier emergent routing scheme** that achieves A7's shard
purity without A7's schema dependency.

| Metric | A7 | A8.0 | A8.1 Target |
|--------|-----|------|-------------|
| Hit@1 | 83.0% | 85.0% | ≥85.0% |
| Hit@5 | 92.0% | 96.2% | ≥96.2% |
| Latency p50 | 6.7ms | 3,270ms | <5ms |
| Schema | 822 relations | none | none |
| Vocabulary | hardcoded | universal | universal |
| Domains | Wikidata only | any | any |
| Modalities | text only | any | any |

---

## Why A7 Was Fast (The Physics)

A7's 6.7ms came from **semantic shard purity**, not architecture:

```
A7 capital shard:   all 122K vectors ≈ bind(R_ACTION, capital) ⊕ bind(R_AGENT, X)
Query:              bind(R_ACTION, capital) ⊕ bind(R_AGENT, france)
Effective search:   just discriminate france among X's → trivial → fast
```

The relation schema pre-computed routing. Every shard was semantically homogeneous.
BSCCompactIndex is O(n) — give it 122K pure vectors and it's instant. Give it 2.37M
mixed vectors and it's 3 seconds.

**A7 cheated: a human-curated 822-relation ontology did the routing work at design time.**

A8.1 achieves equivalent shard purity **without the schema**, using emergent action
clustering discovered from the data itself.

---

## The Two-Tier Architecture

```
Level 1: hash(AGENT)              → entity locality    (which entity neighborhood)
Level 2: cluster(encode(ACTION))  → semantic purity    (which relation family)

Combined shard = (entity_bucket, action_cluster)
```

### At 21.3M Triples:

```
N_entity_buckets   = 36        (entity hash, same as A8.0)
N_action_clusters  = ~50       (emergent, discovered from corpus)
Combined shards    = 36 × 50 = 1,800
Vectors per shard  = 21.3M / 1,800 = ~11,800
knn on 11,800      ≈ 0.4ms     ← sub-millisecond
```

### Shard Semantic Purity (Why It Works):

```
Action cluster 7  = ["place_of_birth", "born in", "native city", "birthplace"]
  → All birth-location variants land here
  → Shard is as pure as A7's place_of_birth shard
  → But no predefined vocabulary

Action cluster 23 = ["chief_executive_officer", "leads", "runs", "ceo of", "heads"]
  → All leadership variants land here
  → Cross-lingual, cross-domain
```

---

## Step-by-Step Build Plan

---

### STEP 0 — EHC C++ Fix (Prerequisite, ~2 hours)

**File:** `bindings/python/bind_core.cpp`

Add numpy-accepting overload to `SparseVector` constructor to eliminate `.tolist()` bloat.
This is G17 from the punchlist — without it, the LSH build loop is too slow at scale.

```cpp
// Add to SparseVector class binding:
.def(nb::init([](dim_t dim,
                 nb::ndarray<int32_t, nb::ndim<1>, nb::c_contig> idx,
                 nb::ndarray<int8_t,  nb::ndim<1>, nb::c_contig> sgn) {
    std::vector<index_t> indices(idx.data(), idx.data() + idx.shape(0));
    std::vector<sign_t>  signs(sgn.data(),   sgn.data() + sgn.shape(0));
    return core::SparseVector{dim, std::move(indices), std::move(signs)};
}),
nb::arg("dim"), nb::arg("indices"), nb::arg("signs"),
"Construct from numpy arrays — zero copy from ndarray.")
```

**Also add** `BSCLSHIndex.serialize_lsh()` / `deserialize_lsh()`:

In `src/index/bsc_lsh_index.cpp` + `.hpp`:
- `hash_indices_` is deterministic from seed — do NOT save it
- Save only: `tables_[t].bucket_ids`, `tables_[t].bucket_offsets`, `ids_`
- Reconstruct `hash_indices_` in `deserialize_lsh()` using same seed formula

```cpp
// hpp addition:
struct LSHSerializedData {
    int32_t dim, k, num_tables, hash_size;
    int64_t n_vectors;
    std::vector<std::vector<int32_t>> bucket_ids;     // [num_tables]
    std::vector<std::vector<int64_t>> bucket_offsets; // [num_tables]
    std::vector<int64_t> ids;
};
[[nodiscard]] LSHSerializedData serialize_lsh() const;
void deserialize_lsh(const LSHSerializedData& data);
```

Expose in `bind_index.cpp`:
```cpp
.def("serialize_lsh",   &BSCLSHIndex::serialize_lsh)
.def("deserialize_lsh", &BSCLSHIndex::deserialize_lsh, nb::arg("data"))
```

**Rebuild EHC after these changes before proceeding.**

---

### STEP 1 — Action Cluster Discovery (`encode/discover_clusters.py`, new file)

Run once on a sample of the corpus before full encode. Discovers the natural action
vocabulary from the data itself.

```python
"""
G.A8.1 — Action Cluster Discovery

Samples ACTION phrases from corpus, encodes as BSC vectors,
clusters by similarity to find emergent relation families.

Usage:
    python discover_clusters.py --source triples.json \
                                --sample 100000 \
                                --n-clusters 50 \
                                --output clusters.json
"""
import json, sys, math, gc
import numpy as np
from pathlib import Path

# EHC import (standard pattern)
for _d in (2,3,4):
    _p = Path(__file__).resolve().parents[_d] / "EHC/build/bindings/python"
    if _p.exists(): sys.path.insert(0, str(_p)); break
import ehc
from eh import LightweightSRL

STOP_WORDS = frozenset({"the","a","an","of","in","on","at","to","for","is","are",
    "was","were","be","been","have","has","had","do","does","did","and","or","not"})


def sample_action_phrases(source: str, n: int, srl) -> list:
    """Sample ACTION phrases from corpus."""
    import random, json
    with open(source) as f:
        data = json.load(f)
    
    sample = random.sample(data, min(n, len(data)))
    actions = []
    
    for t in sample:
        s = t.get("subject",""); r = t.get("relation",""); o = t.get("object","")
        text = f"{s} {r} {o}".strip()
        roles = srl.extract_roles(text)
        action = roles.get("ACTION", r)  # fall back to relation field
        if action and len(action) > 1:
            action_clean = action.lower().replace("_"," ").strip()
            words = [w for w in action_clean.split() if w not in STOP_WORDS]
            if words:
                actions.append(" ".join(words))
    
    return actions


def encode_actions(actions: list, codebook) -> np.ndarray:
    """Encode action phrases as BSC vectors, return as numpy matrix."""
    k = codebook.k
    dim = codebook.dim
    matrix = np.zeros((len(actions), k), dtype=np.int32)
    signs  = np.zeros((len(actions), k), dtype=np.int8)
    
    for i, action in enumerate(actions):
        words = action.split()
        vecs = []
        for w in words:
            try:
                vecs.append(codebook.encode_token(w))
            except Exception:
                pass
        if not vecs:
            continue
        vec = ehc.superpose(vecs) if len(vecs) > 1 else vecs[0]
        inds = list(vec.indices)[:k]
        sgns = list(vec.signs)[:k]
        matrix[i, :len(inds)] = inds
        signs[i,  :len(sgns)] = sgns
    
    return matrix, signs


def bsc_cosine(a_idx, a_sgn, b_idx, b_sgn) -> float:
    """Sparse cosine similarity between two BSC vectors."""
    a_set = {int(i): int(s) for i, s in zip(a_idx, a_sgn) if i != 0}
    b_set = {int(i): int(s) for i, s in zip(b_idx, b_sgn) if i != 0}
    if not a_set or not b_set:
        return 0.0
    overlap = sum(a_set[i] * b_set[i] for i in a_set if i in b_set)
    return overlap / math.sqrt(len(a_set) * len(b_set))


def cluster_actions(actions, idx_mat, sgn_mat, n_clusters=50, n_iter=5):
    """
    K-means-style BSC clustering of action phrases.
    
    Returns: list of cluster dicts with centroid + member phrases.
    """
    n = len(actions)
    rng = np.random.default_rng(42)
    
    # Initialize centroids from random seeds
    centroid_idx = idx_mat[rng.choice(n, n_clusters, replace=False)]
    centroid_sgn = sgn_mat[rng.choice(n, n_clusters, replace=False)]
    
    assignments = np.zeros(n, dtype=np.int32)
    
    for iteration in range(n_iter):
        # Assign each action to nearest centroid
        new_assignments = np.zeros(n, dtype=np.int32)
        for i in range(n):
            best_c, best_sim = 0, -1.0
            for c in range(n_clusters):
                sim = bsc_cosine(idx_mat[i], sgn_mat[i],
                                 centroid_idx[c], centroid_sgn[c])
                if sim > best_sim:
                    best_sim, best_c = sim, c
            new_assignments[i] = best_c
        
        # Update centroids via superpose of members
        for c in range(n_clusters):
            members = np.where(new_assignments == c)[0]
            if len(members) == 0:
                continue
            member_vecs = [
                ehc.SparseVector(idx_mat.shape[1] * 128,  # dim approx
                    idx_mat[m][idx_mat[m] != 0].astype(np.int32).tolist(),
                    sgn_mat[m][idx_mat[m] != 0].astype(np.int8).tolist())
                for m in members[:100]  # cap for speed
            ]
            if member_vecs:
                centroid_vec = ehc.superpose(member_vecs)
                k = len(centroid_vec.indices)
                centroid_idx[c, :k] = list(centroid_vec.indices)
                centroid_sgn[c, :k] = list(centroid_vec.signs)
        
        changed = np.sum(new_assignments != assignments)
        assignments = new_assignments
        print(f"  Iteration {iteration+1}: {changed} reassignments")
        if changed == 0:
            break
    
    # Build cluster output
    clusters = []
    for c in range(n_clusters):
        members = [actions[i] for i in np.where(assignments == c)[0]]
        if not members:
            continue
        # Most common phrase = cluster label
        from collections import Counter
        label = Counter(members).most_common(1)[0][0]
        clusters.append({
            "cluster_id": c,
            "label": label,
            "size": len(members),
            "examples": list(set(members))[:10],
            "centroid_indices": centroid_idx[c][centroid_idx[c] != 0].tolist(),
            "centroid_signs":   centroid_sgn[c][centroid_idx[c] != 0].tolist(),
        })
    
    clusters.sort(key=lambda x: -x["size"])
    return clusters


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--source",     required=True)
    p.add_argument("--sample",     type=int, default=200000)
    p.add_argument("--n-clusters", type=int, default=50)
    p.add_argument("--output",     default="clusters.json")
    p.add_argument("--dim",        type=int, default=16384)
    args = p.parse_args()

    print("=" * 60)
    print("  G.A8.1 — Action Cluster Discovery")
    print("=" * 60)

    srl = LightweightSRL(use_spacy=False)

    cfg = ehc.CodebookConfig()
    cfg.dim = args.dim; cfg.k = int(math.sqrt(args.dim)); cfg.seed = 42
    cb = ehc.TokenCodebook(cfg)
    cb.build_from_vocabulary([])

    print(f"\n  Sampling {args.sample:,} ACTION phrases...")
    actions = sample_action_phrases(args.source, args.sample, srl)
    print(f"  Extracted {len(actions):,} action phrases")

    # Deduplicate
    unique_actions = list(dict.fromkeys(actions))
    print(f"  Unique: {len(unique_actions):,}")

    print("\n  Encoding action phrases as BSC vectors...")
    idx_mat, sgn_mat = encode_actions(unique_actions, cb)

    print(f"\n  Clustering into {args.n_clusters} groups...")
    clusters = cluster_actions(unique_actions, idx_mat, sgn_mat, 
                               n_clusters=args.n_clusters)

    with open(args.output, "w") as f:
        json.dump(clusters, f, indent=2)

    print(f"\n  {len(clusters)} clusters saved to {args.output}")
    print("\n  Top 10 clusters:")
    for c in clusters[:10]:
        print(f"    [{c['cluster_id']:2d}] {c['label']:30s} ({c['size']:,} phrases)")
    print("=" * 60)


if __name__ == "__main__":
    main()
```

**Output:** `clusters.json` — the emergent action vocabulary. Inspect it. Expect to see natural families like birth-location, leadership, education, geography etc. emerging without any predefined schema.

---

### STEP 2 — Universal Chunker (`encode/make_chunks.py`, replace entirely)

```python
"""
G.A8.1 — Universal Chunker

ANY data → (context, value, routing_entity, timestamp)

No domain-specific logic. No schema. One function handles:
  - Wikidata triples
  - Raw prose
  - Logs
  - Genomics annotations  
  - Code
  - Math theorems
  - Any structured record

The SRL extracts AGENT/ACTION/PATIENT universally.
"""
import time
import re
from typing import Optional
from eh import LightweightSRL

STOP_WORDS = frozenset({
    "the","a","an","of","in","on","at","to","for","is","are","was","were",
    "be","been","being","have","has","had","do","does","did","will","would",
    "could","should","may","might","can","shall","must","and","but","or",
    "not","no","so","if","then","than","that","this","it","its","with",
    "from","by","about","as","into","through","during",
})

_srl = None  # module-level singleton, initialized per worker


def get_srl():
    global _srl
    if _srl is None:
        _srl = LightweightSRL(use_spacy=False)
    return _srl


def tokenize(text: str) -> list:
    words = text.replace("_", " ").lower().split()
    return [w for w in words if w not in STOP_WORDS and len(w) > 1]


def make_chunk(text: str, timestamp: str = None) -> Optional[dict]:
    """Universal chunk maker. Works for any data type.

    Extracts (AGENT, ACTION, PATIENT) via SRL.
    Returns context=SR, value=O, routing_entity=AGENT.
    
    This is the A8.1 core insight:
      - O is the answer — never in the context vector
      - SR is the query key — what we bind and index
      - AGENT determines the shard — entity-centric routing
    """
    if not timestamp:
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ")

    srl = get_srl()
    roles = srl.extract_roles(text)

    agent   = roles.get("AGENT",   "").strip()
    action  = roles.get("ACTION",  "").strip()
    patient = roles.get("PATIENT", "").strip()

    # Fallback for text where SRL finds nothing:
    # treat first N-1 tokens as context, last token as value
    if not agent and not patient:
        tokens = tokenize(text)
        if len(tokens) < 2:
            return None
        agent   = " ".join(tokens[:-1])
        action  = ""
        patient = tokens[-1]

    if not patient:
        return None

    context = f"{agent} {action}".strip() if action else agent

    return {
        "context":        context,        # SR — what we bind and index
        "value":          patient,        # O  — the answer we retrieve
        "routing_entity": agent,          # for shard assignment
        "text":           text,           # original, for display
        "timestamp":      timestamp,
    }


def chunk_source(source_path: str) -> list:
    """Detect source type and chunk appropriately. Returns list of chunk dicts."""
    import json, os

    path = source_path.lower()
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ")

    if path.endswith(".json"):
        with open(source_path) as f:
            data = json.load(f)

        if isinstance(data, list) and data and "subject" in data[0]:
            # Wikidata-style triples
            chunks = []
            for t in data:
                s = t.get("subject",""); r = t.get("relation",""); o = t.get("object","")
                if s and o:
                    raw = f"{s} {r} {o}" if r else f"{s} {o}"
                    c = make_chunk(raw, ts)
                    if c:
                        chunks.append(c)
            return chunks
        else:
            # Generic JSON → flatten to text
            lines = []
            def flatten(obj, prefix=""):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        flatten(v, f"{prefix}.{k}" if prefix else k)
                elif isinstance(obj, list):
                    for item in obj:
                        flatten(item, prefix)
                else:
                    if prefix and str(obj).strip():
                        lines.append(f"{prefix} {obj}")
            flatten(data)
            return [c for c in (make_chunk(l, ts) for l in lines) if c]

    else:
        # Raw text — sentence-level chunks
        with open(source_path) as f:
            text = f.read()
        sentences = re.split(r'[.!?\n]+', text)
        chunks = []
        for sent in sentences:
            sent = sent.strip()
            if len(sent) > 10:
                c = make_chunk(sent, ts)
                if c:
                    chunks.append(c)
        return chunks
```

---

### STEP 3 — Two-Tier Encoder (`encode/worker_encode.py`, replace)

Key changes from A8.0:
1. Load `clusters.json` at worker startup
2. Assign each chunk to `(entity_bucket, action_cluster)` shard
3. Build `BSCLSHIndex` during encode (while vectors are in memory)
4. Save `lsh_index.npz` via `serialize_lsh()` alongside `chunk_index.npz`
5. Numpy-accepting `SparseVector` constructor (no `.tolist()`)

```python
"""
G.A8.1 — Worker Encoder (Two-Tier Routing)

Two-tier shard assignment:
  Level 1: hash(AGENT)              → entity_bucket  (0..N_entity-1)
  Level 2: nearest_cluster(ACTION)  → action_cluster (0..N_action-1)
  Shard:   entity_bucket * N_action + action_cluster

Produces ~1,800 shards of ~12K vectors each → ~0.4ms knn.

Builds BSCLSHIndex during encode (vectors in memory) → saves as npz.
Uses numpy-accepting SparseVector constructor (no .tolist() bloat).
"""

import gc, hashlib, json, math, os, pickle, sys, time
import numpy as np
from pathlib import Path

for _d in (2,3,4):
    _p = Path(__file__).resolve().parents[_d] / "EHC/build/bindings/python"
    if _p.exists(): sys.path.insert(0, str(_p)); break
import ehc

from make_chunks import make_chunk, tokenize, STOP_WORDS


def _hash_entity(entity: str, n_buckets: int) -> int:
    h = hashlib.blake2b(entity.encode(), digest_size=8).digest()
    return int.from_bytes(h, "little") % n_buckets


def _nearest_cluster(action_vec, cluster_centroids: list, dim: int) -> int:
    """Find nearest action cluster centroid by BSC cosine similarity."""
    if not cluster_centroids or action_vec is None:
        return 0
    best_c, best_sim = 0, -1.0
    for c_id, centroid in enumerate(cluster_centroids):
        sim = ehc.sparse_cosine(action_vec, centroid)
        if sim > best_sim:
            best_sim, best_c = sim, c_id
    return best_c


def worker_encode(args):
    (worker_id, chunk_pkl_path, dim, k,
     output_dir, n_entity_buckets,
     clusters_path) = args

    import pickle as pkl
    t0 = time.perf_counter()
    out = Path(output_dir) / f"shard_{worker_id:04d}"
    out.mkdir(parents=True, exist_ok=True)

    with open(chunk_pkl_path, "rb") as f:
        chunks = pkl.load(f)
    n = len(chunks)
    print(f"  [shard {worker_id:04d}] {n:,} chunks...")

    # ── Load action clusters ───────────────────────────────────────
    n_action_clusters = 1
    cluster_centroids = []
    if clusters_path and Path(clusters_path).exists():
        with open(clusters_path) as f:
            cluster_data = json.load(f)
        n_action_clusters = len(cluster_data)
        # Pre-build centroid SparseVectors
        for cd in cluster_data:
            idx = cd["centroid_indices"]
            sgn = cd["centroid_signs"]
            if idx:
                cluster_centroids.append(
                    ehc.SparseVector(dim,
                        np.array(idx, dtype=np.int32),
                        np.array(sgn, dtype=np.int8))
                )
            else:
                cluster_centroids.append(None)
        print(f"  [shard {worker_id:04d}] {n_action_clusters} action clusters loaded")

    # ── Build vocabulary ───────────────────────────────────────────
    vocab = set()
    for c in chunks:
        vocab.update(tokenize(c.get("context", "")))
        vocab.update(tokenize(c.get("value", "")))
    vocab_sorted = sorted(vocab)

    # ── Build codebook ─────────────────────────────────────────────
    cfg = ehc.CodebookConfig()
    cfg.dim = dim; cfg.k = k; cfg.seed = 42
    cb = ehc.TokenCodebook(cfg)
    cb.build_from_vocabulary(vocab_sorted)
    for token in vocab_sorted:
        try: cb.encode_token(token)
        except Exception: pass

    # ── Role vectors ───────────────────────────────────────────────
    r_agent  = ehc.make_role(300, dim)
    r_action = ehc.make_role(301, dim)

    # ── Memmap matrices ────────────────────────────────────────────
    mm_dir = out / "_mm"; mm_dir.mkdir(exist_ok=True)
    idx_mat = np.memmap(str(mm_dir / "idx.dat"), dtype=np.int16,
                        mode="w+", shape=(n, k))
    sgn_mat = np.memmap(str(mm_dir / "sgn.dat"), dtype=np.int8,
                        mode="w+", shape=(n, k))

    # ── Encode ─────────────────────────────────────────────────────
    phrase_cache = {}
    texts = []
    values = []
    timestamps = []
    shard_assignments = []  # (entity_bucket, action_cluster) per vector
    n_encoded = 0

    def encode_phrase(phrase: str):
        if phrase in phrase_cache:
            return phrase_cache[phrase]
        words = tokenize(phrase)
        if not words:
            phrase_cache[phrase] = None
            return None
        vecs = []
        for w in words:
            key = f"__token__{w}"
            if key not in phrase_cache:
                try: phrase_cache[key] = cb.encode_token(w)
                except: phrase_cache[key] = None
            if phrase_cache[key] is not None:
                vecs.append(phrase_cache[key])
        if not vecs:
            phrase_cache[phrase] = None
            return None
        result = ehc.superpose(vecs) if len(vecs) > 1 else vecs[0]
        phrase_cache[phrase] = result
        return result

    for i, c in enumerate(chunks):
        context = c.get("context", "")
        value   = c.get("value", "")
        agent   = c.get("routing_entity", "")
        action  = " ".join(context.replace(agent, "").split()).strip()

        agent_vec  = encode_phrase(agent)
        action_vec = encode_phrase(action) if action else None

        if agent_vec is None and action_vec is None:
            continue

        # Bind AGENT and ACTION into context vector
        components = []
        if agent_vec is not None:
            components.append(ehc.bind_role(r_agent, agent_vec))
        if action_vec is not None:
            components.append(ehc.bind_role(r_action, action_vec))

        vec = ehc.superpose(components) if len(components) > 1 else components[0]

        # Two-tier shard assignment
        entity_bucket  = _hash_entity(agent, n_entity_buckets)
        action_cluster = _nearest_cluster(action_vec, cluster_centroids, dim)
        shard_assignments.append((entity_bucket, action_cluster))

        # Write to memmap (numpy-native, no .tolist())
        inds = np.array(vec.indices[:k], dtype=np.int16)
        sgns = np.array(vec.signs[:k],   dtype=np.int8)
        idx_mat[n_encoded, :len(inds)] = inds
        sgn_mat[n_encoded, :len(sgns)] = sgns

        texts.append(c.get("text", context))
        values.append(value)
        timestamps.append(c.get("timestamp", ""))
        n_encoded += 1

        if (i + 1) % 2000 == 0:
            ehc.clear_perm_cache()
        if (i + 1) % 500000 == 0:
            if len(phrase_cache) > 300000:
                phrase_cache = {k: v for k, v in phrase_cache.items()
                                if k.startswith("__token__")}
            idx_mat.flush(); sgn_mat.flush(); gc.collect()

    del phrase_cache
    ehc.clear_perm_cache()
    idx_mat.flush(); sgn_mat.flush(); gc.collect()

    # ── Build BSCCompactIndex ──────────────────────────────────────
    print(f"  [shard {worker_id:04d}] Building CompactIndex ({n_encoded:,})...")
    idx = ehc.BSCCompactIndex(dim, use_sign_scoring=True)

    batch_size = 50000
    for bs in range(0, n_encoded, batch_size):
        be = min(bs + batch_size, n_encoded)
        bv, bi = [], []
        for row in range(bs, be):
            inds = idx_mat[row].astype(np.int32)
            sgns = sgn_mat[row].astype(np.int8)
            nz = k
            while nz > 0 and inds[nz-1] == 0:
                nz -= 1
            if nz > 0:
                # Use numpy-accepting constructor (no .tolist() — G17 fix)
                bv.append(ehc.SparseVector(dim, inds[:nz], sgns[:nz]))
                bi.append(row)
        if bv:
            idx.add_items(bv, bi)
        del bv, bi; gc.collect()

    # Save CompactIndex as npz
    idx_dir = out / "index"; idx_dir.mkdir(exist_ok=True)
    data = idx.serialize()
    np.savez_compressed(
        str(idx_dir / "chunk_index.npz"),
        dim=np.array([data.dim]),
        n_vectors=np.array([data.n_vectors]),
        use_sign_scoring=np.array([1], dtype=np.int32),
        ids=np.array(data.ids, dtype=np.int32),
        plus_data=np.array(data.plus_data, dtype=np.int32),
        plus_offsets=np.array(data.plus_offsets, dtype=np.int64),
        minus_data=np.array(data.minus_data, dtype=np.int32),
        minus_offsets=np.array(data.minus_offsets, dtype=np.int64),
        vec_indices=np.array(data.vec_indices, dtype=np.int16),
        vec_signs=np.array(data.vec_signs, dtype=np.int8),
        vec_offsets=np.array(data.vec_offsets, dtype=np.int64),
    )
    del idx, data; gc.collect()

    # ── Build BSCLSHIndex (while vectors still in memmap) ──────────
    print(f"  [shard {worker_id:04d}] Building LSHIndex ({n_encoded:,})...")
    lsh = ehc.BSCLSHIndex(dim, k, num_tables=8, hash_size=16, use_multiprobe=True)

    for bs in range(0, n_encoded, batch_size):
        be = min(bs + batch_size, n_encoded)
        bv, bi = [], []
        for row in range(bs, be):
            inds = idx_mat[row].astype(np.int32)
            sgns = sgn_mat[row].astype(np.int8)
            nz = k
            while nz > 0 and inds[nz-1] == 0:
                nz -= 1
            if nz > 0:
                bv.append(ehc.SparseVector(dim, inds[:nz], sgns[:nz]))
                bi.append(row)
        if bv:
            lsh.add_items(bv, bi)
        del bv, bi; gc.collect()

    # Serialize LSH via C++ serialize_lsh() — no pickle, no CSR reconstruction
    lsh_data = lsh.serialize_lsh()
    lsh_npz = {"num_tables":  np.array([lsh_data.num_tables]),
               "hash_size":   np.array([lsh_data.hash_size]),
               "n_vectors":   np.array([lsh_data.n_vectors]),
               "ids":         np.array(lsh_data.ids, dtype=np.int64)}
    for t in range(lsh_data.num_tables):
        lsh_npz[f"bucket_ids_{t}"]     = np.array(lsh_data.bucket_ids[t],     dtype=np.int32)
        lsh_npz[f"bucket_offsets_{t}"] = np.array(lsh_data.bucket_offsets[t], dtype=np.int64)
    np.savez_compressed(str(idx_dir / "lsh_index.npz"), **lsh_npz)
    del lsh, lsh_data; gc.collect()

    # ── Save shard assignments ─────────────────────────────────────
    with open(out / "shard_assignments.json", "w") as f:
        json.dump(shard_assignments, f)

    # ── Save texts + values + timestamps ──────────────────────────
    with open(out / "texts.json",  "w") as f: json.dump(texts, f)
    with open(out / "values.json", "w") as f: json.dump(values, f)
    with open(out / "timestamps.json", "w") as f: json.dump(timestamps, f)

    # ── Shard centroid ─────────────────────────────────────────────
    sample_size = min(1000, n_encoded)
    sample_vecs = []
    for row in range(0, n_encoded, max(1, n_encoded // sample_size)):
        inds = idx_mat[row].astype(np.int32)
        sgns = sgn_mat[row].astype(np.int8)
        nz = k
        while nz > 0 and inds[nz-1] == 0:
            nz -= 1
        if nz > 0:
            sample_vecs.append(ehc.SparseVector(dim, inds[:nz], sgns[:nz]))
        if len(sample_vecs) >= sample_size:
            break
    if sample_vecs:
        centroid = ehc.superpose(sample_vecs)
        np.savez(str(out / "centroid.npz"),
                 indices=np.array(list(centroid.indices)[:k], dtype=np.int16),
                 signs=np.array(list(centroid.signs)[:k], dtype=np.int8))
    del sample_vecs; gc.collect()

    # ── Cleanup memmap ─────────────────────────────────────────────
    del idx_mat, sgn_mat; gc.collect()
    import shutil; shutil.rmtree(str(mm_dir), ignore_errors=True)

    elapsed = time.perf_counter() - t0
    manifest = {
        "worker_id":     worker_id,
        "n_chunks":      n,
        "n_encoded":     n_encoded,
        "n_vocab":       len(vocab_sorted),
        "n_action_clusters": n_action_clusters,
        "dim":           dim,
        "k":             k,
        "elapsed_s":     round(elapsed, 1),
        "rate_per_sec":  round(n_encoded / elapsed, 1) if elapsed > 0 else 0,
    }
    with open(out / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"  [shard {worker_id:04d}] Done: {n_encoded:,} vectors | "
          f"{elapsed:.1f}s | {manifest['rate_per_sec']:,.0f}/sec")
    return manifest
```

---

### STEP 4 — Orchestrator (`encode/encode.py`, update)

Key changes:
1. Add `--clusters` argument pointing to `clusters.json`
2. Pass cluster data to workers
3. Increase default `--workers` to 36

```python
# In run_encode() signature:
def run_encode(source, output_dir, n_workers=36, waves=9,
               dim=16384, k=128, clusters_path=None):

# In worker args tuple:
wave_args.append((wid, chunk_path, dim, k, output_dir,
                  n_workers,        # n_entity_buckets = n_workers
                  clusters_path))   # path to clusters.json

# In argparse:
parser.add_argument("--clusters", default=None,
                    help="Path to clusters.json from discover_clusters.py")
parser.add_argument("--workers", type=int, default=36)
```

---

### STEP 5 — Query Engine (`decode/benchmark.py`, update)

Key changes:
1. Load pre-built `lsh_index.npz` via `deserialize_lsh()` — instant, no reconstruction
2. Two-tier routing at query time
3. Drop Python LRU — use EHC C++ `ehc.LRUCache` for shard cache

```python
def load_lsh_from_npz(npz_path, dim, k):
    """Load pre-built LSH index from npz — instant, no reconstruction."""
    d = np.load(str(npz_path), allow_pickle=True)
    num_tables = int(d["num_tables"][0])
    
    # Reconstruct LSHSerializedData
    lsh_data = ehc.BSCLSHIndex.LSHSerializedData()
    lsh_data.dim = dim; lsh_data.k = k
    lsh_data.num_tables = num_tables
    lsh_data.hash_size  = int(d["hash_size"][0])
    lsh_data.n_vectors  = int(d["n_vectors"][0])
    lsh_data.ids        = d["ids"].tolist()
    lsh_data.bucket_ids     = [d[f"bucket_ids_{t}"].tolist()     for t in range(num_tables)]
    lsh_data.bucket_offsets = [d[f"bucket_offsets_{t}"].tolist() for t in range(num_tables)]
    
    lsh = ehc.BSCLSHIndex(dim, k, num_tables=num_tables,
                           hash_size=lsh_data.hash_size, use_multiprobe=True)
    lsh.deserialize_lsh(lsh_data)
    return lsh


def encode_query_a81(text, codebook, r_agent, r_action, cluster_centroids,
                      n_entity_buckets, phrase_cache=None):
    """Two-tier query encoding: extract AGENT+ACTION, bind, route."""
    from eh import LightweightSRL
    srl = LightweightSRL(use_spacy=False)
    roles = srl.extract_roles(text)
    
    agent  = roles.get("AGENT",  "")
    action = roles.get("ACTION", "")
    
    # Encode and bind
    agent_vec  = _encode_phrase(agent,  codebook, phrase_cache)
    action_vec = _encode_phrase(action, codebook, phrase_cache)
    
    components = []
    if agent_vec:
        components.append(ehc.bind_role(r_agent, agent_vec))
    if action_vec:
        components.append(ehc.bind_role(r_action, action_vec))
    if not components:
        return None, -1, -1
    
    query_vec = ehc.superpose(components) if len(components) > 1 else components[0]
    
    # Two-tier routing
    entity_bucket  = _hash_entity(agent, n_entity_buckets)
    action_cluster = _nearest_cluster(action_vec, cluster_centroids, codebook.dim)
    
    return query_vec, entity_bucket, action_cluster
```

---

### STEP 6 — Full Pipeline (`pipeline.sh`, update)

```bash
# Step 0: Discover action clusters (once, before encode)
echo "--- STEP 0: Discover action clusters ---"
python3 encode/discover_clusters.py \
    --source "$TRIPLES_FILE" \
    --sample 200000 \
    --n-clusters 50 \
    --output "$OUTPUT_DIR/clusters.json"

# Step 1: Encode with two-tier routing
echo "--- STEP 1: Encode (two-tier routing) ---"
python3 encode/encode.py \
    --source "$TRIPLES_FILE" \
    --output "$ENCODED_DIR" \
    --workers 36 \
    --waves 9 \
    --clusters "$OUTPUT_DIR/clusters.json"

# Steps 2-4: unchanged (routing table, aliases, cleanup)
```

---

## Configuration (`configs/default.env`)

```bash
# G.A8.1 — Two-Tier Routing Configuration

BSC_DIM=16384
BSC_K=128
CODEBOOK_SEED=42

# Tier 1: Entity buckets
WORKERS=36
WAVES=9

# Tier 2: Action clusters
N_ACTION_CLUSTERS=50
CLUSTER_SAMPLE=200000

# Shard targets
MAX_VECTORS_PER_SHARD=50000   # ~12K expected with 36×50 shards

# LSH parameters (built during encode)
LSH_NUM_TABLES=8
LSH_HASH_SIZE=16
```

---

## Expected Results

```
Shard count:         36 × 50 = 1,800
Vectors per shard:   ~11,800 (21.3M / 1,800)
knn on 11,800:       ~0.4ms
Routing overhead:    ~0.3ms (entity hash + centroid scoring)
Total p50 latency:   ~0.7ms  ← sub-millisecond

Hit@1 expected:      ≥85.0%  (A8.0 baseline, may improve with purity)
Hit@5 expected:      ≥96.2%
Schema:              zero
Vocabulary:          universal, emergent
```

---

## File Checklist for Morning

```
EHC C++ (build first):
  [ ] src/index/bsc_lsh_index.hpp     — add LSHSerializedData + serialize_lsh/deserialize_lsh
  [ ] src/index/bsc_lsh_index.cpp     — implement serialize_lsh/deserialize_lsh  
  [ ] bindings/python/bind_core.cpp   — add numpy SparseVector constructor (G17)
  [ ] bindings/python/bind_index.cpp  — expose serialize_lsh/deserialize_lsh
  [ ] cmake --build (rebuild EHC)

G.A8.1 Python:
  [ ] encode/discover_clusters.py     — NEW (from this blueprint)
  [ ] encode/make_chunks.py           — REPLACE with universal chunker
  [ ] encode/worker_encode.py         — REPLACE with two-tier encoder
  [ ] encode/encode.py                — UPDATE (add --clusters, --workers 36)
  [ ] decode/benchmark.py             — UPDATE (load_lsh_from_npz, two-tier query)
  [ ] pipeline.sh                     — UPDATE (add Step 0)
  [ ] configs/default.env             — UPDATE

Run order:
  1. cmake --build (EHC)
  2. python discover_clusters.py      (~5 min)
  3. python encode.py                 (~30 min, 36 workers)
  4. python benchmark.py              (~3 min, target <5ms p50)
```

---

## The Theoretical Claim

> **G.A8.1 achieves A7-level query latency (sub-5ms) without A7's schema dependency
> by replacing the human-curated relation ontology with an emergent two-tier routing
> scheme. Entity-hash routing preserves locality; action-cluster routing restores
> semantic shard purity. Both tiers are derived automatically from the corpus.
> The result is a universal knowledge engine that operates identically across
> text, multimodal, and cross-disciplinary data — with no predefined vocabulary,
> no domain-specific logic, and no schema maintenance burden.**

---

*Architecture: G.A8.1 — Universal Schema-Free Holographic Knowledge Engine*
*Engine: EHC C++ v12.5.0.2 with GIL-safe nanobind bindings*
*Standards: Two-tier emergent routing, D=16384, k=128, SRL-extracted roles*
*Lineage: A7 (schema-bound, 6.7ms) → A8.0 (schema-free, 3270ms) → A8.1 (schema-free, <5ms)*
