# fault_diag — hydraulic-fault diagnosis prototype

Product corpus + hooks for the "input fault code, get past resolutions"
use case. Built against the UCI Hydraulic Systems Condition Monitoring
dataset as a public stand-in for real factory robot telemetry +
technician resolution logs.

## What's in here (code only — data artifacts untracked)

| file | purpose |
|---|---|
| `hooks.py` | Product hooks. Provides `query_cleaner(text)` that maps free-form NL ("the cooling system is broken") to canonical `subject relation` form, and `get_hooks(index_dir=None)` for `load_hooks(product_dir=...)` auto-discovery. Lazy-imports `HookSet` / `CleanedQuery` so the file is standalone-safe when the edge `hooks` module isn't on path. |
| `regression_probes.py` | Deterministic probe — emits sha256-truncated digest of 13 canonical queries. Pinned at `14f142473860f2e7`; exits non-zero on drift. Run after any change that could affect retrieval. |
| `probe.py` | Demo: 5-query NL → retrieval walk-through. Not used in CI. |

## What's NOT in here (regenerable, kept locally only)

- `hyd_events.jsonl` / `hyd_resolutions.jsonl` / `hyd_triples.jsonl` — synthesized
  event-stream + resolution-log + SRO triples (2,195 / 2,195 / 12,520 rows).
- `encoded_hyd_d512/` — encode_triples shard @ D=512, k=64.
- `nhtsa_camry_2017_diag.jsonl`, `obd2_p0_codes.jsonl`,
  `triplex_fault_catalog.json` — reference slices used during ingestion design.

## Regenerating from scratch

1. Pull UCI Hydraulic Systems dataset (zip from
   https://archive.ics.uci.edu/dataset/447), extract to `/tmp/uci_hydraulic/`.
2. Build `hyd_events.jsonl` from `profile.txt` + sensor files (one
   summary-stat row per cycle).
3. Synthesize `hyd_resolutions.jsonl` keyed by `event_id` using the
   per-fault-class resolution templates documented in `progress.txt`
   (2026-05-19 entry).
4. Emit `hyd_triples.jsonl` — 5 SRO triples per event (`resolved_by`,
   `requires_part`, `occurs_on`, `reported`, `co_occurs_with`).
5. Encode:
   ```bash
   PYTHONPATH=/opt/EHC/install/linux-x86_64:/opt/G.A8.1 \
     python3 -m encode.encode_triples \
       --source /opt/G.A8.1/data/fault_diag/hyd_triples.jsonl \
       --output /opt/G.A8.1/data/fault_diag/encoded_hyd_d512 \
       --dim 512 --k 64 --no-autotune --force
   ```
6. Verify:
   ```bash
   PYTHONPATH=/opt/EHC/install/linux-x86_64:/opt/G.A8.1 \
     python3 /opt/G.A8.1/data/fault_diag/regression_probes.py
   # → digest=14f142473860f2e7  expected=14f142473860f2e7  rows=13  OK
   ```

## Notes on retrieval accuracy (post-encode)

- Top-5 fix accuracy: 100% across all 11 primary codes, including the
  rarest (1.0% of corpus).
- Latency: p50=0.51 ms, p95=4.2 ms over 200 queries.
- Warm-vs-cold separation: known code sim=1.000, unknown sim=0.328 —
  the 0.32 floor is a usable reject threshold for routing to a human.
- NL routing accuracy: 10/10 on the 13-probe test set after `low`
  severity tag was moved from `LOW_SEV` to `LOW_SLT` in the catalog.

## Open work

- Domain reranker hook — current default is generic `50% BSC + 40% KW
  + 10% proximity`. For maintenance-domain retrieval the useful signals
  are tech consensus, recency, success rate, and time-to-fix. Sketched
  but not yet built.
- Embedder-based fallback for NL queries that miss the lexical
  catalog — either reuse the existing HDC encoder on
  `(code, has_description, text)` triples, or layer a small sentence
  embedding model. HDC-native is the cleaner path because it stays in
  one vector space and ships to edge with the rest.
