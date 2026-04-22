# PlanC v13.1.1/v13.1.2 — Amendments

## v13.1.3 — three-zone plateau-aware selection

v13.1.2's binary confidence gate ("confident downsize" vs "retreat to
max") collapsed two distinct low-signal cases that require opposite
responses:

- **Plateau (noise with high absolute recall):** multiple D values
  produce indistinguishable recall, all well above an absolute floor.
  Data is telling us D doesn't matter in this regime. The conservative
  choice is the **smallest** D in the plateau — smaller memory at the
  same measured outcome.
- **Capacity pressure (noise with low absolute recall):** every
  measured D produces poor retrieval. Data is telling us the corpus
  may be capacity-bound. Retreating to cfg default is right.

v13.1.3 replaces the binary gate with four zones:

  | Zone              | Trigger                                                                  | Action                                                                             |
  |-------------------|--------------------------------------------------------------------------|------------------------------------------------------------------------------------|
  | confident         | spread > 1.5 × noise AND N ≥ 50 AND plateau-doesn't-fire                | Pareto-front max-recall pick                                                       |
  | plateau           | ≥3 distinct Ds within 0.05 of best_recall AND best_recall ≥ 0.5          | smallest D in plateau; `headroom > 1.0` promotes to in-plateau next-larger grid D  |
  | capacity_pressed  | best_recall < 0.5                                                        | cfg default (v13.0 geometry)                                                       |
  | ambiguous         | none of the above                                                        | cfg default                                                                        |

Profile JSON now carries `zone`, `plateau_dims`, `best_recall`,
`confidence`, and `selection_reason` so operators can audit the
decision.

Default headroom restored to **1.2**. The earlier concern was that 1.2
compounded the D-collapse bug; in plateau context the promotion is
measurement-supported (target D must itself be in the plateau) so
the multiplier is principled. `1.0` = pick the minimum-memory floor
exactly.

On the edge corpus this produces: plateau detected at
`[4096, 6144, 8192, 12288, 16384, 32768]` within 0.05 of best recall
0.840; smallest-D = 4096; headroom 1.2 promotes to **D=6144/k=78**.
The v13.1.0 answer through correct reasoning — exactly as the
production-readiness review predicted.

## v13.1.2 production-readiness fixes

Three bugs found in v13.1.0 during the end-to-end edge-corpus
validation. All three shipped fixes alongside these amendments.

### 1. Query count scaling with sample size

v13.1.0 defaulted calibration queries to 200 regardless of sample
size. On the 220K edge corpus (3,395 sample) that gave 25 operator
queries — a noise bound of ~0.167 on recall@10. Elbow differences
below ~17 pp were indistinguishable.

**Fix:** `--queries` default is now `max(200, sample_size // 17)` —
roughly one query per 17 sample records, delivering ~4–5 pp noise
at sample=10K–50K. Operator-supplied query files keep their count
unchanged, but the CLI warns loudly when the count is below 100
and the selector's noise guard (#2) handles the fallback.

### 2. Confidence guard / noise-bound sanity check

v13.1.0 always produced a recommendation. When recall barely moved
across the sweep, the elbow logic still returned a confident-looking
D — overselling the measurement's precision.

**Fix:** the selector now computes a Wilson-style 95% CI half-width
from `(num_queries, mean_recall)`. If the observed recall spread is
smaller than 1.5× noise bound, or fewer than 50 queries ran, the
selector refuses to downsize and falls back to
`(cfg.DIM, cfg.K)` — the v13.0 default — which the grandfather
sentinel path then honors.

Profile JSON stamps:

- `confidence: "high" | "medium" | "low"`
- `selection_reason: str` — human-readable explanation
- `num_calibration_queries: int`
- `elbow_analysis.noise_bound: float`
- `elbow_analysis.recall_spread: float`

**Why:** the old selector was a "happy accident" on the validation
corpus — it picked D=6144/k=78 with 25 queries because the algorithm
landed there, not because the data supported the claim. The guard
makes low-signal cases honest.

### 3. Joint (D, k) Pareto selection replaces D-first-then-fixed-k

v13.1.0 collapsed to `max recall per D, elbow over D, then k=√D`.
That path picked D=6144/k=78 for the edge corpus even though the
measured sweep had D=8192/k=45 with **higher recall AND lower
latency** — strictly dominant on both axes. The fix k-ratio
assumption hid the real optimum.

**Fix:** selection now runs over every (D, k) measurement jointly.
Pareto-front by (worst-tier recall, p50 latency). Among front
points, pick max recall; tie-break lower latency; tie-break smaller
memory footprint (D×k). Per-tier elbow lands in the profile as a
diagnostic field only, not as a driver of the recommendation.

**Headroom semantics changed.** The old 1.2× multiplier applied
automatically to the chosen D was the mechanism that compounded the
D-collapse bug (4096 × 1.2 → round-up → 6144, different k than
measured). The v13.1.2 default is 1.0 (trust the measurement). When
set >1.0, headroom now promotes the pick to the next-larger grid
dim **only if** the sweep showed recall there at or above the
picked recall — a measurement-supported promotion, not a blind
round-up.

`A81_DIMENSIONS_HEADROOM` default is now 1.0 in `config.env`;
operators can set it higher for explicit safety margin, and the
behavior is principled rather than lossy.

## v13.1.1 — Amendments (original review)

Refinements to `PlanC.docx` captured during review. Substantive; not
just editorial. Apply these on the next edit of the docx.

## §4.4 — replace entirely

The sweep measures capacity regimes 1 and 2 directly: atomic recovery
(is a bound vector distinguishable from random vectors in this space)
and superposition capacity (can N atoms still resolve under cosine
query). Regime 3 — retrieval-at-scale, where false-positive density in
the full corpus drowns true-positive signal — is **not measured** by
this design. A 10K-sample in-memory index cannot observe the false-
positive density of a 21M index.

The 1.2× multiplier is therefore an operator-judgment policy choice
covering corpus-size-dependent risk. It is not derived from
measurement. Naming this honestly is the point: the plan otherwise
criticizes hand-waving, so the one place where we hand-wave gets a
disclosure. Operators who want a measurement-backed multiplier should
scale-test their profile against a downstream recall benchmark before
locking a corpus in at its recommendation.

## §4.2 / §4.3 — extended grid

The default grid is `{1024, 2048, 4096, 8192, 16384, 32768}`. The
extended grid `{1024, 2048, 4096, 6144, 8192, 12288, 16384, 32768}`
adds two intermediate points that change the rounding behavior
materially — an elbow of 4097 rounds to 6144 under the extended grid
(1.5×) instead of 8192 under power-of-2 (2.0×).

The extended grid is gated behind `A81_DIMENSIONS_GRID_EXTENDED=false`
default, pending C++ engineer confirmation that EHC's BSC kernel does
not assume strict power-of-2 D. See `PlanC_cpp_engineer_memo.md`.

## §4.3 — elbow threshold

The 1 pp absolute threshold is scale-dependent and noisy at the
high-recall end. v13.1.1 uses **2% of the remaining-accuracy-budget**:
threshold = `0.02 * (1.0 - current_recall)`.

- Tier 1 baseline 0.99 → threshold 0.0002 (essentially "any gain")
- Tier 2 baseline 0.64 → threshold 0.0072 (meaningful signal)

Both principled; neither scale-dependent.

## §4.3 — add latency to the sweep

Profile JSON `calibration_sweep` records per-(D, k): `recall_by_tier`,
`p50_latency_ms`, `p95_latency_ms`, `encode_time_s`. The elbow
detector returns both a recall-elbow and a Pareto front of
(recall, latency) so operators can choose their own operating point.
Recall-elbow remains the default recommendation.

## §5.2 — example output

The example showing a mixed corpus landing at `dim: 16384` after
"elbow 8192 × 1.2 rounded to 16384" is honest given power-of-2
rounding, but underscores why the Executive Summary's "D~=8192 for
mixed corpora" claim overstates the savings. Update the example to
show the same computation **with extended-grid enabled** (8192 × 1.2 =
9830, rounds to 12288 — a 1.33× memory saving vs 16384). Keep both
examples in the doc so the grid choice is visible to readers.

## §6.2 — partial CLI override

Add a row to the behavior matrix:

| State | Action | Override |
|---|---|---|
| `--dim` set, `--k` unset | Use CLI `dim`; take `k` from profile if present, else cfg default. | Stamps `override=cli` on the manifest. |
| `--k` set, `--dim` unset | Use CLI `k`; take `dim` from profile if present, else cfg default. | Stamps `override=cli` on the manifest. |

## §8.3 — explicit out-of-scope additions

- **v13.0 → v13.1 migration.** Adding `dimensions` to the composite
  hash changes hash output for every existing shard. v13.1 handles
  this via the `"v13.0-default"` grandfather sentinel: shards loaded
  without a `dimensions` field get the sentinel, which is recognized
  at query time as D=16384/k=128 (the v13.0 defaults). Re-encode is
  customer-triggered on re-profile, never forced by the v13.1 deploy.

- **Per-tier policy field.** Schema reserves `policy: "per_tier"` but
  the v13.1 code raises `NotImplementedError` when it sees that value.
  The field is ground-work for v13.2; do not implement against it.

## §9 — calibration query source

Ordered preference:

1. **Operator-supplied held-out** (production default). `--calibration-queries path/to/queries.jsonl`. Best representation of real workload.
2. **Corpus-derived from query logs** if available. `--queries-from-logs path/to/logs.jsonl`. Good when logs exist.
3. **Synthetic mask-one-field** (dev/testing). `--synthetic-queries`.
   Emits a loud warning that the resulting recall@10 is a **ceiling
   measurement** — it tests self-recovery, not generalization, and
   will typically overestimate real-query retrieval.

Production profiles that were generated with synthetic queries are
flagged in the profile JSON (`calibration.query_source: "synthetic"`)
so audit can see it without re-running.

## §10 Q1 — sample size

Commit to: `sample_size = min(50_000, max(10_000, int(corpus_size * 0.005)))`.

- Corpus 1M → 10K sample (1.0%)
- Corpus 2M → 10K sample (0.5%)
- Corpus 10M → 50K sample (0.5%, cap hit)
- Corpus 21M → 50K sample (0.24%, cap)

0.05% at 21M (old fixed 10K) was too thin for long-tail structural
patterns. 0.25% with a 50K cap absorbs that without blowing up
Stage-2 runtime.

## §10 Q3 — shard profile inheritance

Later-appended shards **inherit** the existing profile in their
run_dir. Breaking the inheritance requires explicit
`--new-profile` on the profile command, which also requires a new
target `run_dir` so no shard ever mixes profiles within the same
geometry.

## §10 Q4 — cross-D query in v13.2

Noted, deferred. Will revisit with measurement once v13.1 has
production data on how often operators hit dim-mismatch aborts and
whether a zero-pad path would close the gap.
