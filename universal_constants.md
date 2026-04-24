# Universal Constants — Discovered Per-Corpus Geometries

Append-only audit log of autotune decisions. Each entry below is
written by `encode_triples.py` or `encode_unstructured.py` after
a successful sweep. Use as institutional memory — when a new
corpus shape is encoded, the precedent here can guide initial
configuration without re-running a full sweep.

## Hints

**For narrative corpora**, supply `--operator-queries` pointing at
a JSONL of `{query_text, gold_ids: [doc_id]}` entries derived
from your real query patterns. Without operator queries, autotune
falls back to a synthetic mask-first heuristic that systematically
under-scores narrative corpora and biases the winner toward
larger D than the real task needs.

For edge-shape social-media corpora, generate the canonical
25-pattern operator query set with:
```
python -m decode13.benchmark.build_edge_queries \
    --source <corpus.jsonl> --output <edge_queries.jsonl>
```

**For SRO Tier-1 corpora**, autotune uses unique-(s,r) self-identity
as the oracle — no operator queries needed.

## How to run (canonical commands)

Paths follow the `/MOE/<EXPERT>/` convention. Legacy `/OUT*` dirs are
deprecated; do not recreate them.

### Encode SRO triples (Tier-1)
```bash
cd /Users/stark/Quantum_Computing_Lab/G.A8.1
python3 -m encode.encode_triples \
    --source /Users/stark/Quantum_Computing_Lab/GoldC/triples_21M.json \
    --output /Users/stark/Quantum_Computing_Lab/MOE/WIKI \
    --force
```
Autotune oracle is built-in (unique-(s,r) self-identity). No operator
queries needed.

### Encode narrative text (Tier-2) — two steps
```bash
# 1. Build the operator-query oracle from the source corpus
cd /Users/stark/Quantum_Computing_Lab/G.A8.1
python3 -m decode13.benchmark.build_edge_queries \
    --source /Users/stark/Quantum_Computing_Lab/MOE/EDGE/source_corpus.jsonl \
    --output /Users/stark/Quantum_Computing_Lab/MOE/EDGE/operator_queries.jsonl

# 2. Encode with those queries scoring the autotune sweep
python3 -m encode.encode_unstructured \
    --source /Users/stark/Quantum_Computing_Lab/MOE/EDGE/source_corpus.jsonl \
    --output /Users/stark/Quantum_Computing_Lab/MOE/EDGE \
    --operator-queries /Users/stark/Quantum_Computing_Lab/MOE/EDGE/operator_queries.jsonl \
    --force
```
**Skipping `--operator-queries` on narrative corpora drops Hit@1 to the
synthetic-oracle ceiling (~20% vs 52%).** Always generate operator
queries first. For non-edge domains, copy `build_edge_queries.py` and
edit the `QUERIES` list for your vocabulary.

### Skip autotune (known-good pin)
```bash
python3 -m encode.encode_{triples|unstructured} \
    --source ... --output ... \
    --dim 4096 --k 64 --no-autotune
```

### Benchmark an encoded shard
```bash
python3 -m decode13.benchmark.run \
    --index-path /Users/stark/Quantum_Computing_Lab/MOE/EDGE \
    --queries   /Users/stark/Quantum_Computing_Lab/MOE/EDGE/operator_queries.jsonl \
    --warmup 20
```

### Wire a shard to the edge service
`start.sh` in `MjolnirPhotonics/product.edge.analyst.bsc/edge_service/`
reads `A81_INDEX_PATH`. Default is `/MOE/EDGE`. To point at a different
expert, export before starting:
```bash
cd MjolnirPhotonics/product.edge.analyst.bsc/edge_service
export A81_INDEX_PATH=/Users/stark/Quantum_Computing_Lab/MOE/WIKI
./stop.sh && ./start.sh
```
The service imports G.A8.1 in-process via the shim at
`decode/query.py` (with `query_service.py` as back-compat fallback).

### Source-file formats (auto-detected)
Both encoders accept either:
  - **JSONL** — one JSON object per line (the default staging format)
  - **JSON array** — a single `[{...}, {...}, ...]` file (Wikidata / DBpedia
    dumps ship this way; parse streams from disk in constant memory)

No pre-conversion step. Detection is by peeking the first non-whitespace
character. Implementation in `encode/_io.py::iter_json_records`.

### What each encode produces in `<output>/`
  - `structural_v13/`    — saved EH pipeline (weights + config)
  - `corpus.jsonl`       — sidecar, one row per encoded doc, id-ordered
  - `corpus_profile.json`— atom histogram + p99 + autotune sweep result
  - (autotune run also appends a section to this file — `universal_constants.md`)

---

## OUT-EDGE-NEW
- **Date**: 2026-04-24T04:34:17+00:00
- **Note**: initial smoke test — synthetic mask-first queries gave near-zero Hit@1; biased toward larger D
- **Encoder**: `encode_unstructured (smoke v1: synthetic queries)`
- **Source**: `/Users/stark/Quantum_Computing_Lab/OUT/corpus.jsonl`
- **Records**: 220,025
- **p99 atoms/record**: 65
- **Predicted zone**: [8192, 16384, 32768]  (long narrative regime (synthetic, narrow zone — early version))
- **Swept zone**: [8192, 16384, 32768]
- **Sweep results**:
  | D | k | Hit@1 | p50 ms |
  |---:|---:|---:|---:|
  | 8192 | 91 | 0.51% | 1.16 |
  | 16384 | 128 | 1.02% | 1.35 |
  | 32768 | 181 | 1.52% | 2.74 | ← winner
- **Winner**: D=32768, k=181, Hit@1=1.52%, p50=2.74 ms

---

## OUT-EDGE-NEW
- **Date**: 2026-04-24T04:34:17+00:00
- **Note**: swapped synthetic→operator queries; numbers improved 10× but D=4096 still excluded by zone prediction
- **Encoder**: `encode_unstructured (smoke v2: operator queries, narrow zone)`
- **Source**: `/Users/stark/Quantum_Computing_Lab/OUT/corpus.jsonl`
- **Records**: 220,025
- **p99 atoms/record**: 65
- **Predicted zone**: [8192, 16384, 32768]  (long narrative regime (operator-scored, narrow — pre-fix))
- **Swept zone**: [8192, 16384, 32768]
- **Sweep results**:
  | D | k | Hit@1 | p50 ms |
  |---:|---:|---:|---:|
  | 8192 | 91 | 8.00% | 1.03 |
  | 16384 | 128 | 8.00% | 1.04 |
  | 32768 | 181 | 20.00% | 1.65 | ← winner
- **Winner**: D=32768, k=181, Hit@1=20.00%, p50=1.65 ms
- **vs prior** (2026-04-24T04:34:17+00:00): prior winner D=32768/k=181 Hit@1=1.52% p50=2.74ms  →  this run: ΔHit@1=+18.48pp  Δp50=-1.09ms  (same geometry)

---

## OUT-EDGE-NEW
- **Date**: 2026-04-24T04:34:17+00:00
- **Note**: widened zone to include D=4096; surfaced separate doc_id misalignment bug (autotune indexed records under post-skip enumerate index, gold lookups missed)
- **Encoder**: `encode_unstructured (smoke v3: wide zone, doc_id misalignment)`
- **Source**: `/Users/stark/Quantum_Computing_Lab/OUT/corpus.jsonl`
- **Records**: 220,025
- **p99 atoms/record**: 65
- **Predicted zone**: [4096, 8192, 16384, 32768]  (long narrative regime (full sweep, but autotune used post-skip enum index — silent bug))
- **Swept zone**: [4096, 8192, 16384, 32768]
- **Sweep results**:
  | D | k | Hit@1 | p50 ms |
  |---:|---:|---:|---:|
  | 4096 | 64 | 0.00% | 0.94 |
  | 8192 | 91 | 8.00% | 1.00 |
  | 16384 | 128 | 8.00% | 1.06 |
  | 32768 | 181 | 20.00% | 1.65 | ← winner
- **Winner**: D=32768, k=181, Hit@1=20.00%, p50=1.65 ms
- **vs prior** (2026-04-24T04:34:17+00:00): prior winner D=32768/k=181 Hit@1=20.00% p50=1.65ms  →  this run: ΔHit@1=+0.00pp  Δp50=+0.00ms  (same geometry)

---

## OUT-EDGE-NEW
- **Date**: 2026-04-24T04:34:17+00:00
- **Note**: fixed autotune to use source doc_id (not post-skip enum); operator-query Hit@1 now matches yesterday's edge_prod_runner reality
- **Encoder**: `encode_unstructured (smoke v4: doc_id fix)`
- **Source**: `/Users/stark/Quantum_Computing_Lab/OUT/corpus.jsonl`
- **Records**: 220,025
- **p99 atoms/record**: 65
- **Predicted zone**: [4096, 8192, 16384, 32768]  (long narrative regime (full sweep — formula over-predicts))
- **Swept zone**: [4096, 8192, 16384, 32768]
- **Sweep results**:
  | D | k | Hit@1 | p50 ms |
  |---:|---:|---:|---:|
  | 4096 | 64 | 28.00% | 0.74 |
  | 8192 | 91 | 44.00% | 0.91 | ← winner
  | 16384 | 128 | 28.00% | 1.10 |
  | 32768 | 181 | 40.00% | 2.48 |
- **Winner**: D=8192, k=91, Hit@1=44.00%, p50=0.91 ms
- **vs prior** (2026-04-24T04:34:17+00:00): prior winner D=32768/k=181 Hit@1=20.00% p50=1.65ms  →  this run: ΔHit@1=+24.00pp  Δp50=-0.74ms  (D shifted 32768→8192)

---

## OUT-EDGE-NEW
- **Date**: 2026-04-24T04:38:48+00:00
- **Encoder**: `encode_unstructured`
- **Source**: `/Users/stark/Quantum_Computing_Lab/OUT/corpus.jsonl`
- **Records**: 220,025
- **p99 atoms/record**: 65
- **Predicted zone**: [4096, 8192, 16384, 32768]  (long narrative regime (full sweep — formula over-predicts))
- **Swept zone**: [4096, 8192, 16384, 32768]
- **Sweep results**:
  | D | k | Hit@1 | p50 ms |
  |---:|---:|---:|---:|
  | 4096 | 64 | 52.00% | 1.07 | ← winner
  | 8192 | 91 | 36.00% | 0.94 |
  | 16384 | 128 | 28.00% | 2.09 |
  | 32768 | 181 | 44.00% | 2.12 |
- **Winner**: D=4096, k=64, Hit@1=52.00%, p50=1.07 ms
- **vs prior** (2026-04-24T04:34:17+00:00): prior winner D=8192/k=91 Hit@1=44.00% p50=0.91ms  →  this run: ΔHit@1=+8.00pp  Δp50=+0.16ms  (D shifted 8192→4096)

---

## EDGE
- **Date**: 2026-04-24T04:43:48+00:00
- **Encoder**: `encode_unstructured`
- **Source**: `/Users/stark/Quantum_Computing_Lab/MOE/EDGE/source_corpus.jsonl`
- **Records**: 220,025
- **p99 atoms/record**: 65
- **Predicted zone**: [4096, 8192, 16384, 32768]  (long narrative regime (full sweep — formula over-predicts))
- **Swept zone**: [4096, 8192, 16384, 32768]
- **Sweep results**:
  | D | k | Hit@1 | p50 ms |
  |---:|---:|---:|---:|
  | 4096 | 64 | 52.00% | 0.74 | ← winner
  | 8192 | 91 | 36.00% | 0.97 |
  | 16384 | 128 | 28.00% | 1.98 |
  | 32768 | 181 | 44.00% | 2.27 |
- **Winner**: D=4096, k=64, Hit@1=52.00%, p50=0.74 ms

---

## WIKI
- **Date**: 2026-04-24T13:05:38+00:00
- **Encoder**: `encode_triples`
- **Source**: `/Users/stark/Quantum_Computing_Lab/MOE/WIKI/source_corpus.jsonl`
- **Records**: 977,051
- **p99 atoms/record**: 2
- **Predicted zone**: [4096, 8192]  (atomic SRO regime)
- **Swept zone**: [4096, 8192]
- **Sweep results**:
  | D | k | Hit@1 | p50 ms |
  |---:|---:|---:|---:|
  | 4096 | 64 | 100.00% | 7.33 | ← winner
  | 8192 | 91 | 100.00% | 10.42 |
- **Winner**: D=4096, k=64, Hit@1=100.00%, p50=7.33 ms

---

## WIKI
- **Date**: 2026-04-24T13:40:14+00:00
- **Encoder**: `encode_triples`
- **Source**: `/Users/stark/Quantum_Computing_Lab/MOE/WIKI/source_corpus.jsonl`
- **Records**: 977,051
- **p99 atoms/record**: 2
- **Predicted zone**: [4096, 8192]  (atomic SRO regime)
- **Swept zone**: [4096, 8192]
- **Sweep results**:
  | D | k | Hit@1 | p50 ms |
  |---:|---:|---:|---:|
  | 4096 | 64 | 100.00% | 9.90 | ← winner
  | 8192 | 91 | 100.00% | 14.09 |
- **Winner**: D=4096, k=64, Hit@1=100.00%, p50=9.90 ms
- **Derived constants** (at k=64): max_slots=16  (=round(2·√k))  •  salient_tokens=8  (=round(√k))
- **vs prior** (2026-04-24T13:05:38+00:00): prior winner D=4096/k=64 Hit@1=100.00% p50=7.33ms  →  this run: ΔHit@1=+0.00pp  Δp50=+2.57ms  (same geometry)

---

## WIKI
- **Date**: 2026-04-24T13:55:20+00:00
- **Encoder**: `encode_triples`
- **Source**: `/Users/stark/Quantum_Computing_Lab/MOE/WIKI/source_corpus.jsonl`
- **Records**: 977,051
- **p99 atoms/record**: 2
- **Predicted zone**: [4096, 8192]  (atomic SRO regime)
- **Swept zone**: [4096, 8192]
- **Sweep results**:
  | D | k | Hit@1 | p50 ms |
  |---:|---:|---:|---:|
  | 4096 | 64 | 100.00% | 7.38 | ← winner
  | 8192 | 91 | 100.00% | 10.43 |
- **Winner**: D=4096, k=64, Hit@1=100.00%, p50=7.38 ms
- **Derived constants** (k=64, p99=2): max_slots=16  (=2·√k)  •  salient_tokens=8  (=√k)
- **vs prior** (2026-04-24T13:40:14+00:00): prior winner D=4096/k=64 Hit@1=100.00% p50=9.90ms  →  this run: ΔHit@1=+0.00pp  Δp50=-2.52ms  (same geometry)

---

## EDGE
- **Date**: 2026-04-24T13:56:33+00:00
- **Encoder**: `encode_unstructured`
- **Source**: `/Users/stark/Quantum_Computing_Lab/MOE/EDGE/source_corpus.jsonl`
- **Records**: 220,025
- **p99 atoms/record**: 65
- **Predicted zone**: [4096, 8192, 16384, 32768]  (long narrative regime (full sweep — formula over-predicts))
- **Swept zone**: [4096, 8192, 16384, 32768]
- **Sweep results**:
  | D | k | Hit@1 | p50 ms |
  |---:|---:|---:|---:|
  | 4096 | 64 | 52.00% | 0.99 | ← winner
  | 8192 | 91 | 32.00% | 1.27 |
  | 16384 | 128 | 28.00% | 1.64 |
  | 32768 | 181 | 44.00% | 3.09 |
- **Winner**: D=4096, k=64, Hit@1=52.00%, p50=0.99 ms
- **Derived constants** (k=64, p99=65): max_slots=65  (=max(2·√k, p99) (p99=65))  •  salient_tokens=8  (=√k)
- **vs prior** (2026-04-24T04:43:48+00:00): prior winner D=4096/k=64 Hit@1=52.00% p50=0.74ms  →  this run: ΔHit@1=+0.00pp  Δp50=+0.25ms  (same geometry)

---

