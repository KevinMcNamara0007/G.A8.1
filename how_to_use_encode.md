# how_to_use_encode.md

How to encode a corpus into G.A8.1, end-to-end, without having to read
the autotune machinery or the tier router. Pairs with
`how_to_use_decode.md` — picks the encoder, runs it, and produces a
directory the unified `decode.QueryService` can read.

---

## TL;DR — pick your encoder in 30 seconds

```
                    What's your corpus shape?
                              │
        ┌─────────────────────┼─────────────────────────────┐
        ▼                     ▼                             ▼
  Atomic SRO            Free text /              Mixed / billions-scale
  (clean s/r/o)         narrative /              (atomic + narrative,
  ≤ ~100M records       social messages          tier-routed, sharded
                        ≤ ~100M records          for horizontal scaling)
        │                     │                             │
        ▼                     ▼                             ▼
  encode_triples.py    encode_unstructured.py         encode.py
  (single-machine,     (single-machine,                (two-tier sharded,
   single LSH index,    single LSH index,               needs clusters.json,
   built-in autotune)   built-in autotune,              tier-routed)
                        salience-pooled tokens)
```

If your records are pre-cleaned `(subject, relation, object)` triples
(Wikidata, knowledge graphs) → **`encode_triples.py`**.

If your records are free-text or social messages with one `text` (or
`object`) field → **`encode_unstructured.py`**.

If you need to scale beyond ~100M records, OR your corpus has mixed
shapes (atomic + narrative + emergent), OR you want shard-routed
sub-millisecond query latency → **`encode.py`** (preceded by
`discover_clusters.py`).

---

## The three encoders side by side

| | `encode_triples.py` | `encode_unstructured.py` | `encode.py` |
|---|---|---|---|
| **Output layout** | flat: `structural_v13/` + `corpus.jsonl` | flat: `structural_v13/` + `corpus.jsonl` | sharded: `shard_NNNN/` × N + `manifest.json` + `clusters.json` |
| **Decoder** | `from decode import QueryService` | `from decode import QueryService` | `from decode import QueryService` (same import — auto-detects layout) |
| **Vector algebra** | `ehc.StructuralPipelineV13.ingest_batch_parallel` (full C++ pipeline: slot + bigram + KV + optional Hebbian) | same as encode_triples | `ehc.superpose([codebook[t] for t in atoms])` — pure superposition, no slot binding |
| **Atom contract** | Path-B-symmetric: vector = `superpose(s_atom, r_atom)`; O lives in sidecar as O' | salience-pooled: vector = `superpose(top-K-IDF tokens of s+r+o)` | Tier-1 path: `superpose(s_atom, r_atom)` (same as encode_triples). Tier-2/3 paths use extracted-triple or fallback bag tokens. |
| **`max_slots` honored?** | Yes (recipe: `2·√k`, p99 lift) | Yes | No — sharded path doesn't allocate the slot table |
| **`max_salient_tokens` honored?** | N/A | Yes (recipe: `k/2`) | Yes (worker_encode now derives from `derive_k_constants(k)`) |
| **Built-in autotune?** | Yes — sweeps D ∈ {256, 512, 1024, 2048, 4096, 8192, 16384} via `_autotune.predict_d_zone` | Yes — same grid + zone heuristic | No — uses `encode.profile` as a separate pre-step, OR explicit `--dim/--k` pin |
| **Pre-steps required** | None | None | `discover_clusters.py` first (k-means over relation phrases → `clusters.json`) |
| **Required env vars** | None | None | `A81_TIER_ROUTED=1` (without it, no tier metadata → query recall collapses to ~0%) |
| **Sharding parallelism** | Single-process ingest (concurrent encode threads inside C++, serial LSH writer) | Same | Embarrassingly parallel: 9 partition workers + waves of per-shard `worker_encode` processes |
| **Bidirectional retrieval (o, r → s)?** | No | No (only via salience overlap) | No today (would need a parallel `(o, r)`-keyed index — out of current scope) |
| **Scales to 10B+ records?** | No (single LSH ceiling ~100M) | No | Yes — per-shard size stays bounded |
| **Validated on 21.3M Wikidata** | 99.87% unique-key Hit@1, 14.7 ms p50, 12.5 min encode | not benchmarked on this corpus | 84.90% Hit@1 / 98.30% Hit@10 / 1.17 ms p50 (deterministic routing), 17.6 min encode |
| **Use it when** | Pre-cleaned SRO, single machine, want autotune+slot-binding, simple to operate | Free text or social messages, salience-pooled vector | Billions-scale, OR mixed atomic+narrative, OR need shard-routed sub-ms latency |

---

## End-to-end use cases — exact scripts

### Use case 1 — Atomic SRO at single-machine scale

Wikidata-shape data, 1M – 100M triples, one machine, latency budget
< 20 ms, recall budget > 99%.

**Script:**

```bash
cd /path/to/G.A8.1

python3 -m encode.encode_triples \
    --source /path/to/triples.json \
    --output /path/to/encoded
```

That's it. No env vars, no clusters file, no profile pre-step.
Autotune sweeps `{256, 512, 1024}` for the atomic-SRO p99=2 zone, picks
the smallest D at 100% Hit@1 on a 1M sample, writes the index.

**Output:**

```
/path/to/encoded/
    structural_v13/
        structural_v13.cfg          # config (dim, k, max_slots, …)
        lsh.bin                     # the LSH index for the whole corpus
        hebbian.bin                 # optional, only if --enable-hebbian
    corpus.jsonl                    # one row per doc_id
                                    # (doc_id, subject, relation, object, text, ...)
    corpus_profile.json             # autotune audit + winner (D, k)
```

**Decode (matches automatically):**

```python
from decode import QueryService
qs = QueryService("/path/to/encoded")
qs.query(subject="france", relation="capital", k=10)
```

**Pin geometry explicitly (skip autotune):**

```bash
python3 -m encode.encode_triples \
    --source /path/to/triples.json \
    --output /path/to/encoded \
    --dim 256 --k 16
```

**Wipe before encoding (`--force`):**

```bash
python3 -m encode.encode_triples --force \
    --source /path/to/triples.json \
    --output /path/to/encoded \
    --dim 256 --k 16
```

### Use case 2 — Free text / narrative / social messages

Variable-length records with a single `text` (or `object`) field.
Tokens come from the field; salience filtering keeps the vector
density bounded regardless of input length.

**Script:**

```bash
python3 -m encode.encode_unstructured \
    --source /path/to/messages.jsonl \
    --output /path/to/encoded
```

Autotune sweeps the short-narrative or long-narrative zone depending
on observed p99 atoms/record:
- p99 ≤ 24:  `{512, 1024, 2048, 4096}` (synthetic-mode wide)
- 25 – 200:  `{1024, 2048, 4096, 8192}`
- > 200:     `{2048, 4096, 8192, 16384}` (deep)

**Pin geometry + use operator queries** (more accurate scoring than
synthetic mask-first queries):

```bash
python3 -m encode.encode_unstructured \
    --source /path/to/messages.jsonl \
    --output /path/to/encoded \
    --dim 4096 --k 64 \
    --operator-queries /path/to/operator_queries.jsonl
```

`operator_queries.jsonl` is one JSON object per line, each
`{"query_text": str, "gold_ids": [int, …]}`. The autotune scores by
real-task Hit@1 against gold instead of synthetic queries; for
narrative corpora this typically picks a smaller D than synthetic mode
would.

**Output:** same shape as use case 1 (flat).

**Decode:**

```python
from decode import QueryService
qs = QueryService("/path/to/encoded")
qs.query(text="who built the bridge?", k=10)   # text-only on flat backend
```

### Use case 3 — Billions-scale OR mixed-shape (sharded, tier-routed)

Atomic SRO at 100M – 100B+ records, OR a corpus mixing pre-cleaned
triples with free-text records, OR you need shard-routed
sub-millisecond query latency.

**Step 1 — discover semantic action clusters** (one-time per corpus):

```bash
python3 -m encode.discover_clusters \
    --source /path/to/triples.json \
    --output /path/to/encoded/clusters.json \
    --sample 200000 \
    --n-clusters 50 \
    --dim 256
```

Streams the source via reservoir sampling (no full `json.load` — works
on 1.9 GB / 21M-record files at constant memory). Discovers ~50
emergent action families via BSC k-means. `--dim` here must match the
encode dim you'll use in step 2.

**Step 2 — encode with tier routing:**

```bash
A81_TIER_ROUTED=1 python3 -m encode.encode \
    --source /path/to/triples.json \
    --output /path/to/encoded \
    --clusters /path/to/encoded/clusters.json \
    --no-profile \
    --dim 256 --k 16 \
    --entity-buckets 36
```

**`A81_TIER_ROUTED=1` is required.** Without it, vectors are encoded
as bag-of-tokens with no tier metadata; `QueryService` startup logs
`tier_counts={'structured_atomic': 0, …}` and recall collapses to
~0%. This is BUG-DATA-01 from the upstream brief — flagged here so
you don't repeat it.

`--entity-buckets 36 × 50 action_clusters = 1,800 shards`. Each shard
has its own per-shard LSH + sidecar + tier manifest.

**Output:**

```
/path/to/encoded/
    manifest.json                   # corpus-level: dim, k, n_entity_buckets,
                                    #   n_action_clusters, per-shard summary
    clusters.json                   # action centroids (from step 1)
    centroids.json                  # per-shard centroids (for legacy
                                    #   centroid routing; deterministic
                                    #   routing supersedes this)
    action_clusters.json            # alias of clusters.json
    _global_idf.json                # global IDF map for salience
    shard_0000/
        index/chunk_index.npz       # BSCCompactIndex
        index/lsh_index.npz         # BSCLSHIndex
        sidecar.ehs                 # EHS1 binary metadata
        tier_manifest.json          # per-vector tier registry
        centroid.npz                # this shard's centroid vector
        manifest.json               # per-shard summary
        ...
    shard_0001/
    ...
    shard_1799/
```

**Decode (auto-detects sharded layout, deterministic routing on by
default):**

```python
from decode import QueryService
qs = QueryService("/path/to/encoded", dim=256, k=16)
qs.query(subject="france", relation="capital", k=10)   # 1.17 ms p50
```

**For long-running encodes — disable sleep mode** on macOS:

```bash
caffeinate -d nohup python3 -m encode.encode ... > encode.log 2>&1 &
```

---

## What the encode contract guarantees

The encoders honor a recipe so the decoder doesn't have to be told
the geometry separately. Enforced in code:

| Property | Where it's enforced |
|---|---|
| **D grid `{256, 512, 1024, 2048, 4096, 8192, 16384}`** | `encode/_autotune.py:_GRID`, `decode13/profile/elbow.py:GRID_POWER_OF_TWO` |
| **`k = round(√D)`** | `encode_triples.py:autotune_dk`, `encode_unstructured.py:autotune_dk` |
| **`max_slots = round(2·√k)`** + p99 lift | `_autotune.derive_k_constants` (used by encode_triples + encode_unstructured + decode `build_sro_tier1_config`) |
| **`max_salient_tokens = k // 2`** | `_autotune.derive_k_constants` (used by encode_triples + worker_encode) |
| **Atomic-SRO autotune zone `{256, 512, 1024}`** for p99 ≤ 8 | `_autotune.predict_d_zone` |
| **Path-B-symmetric Tier-1** | `decode13/structured_pipeline.py:tokens_from_triple` returns `[s, r]`; `worker_encode.py:572` calls `tokens_from_triple()` |
| **O' (object) preserved in sidecar** | `corpus.jsonl` (flat) or per-shard EHS1 / `texts.json` (sharded) |
| **Deterministic Tier-1 routing** | `decode13/query_service.py:_route_deterministic` mirrors `encode/encode.py:_hash_entity` + `_nearest_cluster` exactly |
| **Streaming source ingest** | `encode/_io.py:iter_json_records` (auto-detects JSON-array vs JSONL); `discover_clusters.py` uses streaming reservoir sampling |
| **Sample-bounded autotune scans** | `encode_triples.py:autotune_dk` and `_quick_p99_atoms_sro` break out at `sample_n` records (~1M default) |

---

## Common gotchas

1. **Forgot `A81_TIER_ROUTED=1` on the sharded path.** Symptom:
   `QueryServiceV13` startup logs `tier_counts={'structured_atomic':
   0, …}`. Recall ~0%. Fix: re-encode with the env var set.

2. **Forgot `discover_clusters.py` before `encode.py`.** `encode.py
   --clusters /path/to/clusters.json` will fail with a missing-file
   error. Always run `discover_clusters` first; the cluster file is a
   one-time artifact per corpus shape.

3. **`encode.py`'s `--entity-buckets` defaults to a small value.**
   The current default in `config.py` may be `4`, producing only
   `4 × 50 = 200` shards. For canonical 1,800-shard layout, pass
   `--entity-buckets 36` explicitly. (We hit this on the May 2026 WIKI
   run.)

4. **Sleep mode interrupts long encodes.** macOS suspends `nohup`
   processes under power management. For multi-hour encodes use
   `caffeinate -d`, or run on a Linux box with no auto-suspend.

5. **`json.load` of a >100MB source.** All three encoders use the
   streaming reader (`encode/_io.iter_json_records`) for the source +
   sample writes. If you write a custom encoder, do the same — never
   `json.load(f)` a Wikidata-scale file. (`discover_clusters.py` was
   patched in May 2026 specifically because the old version did this
   and OOM'd.)

6. **Source format mismatch.** All encoders auto-detect JSON-array
   vs JSONL via `_io._detect_source_type`. Both are supported. The
   first non-whitespace byte of the file decides: `[` → JSON array,
   `{` → JSONL.

7. **The `_count_records` upfront pass.** `encode_triples.py` skips
   this (was 5 minutes of wasted single-thread JSON parsing on a 21M
   source). `encode.py` also skips it. The record count comes from
   the actual ingest pass instead. If you write a custom encoder, do
   not add an upfront count.

8. **Salience cap doesn't bite for atomic SRO.** Per record, atomic
   SRO has 2 atoms (s_atom, r_atom). The salience cap (k/2 = 8 at
   D=256) is much larger than 2, so it never filters. The
   `MAX_SALIENT_TOKENS = 12` vs `k/2 = 8` distinction is functionally
   irrelevant for atomic SRO; only matters for narrative.

9. **Asymmetric encode and query atom sets.** This is the
   LSH-mismatch pathology that took most of a debug day to find: if
   the encode superposes more atoms than the query, the LSH hash
   signatures diverge and the gold record falls out of the candidate
   list. Path B (encode = `[s, r]`, query = `[s, r]`) is what works.
   Don't add `o` to the encode side without also adding it to the
   query side.

---

## Where to add new code

| You want to… | Edit |
|---|---|
| Add a new encoder for a corpus shape we don't cover | New `encode/encode_*.py` modeled on `encode_triples.py` (flat) or `encode.py` (sharded) |
| Change the (s, r) → shard partition function | `encode/encode.py:_hash_entity` AND `decode13/query_service.py:_hash_entity` (must stay in lockstep — they're the same algorithm) |
| Add a new tier (beyond 1/2/3) | `decode13/tier_types.py:Tier` enum + `decode13/*_pipeline.py` + register in `tier_router.py` + handle in `worker_encode.py` |
| Tweak the autotune D grid | `encode/_autotune.py:_GRID` AND `decode13/profile/elbow.py:GRID_POWER_OF_TWO` (must match) |
| Tweak the recipe (k, slots, salient formulas) | `encode/_autotune.py:derive_k_constants` (single source of truth across all three encoders + decode) |
| Tweak the salience pool (which tokens get IDF-ranked) | `encode/worker_encode.py:_select_salient` |
| Add a media encoder (images, video) | `encode/worker_encode.py` already handles `media_path` fields. Plug a new vision/video encoder into `_encode_media`. |

---

## Quick reference

```
ATOMIC SRO, single-machine
─────────────────────────────────────────────────────────────────────
python3 -m encode.encode_triples \
    --source triples.json --output /encoded
# → flat layout, autotuned D ∈ {256, 512, 1024}, decode via:
#   from decode import QueryService; QueryService("/encoded")


NARRATIVE / SOCIAL, single-machine
─────────────────────────────────────────────────────────────────────
python3 -m encode.encode_unstructured \
    --source messages.jsonl --output /encoded \
    --operator-queries gold.jsonl     # optional, for accurate autotune
# → flat layout, salience-pooled vectors, same decoder


BILLIONS-SCALE / MIXED-SHAPE, sharded
─────────────────────────────────────────────────────────────────────
# Step 1: cluster discovery (one-time per corpus shape)
python3 -m encode.discover_clusters \
    --source triples.json --output /encoded/clusters.json \
    --sample 200000 --n-clusters 50 --dim 256

# Step 2: encode (must set A81_TIER_ROUTED=1)
A81_TIER_ROUTED=1 python3 -m encode.encode \
    --source triples.json --output /encoded \
    --clusters /encoded/clusters.json \
    --no-profile --dim 256 --k 16 --entity-buckets 36
# → sharded layout, 36×50 = 1,800 shards, decode via:
#   from decode import QueryService; QueryService("/encoded")
#   # → 1.17 ms p50 deterministic routing on Tier-1
```

Last validated: 2026-05-08, Wikidata 21.3M corpus, all three encoders
+ unified decoder, end-to-end recipe contract honored.
