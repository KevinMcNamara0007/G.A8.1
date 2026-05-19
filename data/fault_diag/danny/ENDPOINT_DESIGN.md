# Endpoint design — native C++ sim-run ingest in RESTWRAPPER

Goal: Danny POSTs his MATLAB-exported CSV (per `SPEC.md`) to RESTWRAPPER,
RESTWRAPPER ingests it natively (no Python at runtime), and the same
service answers queries. Auth via the existing `X-API-Key` header
(or new bearer middleware — see Open Question 1).

## Routes

```
POST /v1/sim_runs/ingest
  Headers:  X-API-Key, Content-Type: text/csv
  Body:     the CSV (one row per sim run, columns per SPEC.md)
  Response: { ok, run_count, triples_emitted, shard_path,
              encode_seconds, breakpoints (per-feature, for transparency) }

POST /v1/sim_runs/query
  Headers:  X-API-Key, Content-Type: application/json
  Body:     { text: "TORQUE_SPIKE@HumanoidArm_v1 has_run", k: 10 }
  Response: { results: [{ doc_id, similarity, metadata }] }

GET  /v1/sim_runs/health
  Response: { ok, shard_loaded, total_vectors, dim, k, last_ingest_ts }
```

## C++ work breakdown

### New files (estimated ~600 LOC total)

| file | LOC | purpose |
|---|---|---|
| `src/routes/sim_runs.cpp` | ~150 | route registration; thin handlers that delegate to the modules below |
| `src/sim_runs/csv_parser.{cpp,hpp}` | ~80 | small CSV → `vector<unordered_map<string,string>>`. Hand-rolled (no comma-in-quotes, no escapes — the SPEC.md format doesn't need them). |
| `src/sim_runs/triple_emitter.{cpp,hpp}` | ~150 | percentile breakpoint computation, feature quantization, the 6-triples-per-row emission with metadata. Writes `triples.jsonl` and `corpus.jsonl`. |
| `src/sim_runs/encoder_session.{cpp,hpp}` | ~100 | wraps `ehc::StructuralPipelineV13` lifecycle (build cfg → ingest_batch_parallel → save). Handles concurrency (one ingest at a time per shard; query is concurrent). |
| `include/restwrapper/routes.hpp` (edit) | +1 | declare `register_sim_runs_routes()` |
| `src/main.cpp` (edit) | +1 | call the register fn |
| `CMakeLists.txt` (edit) | +5 | new sources |
| `openapi.yaml` (edit) | +60 | route specs |

### EHC APIs already exposed (validated against headers)

- `ehc::pipeline::StructuralPipelineV13` (in `ehc/pipeline/structural_v13.hpp`)
  - `int64_t ingest_text(const std::string&, int64_t doc_id = -1)`
  - `void ingest_batch(...)`, `void ingest_batch_parallel(texts, ids, n_threads)`
  - `void save(const std::string& dir)`
- `ehc::sidecar::JsonlAppender` (in `ehc/sidecar/jsonl_appender.hpp`) — already
  the C++ class wired into `encode_triples.py` per INTEG-01. We use it directly
  here so the corpus.jsonl writer is consistent.

### What we re-implement vs reuse

- **Encoding kernel:** reuse `StructuralPipelineV13` directly. No reimplementation.
- **Text key formatting:** trivial in C++ (`subject + " " + relation`). Tier-1
  SRO contract is just two tokens concatenated.
- **Quantization (33/66 percentile):** ~20 lines of std::sort + index lookup.
- **CSV parsing:** hand-rolled, ~40 lines. Sufficient for the SPEC.md format.
- **JSON metadata:** `nlohmann::json` is already a dep of RESTWRAPPER.

## Data flow

```
                ┌──────────────────────────────────────────┐
   POST CSV ──▶ │ sim_runs.cpp                              │
                │  ├─ csv_parser  → vector<row_map>         │
                │  ├─ triple_emitter:                       │
                │  │    1. compute percentile breakpoints   │
                │  │    2. quantize feature columns          │
                │  │    3. emit 6 triples per row           │
                │  │    4. build texts[] (subject+relation) │
                │  │    5. build metadata[]                  │
                │  └─ encoder_session:                      │
                │       1. cfg = build_sro_tier1_config()   │
                │       2. pipe = StructuralPipelineV13     │
                │       3. ingest_batch_parallel(texts,ids) │
                │       4. JsonlAppender writes sidecar     │
                │       5. pipe.save(shard_dir)             │
                │  └─ return JSON summary                   │
                └───────────────────────────────────────────┘
```

## Open questions (need decisions before coding)

1. **Auth header.** Existing routes use `X-API-Key`. You picked "bearer" in
   the earlier prompt. Options:
     a. Keep `X-API-Key` for the new routes (consistency, no middleware change).
     b. Add bearer support across the service (touches `auth.cpp`).
     c. Bearer just for `/v1/sim_runs/*`, X-API-Key on the rest. Inconsistent
        but isolates the change.
   Recommend (a) for v1.

2. **Shard lifecycle.** What happens when Danny posts a second CSV?
     a. Append to existing shard (incremental ingest — `StructuralPipelineV13`
        supports it, but corpus.jsonl needs careful append).
     b. New shard per request; query route picks the latest. Simpler.
     c. Named shards: Danny passes `?shard=danny_2026_05_19` and queries
        target a specific one. Most flexible.
   Recommend (b) for v1, (c) later.

3. **Encoder geometry.** Hardcode D=512, k=23 (canonical) or accept as
   query params?
   Recommend hardcode for v1; expose later if Danny needs to experiment.

4. **Ingest concurrency.** Two simultaneous ingests on the same shard would
   race. A simple per-shard `std::mutex` (already in `StructuralPipelineV13`)
   handles this, but if ingest takes minutes the second request would block.
   For v1 the dataset is small (~190 rows → <1s encode), so this is fine.
   At customer scale we'd want async accept + status polling.

## Risks

- **CMake link order.** RESTWRAPPER currently links `libehc.a` for the
  routes that use `ehc::edge::*` etc. The pipeline class is in the same
  library, so it should link cleanly. Unknown: whether the static-lib build
  of EHC has been exercised against `StructuralPipelineV13` (no existing
  RESTWRAPPER route uses it).
- **Result parity with Python.** corpus.jsonl format and triple-ordering
  needs to match what Python emits so any downstream consumer (regression
  probes, Mario's eyeballing) sees the same shape. We'll write a small
  cross-check: encode the sample CSV via both paths, diff the corpus.jsonl
  byte-for-byte (modulo timestamps).
- **Multipart vs raw text/csv body.** Crow handles raw bodies easily; multipart
  is more code. Going with `Content-Type: text/csv` on the body — Danny's
  curl command becomes `curl -H "Content-Type: text/csv" --data-binary @file.csv`.

## Out of scope for v1

- Streaming uploads (large CSVs over multi-megabyte threshold)
- Async ingest with job status polling
- Shard list / delete / TTL
- Auto-generated breakpoints from a held-out training set
  (v1 computes from each batch — fine for Danny's expected single-shot use)

## Acceptance test (the demo we'll show Danny)

```bash
# Ingest
curl -X POST https://letthegamesbegin.ai/v1/sim_runs/ingest \
     -H "X-API-Key: $KEY" \
     -H "Content-Type: text/csv" \
     --data-binary @sample_sim_dataset.csv
# → {"ok": true, "run_count": 190, "triples_emitted": 1130, ...}

# Query
curl -X POST https://letthegamesbegin.ai/v1/sim_runs/query \
     -H "X-API-Key: $KEY" \
     -H "Content-Type: application/json" \
     -d '{"text": "TORQUE_SPIKE@HumanoidArm_v1 has_run", "k": 5}'
# → {"results": [{"similarity": 1.0, "metadata": {"run_id":"sim_0058", ...}}, ...]}
```

Same shapes as the existing Python pipeline produces. Same retrieval
semantics. Danny doesn't need a Python interpreter on his side.

## Estimated effort

- Design (this doc): done
- Coding (3 modules + handler + tests): ~4 h
- CMake + build + first link: ~30 min
- openapi.yaml + smoke test against the real endpoint: ~1 h
- Total: **~5–6 h of focused work**

Recommend doing it in two passes:
- Pass 1: route + handler stubs that parse CSV and emit triples to disk
  (no encoding yet). Verify CSV → corpus.jsonl matches Python output.
- Pass 2: wire the encoder, hook up query route, openapi + acceptance test.
