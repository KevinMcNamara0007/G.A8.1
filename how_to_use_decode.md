# how_to_use_decode.md

How to query an encoded G.A8.1 corpus, end-to-end, without having to read
5000 lines of source. Pairs with the encode CLI tools — picks up where
they leave off and returns answers.

---

## TL;DR — one import, any layout

```python
from decode import QueryService                            # ← canonical entry

qs = QueryService("/path/to/encoded")
qs.query(subject="france", relation="capital", k=10)       # SRO
qs.query(text="who built the bridge?", k=10)               # free-text
```

`decode.QueryService` **auto-detects the layout** at construction time
and dispatches to the right backend internally. Use this for all new
code — developers, AI agents, and architects shouldn't need to know
which encode CLI produced the directory.

The two on-disk shapes it routes between:

```
                       Did you encode with…
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
  encode_triples.py     encode_unstructured.py    encode.py
  (atomic SRO)          (narrative / messages)    (two-tier sharded
                                                   for billions-scale)
        │                     │                     │
        └────────┬────────────┘                     │
                 ▼                                  ▼
        ┌─────────────────┐                ┌──────────────────┐
        │ flat layout:    │                │ sharded layout:  │
        │ structural_v13/ │                │ shard_NNNN/ × N  │
        │ corpus.jsonl    │                │ manifest.json    │
        └─────────────────┘                │ clusters.json    │
                 │                         └──────────────────┘
                 │                                  │
                 ▼                                  ▼
        ┌─────────────────────────────────────────────────┐
        │                                                 │
        │   from decode import QueryService               │
        │   qs = QueryService(path)                       │
        │   qs.layout  → "flat"      or "sharded"         │
        │   qs.backend → underlying impl if you need      │
        │                layout-specific features         │
        │                                                 │
        └─────────────────────────────────────────────────┘
```

The unified entry is implemented in `decode/query_dispatch.py:QueryService`
and re-exported from `decode/__init__.py`. The legacy import paths
(`decode.query.QueryService`, `decode13.QueryServiceV13`) still work
unchanged for back-compat with existing edge_service / RESTWRAPPER calls.

You can identify the layout by `ls`'ing the encoded directory:

```bash
# Flat layout:
$ ls /path/to/encoded
clusters.json   corpus.jsonl   corpus_profile.json   structural_v13/

# Sharded layout:
$ ls /path/to/encoded
manifest.json   clusters.json   centroids.json   _global_idf.json
shard_0000/   shard_0001/   ...   shard_1799/
```

---

## The contract: encode → decode

Every encode entry point produces a **specific on-disk layout** with
**specific guarantees**. The matching decoder reads exactly that layout.

### Flat layout (single-machine scale, ≤ ~100M records)

| Encode CLI | Output shape | What's in the vector |
|---|---|---|
| `python -m encode.encode_triples` | flat: `structural_v13/` + `corpus.jsonl` | `superpose(s_atom, r_atom)` (Path-B-symmetric) |
| `python -m encode.encode_unstructured` | flat: same shape | `superpose(top-K-IDF salient tokens)` of `s+r+o` |

The decoder for this shape:

```python
from decode import QueryService     # canonical — auto-detects flat layout

qs = QueryService("/path/to/encoded")
result = qs.query(subject="france", relation="capital", k=10)
# (qs synthesizes "france capital" as text and forwards to the flat backend)
```

Or directly via the legacy class if you need flat-specific extras
(e.g. `query_images`, `query_multimodal`):

```python
from decode.query import QueryService as FlatQueryService
svc = FlatQueryService(a81_path="/path/to/encoded",
                       product_dir=None, context={})
result = svc.query("france capital", k=10)
# returns: {results: [{doc_id, text, score, ...}], confidence, audit}
```

The single `StructuralPipelineV13` is loaded from disk on startup. Every
query is encoded with the same codebook and probed against one LSH
index. No tier routing, no shard fan-out. **Latency stays under 20 ms
at 21M records (we measured 14.7 ms p50 on D=256/k=16 Wikidata).**

### Sharded layout (billions-scale, two-tier semantic routing)

| Encode CLI | Output shape | What's in the vector |
|---|---|---|
| `A81_TIER_ROUTED=1 python -m encode.encode --clusters clusters.json` | sharded: `shard_NNNN/` × N | `superpose(s_atom, r_atom)` per Tier-1 record (Path-B-symmetric inside the sharded shell) |

**Critical:** `A81_TIER_ROUTED=1` MUST be set when encoding for the
sharded path. Without it, vectors are encoded as bag-of-tokens (no tier
metadata) and `QueryServiceV13` returns ~0% recall because the tier
filter rejects every candidate. This is BUG-DATA-01 from the upstream
brief — flagged here so you don't repeat it.

The decoder for this shape:

```python
from decode import QueryService     # canonical — auto-detects sharded layout

qs = QueryService("/path/to/encoded", dim=256, k=16)

# Default route_mode="auto" — for SRO Tier-1 queries this picks the exact
# shard via the partition function (1.17 ms p50, 100% routing accuracy).
# Falls back to centroid routing for narrative / Tier-2/3.
result = qs.query(subject="france", relation="capital", k=10)
# returns: {results: [{shard_id, vec_id, raw_score, value, ...}], trace}

# To force the deterministic route (fails open if metadata missing):
result = qs.query(subject="france", relation="capital", route_mode="deterministic")

# To force exhaustive search across all shards (slow, useful as ground truth):
result = qs.query(subject="france", relation="capital", n_shards=0)
```

If you need direct access to the sharded backend (rare):

```python
from decode13 import QueryServiceV13   # still works, kept for back-compat
qs = QueryServiceV13("/path/to/encoded", dim=256, k=16)
```

---

## End-to-end use cases — full runnable scripts

Each script below is **copy-paste runnable**. Fix `RUN_DIR` to your
encoded path and run with `python3 path/to/script.py`. Every script
uses the canonical `from decode import QueryService` so layout
detection is automatic.

### Use case 1: knowledge-graph lookup, single machine, atomic SRO

Wikidata-shape data, 1M – 100M triples, single-machine deployment.
Latency budget under 20 ms, recall budget over 99%.

**Encode** (per `how_to_use_encode.md`, use case 1):

```bash
cd /Users/stark/Quantum_Computing_Lab/G.A8.1
python3 -m encode.encode_triples \
    --source /path/to/triples.json \
    --output /path/to/encoded
```

**Decode — full runnable script:**

```python
#!/usr/bin/env python3
"""Atomic SRO decode (flat layout)."""
import sys
sys.path.insert(0, "/Users/stark/Quantum_Computing_Lab/G.A8.1")
sys.path.insert(0, "/Users/stark/Quantum_Computing_Lab/EHC/build/bindings/python")

from decode import QueryService

RUN_DIR = "/path/to/encoded"

qs = QueryService(RUN_DIR)
print(f"layout: {qs.layout}")
print(f"stats : {qs.stats}")

# SRO query (the dispatcher synthesizes f"{s} {r}" text for the flat backend).
res = qs.query(subject="france", relation="capital", k=5)
for i, r in enumerate(res["results"]):
    print(f"  rank {i}  doc_id={r.get('doc_id')}  "
          f"score={r.get('score'):.3f}  text={r.get('text')!r}")

qs.close()
```

If you need flat-only extras (e.g. `query_images`, `query_multimodal`,
metadata filters like `tags_any`/`prefer_recent`), bypass the
dispatcher and use the flat backend directly:

```python
from decode.query import QueryService as FlatQueryService
svc = FlatQueryService(a81_path=RUN_DIR, product_dir=None, context={})
res = svc.query("france capital", k=5,
                has_media=False, tags_any=["history"])
```

**Validated numbers** (21.3M Wikidata at D=256/k=16):
- 99.87% unique-key Hit@1, 99.80% multiplicity-aware Hit@mult
- p50 = 14.7 ms, p99 = 105 ms
- Encode wall: 12.5 min on a 16-core/128 GB Mac

### Use case 2: billions-scale knowledge graph, two-tier sharded

Same atomic SRO data shape but at 100M – 100B+ records. Single-machine
RAM and LSH bucket density both run out of road. Need shard-routed
queries.

**Pre-step (once per corpus):**

```bash
python -m encode.discover_clusters \
    --source /path/to/triples.json \
    --output /path/to/encoded/clusters.json \
    --sample 200000 --n-clusters 50 --dim 256
```

This streams the source (no full json.load — uses reservoir sampling,
constant memory) and clusters relations into ~50 emergent action
families.

**Encode:**

```bash
A81_TIER_ROUTED=1 python -m encode.encode \
    --source /path/to/triples.json \
    --output /path/to/encoded \
    --clusters /path/to/encoded/clusters.json \
    --no-profile --dim 256 --k 16 \
    --entity-buckets 36
```

`--entity-buckets 36 × --action-clusters (from clusters.json) 50 = 1,800 shards`.
Each shard is independent: per-shard LSH index, per-shard sidecar, per-shard
tier manifest. Encode is embarrassingly parallel across shards.

**Decode — full runnable script (deterministic routing for SRO):**

```python
#!/usr/bin/env python3
"""Sharded SRO decode with deterministic routing."""
import sys
sys.path.insert(0, "/Users/stark/Quantum_Computing_Lab/G.A8.1")
sys.path.insert(0, "/Users/stark/Quantum_Computing_Lab/EHC/build/bindings/python")

from decode import QueryService

RUN_DIR = "/path/to/encoded"

# dim/k are auto-resolved from manifest.json if you omit them.
qs = QueryService(RUN_DIR, dim=256, k=16)
print(f"layout: {qs.layout}  shards: {qs.stats.get('shards')}  "
      f"dim={qs.stats.get('dim')}  k={qs.stats.get('k')}")

# Default route_mode="auto" → deterministic for SRO Tier-1.
# 1.17 ms p50 on the validated 21.3M WIKI corpus.
res = qs.query(subject="france_under_the_third_republic",
               relation="capital", k=5)
for i, r in enumerate(res["results"]):
    print(f"  rank {i}  shard={r['shard_id']}  vec={r['vec_id']}  "
          f"score={r['raw_score']:.3f}  obj={r['value']!r}")
print(f"trace: {res['trace']}")

qs.close()
```

**Variants — when you need to override the default routing:**

```python
# Force deterministic (errors loudly when metadata is missing — useful
# for surfacing config bugs in production):
res = qs.query(subject=s, relation=r, route_mode="deterministic")

# Centroid-routed top-N shards (legacy; the only option for Tier-2/3
# narrative queries that don't have a deterministic partition function):
res = qs.query(subject=s, relation=r, n_shards=8, route_mode="centroid")

# Exhaustive across all shards (~135 ms p50; ground-truth recall, never
# use in latency-sensitive paths):
res = qs.query(subject=s, relation=r, n_shards=0)
```

**Validated numbers** (21.3M Wikidata at D=256/k=16, 1,800 shards):
- 84.90% Hit@1, 98.30% Hit@10 (combined-key bench; matches single-index
  Path B within noise)
- p50 = 1.17 ms, p99 = 10.1 ms (deterministic route)
- Encode wall: 17.6 min on a 16-core/128 GB Mac (encoded 21.3M records
  across 1,800 shards via 9 parallel partition workers)

**What's actually in each Tier-1 record vector** (sharded path is
simpler than the recipe table might suggest):

```python
# Per record (s, r, o):
V_record = ehc.superpose([
    codebook.encode_token(s_atom),    # ≈16 of 256 positions
    codebook.encode_token(r_atom),    # ≈16 of 256 positions
])                                    # ≈32 positions total (with collisions)
LSH.add(V_record, doc_id)
sidecar.write({doc_id, subject=s, relation=r, object=o, ...})
```

No slot binding, no bigram, no Hebbian — just a superposition + an
LSH index entry + a sidecar row. `max_slots` is irrelevant on this
path because the C++ slot table never gets built. The "Tier-1" label
is doing work at the *routing* layer (atomic compounds preserved,
per-vector manifest registered) and at the *sidecar layer* (full O
stored as O') — not in the vector algebra itself.

For our existing MOE/WIKI specifically, this means:
- D = 256, k = 16
- `max_salient_tokens = 12` (hardcoded constant at encode time; the k/2
  fix landed *after*, future encodes will use 8)
- `max_slots`: not stamped, not used
- Per-record vector = 2-atom superpose (~32 positions in 256 dims)

### Use case 3: narrative / messaging corpora (mixed atomic + free-text)

Edge messaging, document chunks, or mixed S/R/O + free-text data.
Records are long and noisy; tier routing matters.

**Pre-steps** (same as Use Case 2): cluster discovery first.

**Encode:**

```bash
A81_TIER_ROUTED=1 python -m encode.encode \
    --source /path/to/messages.jsonl \
    --output /path/to/encoded \
    --clusters /path/to/encoded/clusters.json \
    --media-dir /path/to/media \
    --no-profile --dim 4096 --k 64
```

The tier router sends each record to one of three pipelines:
- Tier 1 (`structured_atomic`) — explicit s/r/o present, atomic compounds.
- Tier 2 (`extracted_triple`) — free text, NER + rule-based fact extraction.
- Tier 3 (`emergent_structure`) — fallback for narrative without extractable triples.

The salience filter (`max_salient_tokens = k/2`) keeps the encoded vector
density bounded regardless of input length.

**Decode — full runnable script (mixed query shapes):**

```python
#!/usr/bin/env python3
"""Sharded narrative + mixed-tier decode."""
import sys
sys.path.insert(0, "/Users/stark/Quantum_Computing_Lab/G.A8.1")
sys.path.insert(0, "/Users/stark/Quantum_Computing_Lab/EHC/build/bindings/python")

from decode import QueryService

RUN_DIR = "/path/to/encoded"

qs = QueryService(RUN_DIR, dim=4096, k=64)
print(f"layout: {qs.layout}  shards: {qs.stats.get('shards')}")

# Tier-2/3 dispatch — free-text query, the tier router classifies and
# emits the right token list at query time. Centroid routing is used
# (deterministic doesn't apply without (s, r) anchors).
res = qs.query(text="who built the bridge?", k=10, n_shards=32)
for i, r in enumerate(res["results"]):
    print(f"  rank {i}  shard={r['shard_id']}  "
          f"score={r['raw_score']:.3f}  text={r.get('text', '')[:60]!r}")

# Tier-1 dispatch — same service, explicit (s, r) → deterministic route.
res = qs.query(subject="some_author", relation="topic", k=10)

qs.close()
```

**Validated numbers** (MOE/EDGE corpus, ~315K social-media-shape records,
D=4096/k=64): 52% Hit@1 with operator-supplied gold queries; 82%
relevance with synthetic mask-first queries. (See
`universal_constants.md` for the discovery-log entry.)

---

## Operational scripts

Common things you actually do with an encoded directory.

### Smoke-test an encoded directory in 10 seconds

Tells you whether the directory is loadable, what layout it is, and
whether a sanity query returns something. Run this first whenever you
land on a corpus you didn't encode yourself.

```python
#!/usr/bin/env python3
"""smoke_test.py — verify an encoded directory is queryable."""
import sys, time
sys.path.insert(0, "/Users/stark/Quantum_Computing_Lab/G.A8.1")
sys.path.insert(0, "/Users/stark/Quantum_Computing_Lab/EHC/build/bindings/python")

from decode import QueryService

RUN_DIR = sys.argv[1] if len(sys.argv) > 1 else "/path/to/encoded"

t0 = time.perf_counter()
qs = QueryService(RUN_DIR)
load = time.perf_counter() - t0

print(f"layout : {qs.layout}")
print(f"loaded : {load:.1f}s")
print(f"stats  : {qs.stats}")

# Pull one row out of the corpus to use as a self-identity probe.
if qs.layout == "flat":
    sample_doc = next(iter(qs.backend._docs.values()))
    s, r = sample_doc.get("subject"), sample_doc.get("relation")
elif qs.layout == "sharded":
    # Walk one shard's sidecar for a sample row.
    import json
    from pathlib import Path
    for shard_dir in sorted(Path(RUN_DIR).glob("shard_*")):
        legacy = shard_dir / "texts.json"
        if legacy.exists():
            with open(legacy) as f:
                rec = json.loads(f.read().splitlines()[0])
            s, r = rec.get("subject"), rec.get("relation")
            break
    else:
        s = r = None

if s and r:
    t0 = time.perf_counter()
    res = qs.query(subject=s, relation=r, k=5)
    print(f"query  : ({s!r}, {r!r}) → "
          f"{len(res['results'])} results in "
          f"{(time.perf_counter()-t0)*1000:.1f} ms")
    if res["results"]:
        print(f"top-1  : {res['results'][0]}")
print("OK" if (s and r and res["results"]) else "FAIL")
qs.close()
```

Run: `python3 smoke_test.py /Users/stark/Quantum_Computing_Lab/MOE/WIKI`

### Sample-and-verify recall (quick benchmark)

Pulls N random records from the source, queries by `(s, r)`, checks
whether each gold object appears in the top-k. Useful as a sanity
check after encoding.

```python
#!/usr/bin/env python3
"""recall_check.py — quick Hit@1/Hit@10 against the encoded corpus."""
import json, random, sys, time
sys.path.insert(0, "/Users/stark/Quantum_Computing_Lab/G.A8.1")
sys.path.insert(0, "/Users/stark/Quantum_Computing_Lab/EHC/build/bindings/python")

from decode import QueryService
from encode._io import iter_json_records

SOURCE  = "/Users/stark/Quantum_Computing_Lab/GoldC/triples_21M.json"
RUN_DIR = "/Users/stark/Quantum_Computing_Lab/MOE/WIKI"
N_BENCH, SEED = 500, 42

# Reservoir-sample N records from source (constant memory).
rng = random.Random(SEED)
samples = []
for i, rec in enumerate(iter_json_records(SOURCE)):
    s, r, o = rec.get("subject",""), rec.get("relation",""), rec.get("object","")
    if not (s and r): continue
    if len(samples) < N_BENCH:
        samples.append((s, r, o))
    elif rng.randint(0, i) < N_BENCH:
        samples[rng.randint(0, N_BENCH - 1)] = (s, r, o)

qs = QueryService(RUN_DIR, dim=256, k=16)
hit1 = hit10 = 0; lat = []
for s, r, gold_o in samples:
    t0 = time.perf_counter()
    res = qs.query(subject=s, relation=r, k=10)
    lat.append((time.perf_counter() - t0) * 1000)
    objs = [h.get("value", "") for h in res["results"]]
    if objs and objs[0] == gold_o: hit1 += 1
    if gold_o in objs: hit10 += 1
qs.close()

n = len(samples); lat.sort()
print(f"N={n}  Hit@1={100*hit1/n:.2f}%  Hit@10={100*hit10/n:.2f}%  "
      f"p50={lat[n//2]:.2f} ms  p99={lat[int(0.99*n)]:.2f} ms")
```

### Batch query (parallel, low overhead)

Concurrent queries over a list of `(s, r)` pairs.

```python
#!/usr/bin/env python3
"""batch_query.py — concurrent queries via ThreadPoolExecutor."""
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, "/Users/stark/Quantum_Computing_Lab/G.A8.1")
sys.path.insert(0, "/Users/stark/Quantum_Computing_Lab/EHC/build/bindings/python")
from decode import QueryService

RUN_DIR = "/Users/stark/Quantum_Computing_Lab/MOE/WIKI"

queries = [
    ("france_under_the_third_republic", "capital"),
    ("lalit_kumar_goel", "instance_of"),
    ("ugo_riccarelli", "languages_spoken,_written_or_signed"),
    # … add yours
]

qs = QueryService(RUN_DIR, dim=256, k=16)
def run_one(sr):
    s, r = sr
    res = qs.query(subject=s, relation=r, k=5)
    return (s, r, res["results"])

with ThreadPoolExecutor(max_workers=8) as pool:
    for s, r, results in pool.map(run_one, queries):
        top = results[0] if results else None
        print(f"({s!r}, {r!r}) → {top.get('value') if top else '<none>'!r}")
qs.close()
```

`QueryServiceV13.query_text` (called inside the sharded backend)
releases the GIL, so a Python thread pool is the right concurrency
primitive — no need for `multiprocessing`.

### Inspect tier counts and per-shard health (sharded only)

After loading a sharded directory, the QueryService prints
`tier_counts={'structured_atomic': N, 'extracted_triple': M, …}`. If
any tier shows 0 when you expect non-zero, you forgot
`A81_TIER_ROUTED=1` at encode time. To pull more detail:

```python
#!/usr/bin/env python3
"""shard_health.py — per-shard size, tier mix, centroid health."""
import sys
sys.path.insert(0, "/Users/stark/Quantum_Computing_Lab/G.A8.1")
sys.path.insert(0, "/Users/stark/Quantum_Computing_Lab/EHC/build/bindings/python")
from decode import QueryService

RUN_DIR = "/Users/stark/Quantum_Computing_Lab/MOE/WIKI"
qs = QueryService(RUN_DIR, dim=256, k=16)
assert qs.layout == "sharded", "shard_health.py only applies to sharded layout"

shards = qs.backend.shards   # {shard_id: ShardData13}
sizes = [(sid, s.size()) for sid, s in shards.items()]
sizes.sort(key=lambda x: -x[1])

print(f"{len(shards)} shards")
print(f"  largest 5: {sizes[:5]}")
print(f"  smallest 5: {sizes[-5:]}")
print(f"  median: {sizes[len(sizes)//2]}")

empty = [sid for sid, n in sizes if n == 0]
if empty: print(f"  empty shards: {len(empty)}  (e.g. {empty[:5]})")

centroid_loaded = qs.backend.centroid_index.size()
print(f"centroid_index: {centroid_loaded} centroids "
      f"(deterministic routing: "
      f"{'available' if qs.backend.action_centroids else 'NOT available'})")
qs.close()
```

### REST endpoint template (Flask)

Minimal Flask service wrapping `QueryService`. Suitable for plugging
into edge_service / RESTWRAPPER patterns.

```python
#!/usr/bin/env python3
"""decode_rest.py — minimal REST wrapper."""
import sys
from flask import Flask, request, jsonify
sys.path.insert(0, "/Users/stark/Quantum_Computing_Lab/G.A8.1")
sys.path.insert(0, "/Users/stark/Quantum_Computing_Lab/EHC/build/bindings/python")
from decode import QueryService

app = Flask(__name__)
RUN_DIR = "/Users/stark/Quantum_Computing_Lab/MOE/WIKI"
QS = QueryService(RUN_DIR, dim=256, k=16)   # load once at startup

@app.route("/query", methods=["POST"])
def query():
    body = request.get_json(force=True) or {}
    res = QS.query(
        text=body.get("text", ""),
        subject=body.get("subject", ""),
        relation=body.get("relation", ""),
        obj=body.get("object", ""),
        k=int(body.get("k", 10)),
    )
    return jsonify(res)

@app.route("/stats", methods=["GET"])
def stats():
    return jsonify(QS.stats)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
```

Curl test:

```bash
curl -X POST http://localhost:8080/query \
    -H "Content-Type: application/json" \
    -d '{"subject": "france_under_the_third_republic", "relation": "capital", "k": 5}'
```

### Debug a single failing query (trace the routing)

When a specific query is returning nothing or the wrong rank, this
script shows the deterministic shard, the centroid-routed top-N
shards, the exhaustive result, and the candidate counts at each level.

```python
#!/usr/bin/env python3
"""query_trace.py — debug routing for one (s, r) query."""
import sys
sys.path.insert(0, "/Users/stark/Quantum_Computing_Lab/G.A8.1")
sys.path.insert(0, "/Users/stark/Quantum_Computing_Lab/EHC/build/bindings/python")
from decode import QueryService

RUN_DIR = "/Users/stark/Quantum_Computing_Lab/MOE/WIKI"
S, R   = "france_under_the_third_republic", "capital"

qs = QueryService(RUN_DIR, dim=256, k=16)
b = qs.backend

# 1) Where does deterministic routing point?
det_sid = b._route_deterministic(S, R)
print(f"deterministic shard = {det_sid}")

# 2) Where do centroid-top-8 routes point?
qvec = b._encode_tokens([S.lower(), R.lower()])
centroid_top = [int(s) for s in b.centroid_index.knn_query(qvec, k=8).ids]
print(f"centroid top-8 = {centroid_top}  "
      f"(deterministic in this set? {det_sid in centroid_top})")

# 3) Run each route mode and report.
for mode, n_shards in [("deterministic", 1), ("centroid", 8),
                        ("centroid", 32), ("centroid", 0)]:
    res = qs.query(subject=S, relation=R, k=5,
                   route_mode=mode, n_shards=n_shards)
    n = res["trace"].get("candidates", 0)
    sp = res["trace"].get("shards_probed", 0)
    top = res["results"][0] if res["results"] else None
    label = f"{mode} (n_shards={n_shards if n_shards>0 else 'all'})"
    print(f"  {label:35} candidates={n:>6}  shards={sp:>4}  "
          f"top={top['value'] if top else '<none>'!r}")
qs.close()
```

---

## What the encode contract guarantees end-to-end

The encode side establishes a contract; the decode side honors it
automatically as long as you match the layout. Here's what's enforced
in code so you don't have to think about it.

**Important caveat first:** the two encode paths use *different* vector
algebra under the hood:

- **`encode_triples.py` / `encode_unstructured.py`** (flat layout) call
  `ehc.StructuralPipelineV13` — the full C++ pipeline with slot +
  bigram + KV + (optional) Hebbian binding. `max_slots`, `enable_kv`,
  `hebbian_window` etc. all apply.
- **`encode.py` + `worker_encode.py`** (sharded layout) call plain
  `ehc.superpose(token_vecs)` — *no slot binding, no bigram, no KV.*
  The vector is just a superposition of the salient (or Tier-1) token
  codebook entries. `max_slots` is **not used** in this path.

So the recipe table below is a per-path matrix, not a single global
contract:

| Property | flat (`encode_triples`) | sharded (`encode.py`) |
|---|---|---|
| **`k = √D`** | ✓ `_autotune.predict_d_zone` + `autotune_dk` | ✓ same |
| **`max_slots = round(2·√k)`** (universal law) | ✓ via `build_sro_tier1_config` → `derive_k_constants`. The historical "+ p99 lift" was removed 2026-05-12; opt-in per corpus via `lift_for_p99=True`. | **N/A** — sharded path uses pure `ehc.superpose`; no slot table exists |
| **`max_salient_tokens = k // 2`** | N/A — flat path doesn't use salience | ✓ `worker_encode.py` calls `derive_k_constants` per-encode |
| **D grid `{256…16384}`** | ✓ `_autotune._GRID`, `decode13/profile/elbow.py:GRID_POWER_OF_TWO` | ✓ same |
| **Path-B-symmetric Tier-1** | ✓ `sro_tier1_encode_text(s, r)` = `f"{s} {r}"` | ✓ `structured_pipeline.tokens_from_triple` returns `[s, r]`; `worker_encode.py:572` calls it instead of hardcoding `(s, r, o)` |
| **O' in sidecar, not in vector** | ✓ sidecar `value` column carries full O | ✓ same — sidecar is per-shard EHS1 (or `texts.json` legacy) |
| **Deterministic Tier-1 routing** | N/A — single index, no routing needed | ✓ `query_service._route_deterministic` mirrors `encode._hash_entity` + `_nearest_cluster`; uses `manifest.json` + `clusters.json` |
| **Tier registry persistence** | N/A | ✓ requires `A81_TIER_ROUTED=1`; writes per-vector `tier_manifest.json` per shard |
| **Streaming source ingest** | ✓ `encode/_io.iter_json_records` (JSON-array OR JSONL) | ✓ same; `discover_clusters.py` uses reservoir sampling |

---

## Common gotchas

1. **Forgot `A81_TIER_ROUTED=1` on the sharded path.** Symptom:
   QueryServiceV13 startup logs `tier_counts={'structured_atomic': 0,
   'extracted_triple': 0, 'emergent_structure': 0}` — every vector
   classified as zero-tier. Recall drops to ~0%. Fix: re-encode with
   the env var set.

2. **Loaded the wrong decoder for the layout.** `decode.QueryService`
   on a sharded directory will fail trying to find `structural_v13/` at
   the root; `QueryServiceV13` on a flat directory will find zero shards
   and return empty results. The `ls` check at the top of this doc tells
   you which to use.

3. **Mismatched (D, k) between encode and decode.** Both decoders
   require `dim` and `k` to match what was encoded. The flat path can
   read these from `corpus_profile.json`; the sharded path reads from
   `manifest.json`. If you pass explicit values, they must match.

4. **Asymmetric encode and query atom sets.** This is the LSH-mismatch
   pathology that cost us most of a day. The encode and query MUST
   superpose the **same set of token atoms** for the LSH bucketing to
   align. Path-B-symmetric Tier-1 (encode `[s, r]`, query `[s, r]`) is
   what works at 99% recall. Path A (encode `[s, r, o]`, query `[s, r]`)
   collapses to ~2% recall via LSH bucket divergence at every D we
   tested.

5. **`route_mode="deterministic"` requires manifest + clusters.json
   present in `run_dir`.** If either is missing, `_route_deterministic`
   returns None. With `route_mode="auto"` (the default), the service
   silently falls back to centroid routing. With explicit
   `route_mode="deterministic"`, you get an empty result instead — that
   surfaces the missing-metadata bug instead of returning approximate
   answers.

6. **Sleep mode breaks long-running encodes.** macOS will suspend a
   detached `nohup` process under power management. For multi-hour
   encodes, use `caffeinate` or run on a Linux box with no auto-suspend.

---

## Where to add new code

If you want to extend or modify the decode behavior:

| You want to… | Edit |
|---|---|
| Add a new query routing strategy | `decode13/query_service.py:query` (extend `route_mode` enum) |
| Add a new tier (beyond 1/2/3) | `decode13/tier_types.py:Tier` enum + new `*_pipeline.py` |
| Change the (s, r) → shard partition function | `encode/encode.py:_hash_entity` AND `decode13/query_service.py:_hash_entity` (must stay in lockstep) |
| Add object-side reverse retrieval | new `(o, r)`-keyed parallel index (separate file in shard dirs) — out of current scope |
| Tweak the salience pool | `encode/worker_encode.py:_select_salient` |
| Update the autotune zone heuristic | `encode/_autotune.py:predict_d_zone` |

The split between `decode/` (flat compat shim) and `decode13/` (sharded
implementation) reflects two genuinely different on-disk shapes; it's
not a refactoring debt that should be collapsed into one file. The
unification opportunity is at the **public entry point** (a future
`decode.query.QueryService` that auto-detects layout and dispatches),
not at the implementation layer.

---

## Quick reference

```
ENCODE                                         DECODE
─────────────────────────────────────────────  ────────────────────────────────────
encode_triples.py     → flat layout
encode_unstructured   → flat layout              from decode import QueryService
A81_TIER_ROUTED=1                                qs = QueryService(path)
  encode.py           → sharded layout           qs.query(subject=..., relation=...)
                                                 # auto-detects layout, dispatches
                                                 # default route_mode="auto" on
                                                 # sharded → deterministic for SRO

LEGACY (still works, back-compat only):
  decode.query.QueryService                      ← flat-only direct access
  decode13.QueryServiceV13                       ← sharded-only direct access
```

Last validated: 2026-05-08, WIKI 21.3M corpus, both encode paths +
both decode paths, Path B symmetry confirmed end-to-end.
