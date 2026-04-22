"""decode13/profile — v13.1 corpus profiler (PlanC).

Two-stage pre-encode calibration that recommends (D, k) per corpus:

  Stage 1 (`StructuralScanner`): single disk-bandwidth pass classifying
    each record via TierRouter, accumulating per-tier histograms of
    n_atoms / n_slots / char_len.

  Stage 2 (`CalibrationSweep`): stratified sample encoded across a
    (D, k) grid, held-out query set scored with recall@10 and latency
    percentiles per candidate.

  `ElbowDetector`: normalized-threshold elbow, 1.2x headroom, grid
    rounding. Returns a recall-elbow and a Pareto front of
    (recall, latency) operating points.

  `CorpusProfile`: JSON artifact written to the target run directory.
    Schema is `profile-v1`. The encode path reads it, applies (D, k),
    and stamps the `dimensions` axis into the TierManifest.

The honest limitation (PlanC §4.4 rewrite): Stage 2 measures atomic
recovery and superposition capacity directly but cannot observe
retrieval-at-scale false-positive density on a 10K-50K sample. The
headroom multiplier is the operator-judgment knob covering that gap.
"""

from __future__ import annotations

from .schema import (
    CorpusProfile,
    CalibrationRow,
    ProfileValidationError,
    compute_source_hash,
    load_profile,
    save_profile,
    resolve_sample_size,
    PROFILE_VERSION,
)

__all__ = [
    "CorpusProfile",
    "CalibrationRow",
    "ProfileValidationError",
    "compute_source_hash",
    "load_profile",
    "save_profile",
    "resolve_sample_size",
    "PROFILE_VERSION",
]
