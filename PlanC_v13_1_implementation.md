# v13.1 Corpus Profiler — Implementation Plan

Status: in-flight. Extends `PlanC.docx`. Pairs with
`PlanC_v13_1_1_amendments.md` (design refinements) and
`PlanC_cpp_engineer_memo.md` (gated questions).

## 1. Scope split

**Python-executable now** (no C++ dependency):

- `config.py` + `config.env` knobs
- `decode13/profile/` package (schema, source_hash, scanner, elbow, calibration)
- `encode/profile.py` CLI
- `tier_manifest.py` `dimensions` axis + grandfather sentinel
- `encode/encode.py` profile loading
- `decode13/query_service.py` dimensions verification
- unit tests

**C++-gated — implemented behind a flag, defaults OFF until cleared**:

- Extended grid {6144, 12288}. EHC BSC kernels may assume power-of-2 D in
  codebook arithmetic, LSH hash routing, or SIMD pack sizes. Plan ships
  `A81_DIMENSIONS_GRID_EXTENDED=false` default. Flipping to true without
  C++ sign-off will crash at encode time — that is the intended loud
  failure mode.

## 2. Design decisions carried forward

Recorded here so the code is auditable against the conversation.

1. **§4.4 rewrite.** Stage-2 calibration measures capacity regimes 1 and
   2 (atomic recovery, superposition) directly. Regime 3 (retrieval-at-
   scale) is *not* measured by this design; the 1.2× multiplier is an
   operator-judgment policy choice for corpus-size-dependent risk, not
   a derived engineering number. Code comments say this out loud.

2. **Calibration queries.** Priority order: operator-supplied held-out
   (prod default) → corpus-derived from query logs if available →
   synthetic mask-one-field (dev/testing only, emits a loud warning that
   the resulting recall@10 is a ceiling measurement).

3. **source_hash.** Sampled-content hash: record-count + total-byte-size
   + SHA-256 of N deterministic byte offsets. Catches in-place edits the
   naïve "path + count + first/last" design misses. Still O(1) time.

4. **Elbow threshold.** 2% of the remaining-accuracy-budget
   (`1.0 - current_recall`), not 1 pp absolute. Tier-1 at baseline 0.99
   uses threshold ~0.0002; Tier-2 at baseline 0.64 uses ~0.0072. Both
   principled.

5. **Latency in the sweep.** Each (D, k) row records p50/p95 query
   latency in addition to recall@10. Profile JSON carries both. Elbow
   detection returns a recall-elbow and a latency-front so operators can
   pick their own operating point.

6. **Manifest `dimensions` axis.** Hard axis in the composite hash.
   Grandfather: legacy shards lacking the field load with sentinel
   `"v13.0-default"` which maps to the hardcoded D=16384/k=128 at query
   time. Re-profile + re-encode is the customer-initiated trigger, not
   the v13.1 deploy.

7. **Partial CLI override.** `--dim` without `--k` takes k from profile
   if present else cfg default. Either path stamps `override=cli` in the
   manifest so the provenance survives audit.

8. **Per-tier policy field** in the profile schema: reserved but
   **not wired**. Calling with `policy="per_tier"` raises
   `NotImplementedError`. The schema reservation is opt-in ground-work
   for v13.2, not a promise v13.1 fulfils.

9. **Sample size scaling.** `min(50000, max(10000, int(corpus_size * 0.005)))`.
   Floor 10K for small corpora, cap 50K for operational sanity, 0.25%
   sampling on large corpora (50K at 10M+). 0.05% at 21M was too thin.

## 3. Manifest dimensions semantics

Symbolic, not semantic. The `dimensions` axis carries a string like
`"D16384:k128"`. Two shards are compatible only if their dimensions
strings match exactly. `"v13.0-default"` is its own distinct value:

- v13.0 shards (no field on disk) load with `"v13.0-default"` via the
  `ComponentVersions` default.
- v13.1 shards re-encoded at exactly D=16384/k=128 carry
  `"D16384:k128"` and are **not** compatible with legacy shards (even
  though the geometry matches). This is intentional — different
  manifest values capture different encoding provenance (profile-backed
  vs. hardcoded). Operators who want to merge the two pools do a full
  re-profile + re-encode of the legacy pool.

Query-time, the runtime decodes `"v13.0-default"` → `(D=16384, k=128)`
for the BSC cosine kernel. Any other value is parsed as `D{n}:k{m}`.
Malformed values abort load.

## 4. Execution order

1. Plan docs (this file + amendments + memo). (task 53)
2. Config knobs. (task 54)
3. Profile schema + source_hash. (task 55)
4. Stage 1 scanner. (task 56)
5. Elbow detection. (task 57)
6. Stage 2 calibration. (task 58)
7. Profile CLI. (task 59)
8. TierManifest extension. (task 60)
9. encode.py integration. (task 61)
10. query_service verification. (task 62)
11. Tests. (task 63)
12. Run suite. (task 64)

## 5. Out of scope for v13.1

- Per-tier partitioned shards (schema-reserved, raises).
- Online profile refinement.
- Non-power-of-2 dimensions (behind `A81_DIMENSIONS_GRID_EXTENDED`).
- k values outside `{√D/2, √D, 2√D}`.
- Cross-D query padding.

## 6. Validation plan

Covered by unit tests this session. Corpus-scale validation (Phase B
in PlanC §9.2 — 21M Wikidata, 220K edge, mixed) remains manual once a
shard is re-encoded under a profile. Not automated this session.
