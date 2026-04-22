# v13.1 Corpus Profiler — C++ Engineer Memo

For: EHC C++ owner
From: G.A8.1 / v13.1 implementation
Status: blocking the extended-grid default. v13.1 ships either way;
without clearance, the extended grid stays gated.

## Context

v13.1 introduces a pre-encode profiler that recommends `(D, k)` per
corpus instead of the hardcoded D=16384/k=128. The recommendation
comes from measuring recall@10 across a grid of candidate dimensions
and picking the elbow.

The default grid is strict power-of-2: `{1024, 2048, 4096, 8192, 16384, 32768}`.
Under this grid plus the 20% headroom, most corpora round back up to
the v13.0 default (elbow 8192 × 1.2 → 9830 → rounds to 16384). The
stated memory wins don't materialize.

The proposed fix is an **extended grid**:

```
{1024, 2048, 4096, 6144, 8192, 12288, 16384, 32768}
```

6144 and 12288 are both multiples of 256 and 512. An elbow of 4097
rounds to 6144 (1.5×) instead of 8192 (2.0×) — real memory savings.

This memo asks whether EHC's BSC kernels can handle non-power-of-2 D.
If yes, we flip `A81_DIMENSIONS_GRID_EXTENDED=true` default. If no,
we either stay on power-of-2 or you scope the kernel work to make it
yes.

## Questions

### 1. Codebook arithmetic

Does `BSCCodebook` or its generator assume `D` is a power of 2
anywhere — modular indexing, bitmask wrap, hash mix? A quick grep for
`D - 1` used as a mask would answer it.

### 2. LSH hash routing

Does `BSCLSHIndex` hash mixing assume power-of-2 D for bucket
assignment, or is the bucket count a function of `LSH_TABLES ×
LSH_HASH_SIZE` independently?

### 3. SIMD pack alignment

What is the SIMD pack width the cosine/similarity kernels use — 256
bits (AVX2), 512 bits (AVX-512), or NEON-128? As long as D is a
multiple of the pack width's element count, non-power-of-2 is fine.

- D=6144: divisible by 32, 64, 128, 256, 512, 1024, 2048.
- D=12288: divisible by 32, 64, 128, 256, 512, 1024, 2048, 4096.

Both are SIMD-safe for any reasonable pack width. The remaining
concern is whether the C++ side hardcodes a power-of-2 shift anywhere
as a fast-division substitute.

### 4. Manifest `dimensions` axis — any C++ side?

v13.1 adds a `dimensions` field to `TierManifest.ComponentVersions`
on the Python side. The value is symbolic (`"D16384:k128"` or
`"v13.0-default"` for legacy shards). Does anything on the C++ side
read the manifest directly, or is manifest I/O entirely Python?

Last I checked, per the `tier_manifest.py` docstring, the C++
CSR-backed indices "own the actual vectors" and manifest is Python-
only metadata. Confirming.

### 5. Grandfather sentinel

Legacy v13.0 shards have no `dimensions` field. v13.1 loads them with
`dimensions = "v13.0-default"`, which the query-time code maps to
D=16384/k=128 for the BSC cosine kernel. No C++ change needed as long
as the sentinel stays Python-only and query paths convert to
numerical (D, k) before calling into EHC. Confirming.

## Deliverables requested

1. Yes/no on questions 1–3.
2. If "no" to any of 1–3: estimate the work to lift the assumption.
3. Yes/no on question 4.
4. Yes/no on question 5.

If yes to 1–3 and 4–5 are Python-only, flipping the default is a
one-line change in `config.env` after this memo clears. Ship v13.1
with real memory wins.

## What's already implemented on the Python side

Shipped behind `A81_DIMENSIONS_GRID_EXTENDED=false` default:

- Profile command (`python -m encode.profile ...`)
- Stage-1 structural scanner
- Stage-2 calibration sweep (currently runs the power-of-2 grid)
- Elbow detection with 2% remaining-accuracy-budget threshold
- Manifest `dimensions` axis with grandfather sentinel
- Encode-time profile loading with abort on source-hash mismatch
- Query-time dimensions verification
- Unit tests for schema, elbow, manifest compat

Flipping the env var activates the extended grid in elbow rounding
and in the calibration sweep. The code is ready; we're waiting on
you.
