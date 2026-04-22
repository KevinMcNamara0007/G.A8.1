"""v13.1 CorpusProfile — JSON schema, source_hash, IO.

Memory discipline: this module never materializes the corpus. `compute_source_hash`
streams N deterministic byte offsets and hashes those bytes only. The profile
dataclass itself is small — histograms and sweep rows are bounded by tier count
and grid size, not by corpus size.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

PROFILE_VERSION = "profile-v1"

# Number of deterministic byte offsets sampled for source_hash. 64 offsets
# × 4KiB each = 256 KiB read per hash. Catches in-place mid-file edits that
# "path + count + first/last record" would miss.
_SOURCE_HASH_PROBES = 64
_SOURCE_HASH_PROBE_BYTES = 4096


class ProfileValidationError(Exception):
    """Raised on schema-version mismatch, source-hash mismatch, or malformed JSON."""


@dataclass
class CalibrationRow:
    """One (D, k) measurement from Stage 2. Numbers only — no vectors."""
    dim: int
    k: int
    recall_by_tier: Dict[str, float] = field(default_factory=dict)
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    encode_time_s: float = 0.0


@dataclass
class CorpusProfile:
    """v13.1 corpus profile.

    Fields are intentionally flat — no nested objects beyond dicts of
    scalars — so JSON serialization is trivial and audit tools can diff
    two profiles line-by-line.
    """
    profile_version: str = PROFILE_VERSION
    source_hash: str = ""
    recommended_dim: int = 16384
    recommended_k: int = 128
    policy: str = "worst_case_mixed"
    structural_scan: Dict[str, Any] = field(default_factory=dict)
    calibration_sweep: List[Dict[str, Any]] = field(default_factory=list)
    elbow_analysis: Dict[str, Any] = field(default_factory=dict)
    generated_at: str = ""
    tooling: Dict[str, Any] = field(default_factory=dict)
    calibration_query_source: str = "synthetic"  # synthetic | operator | logs
    grid_extended: bool = False
    # v13.1.2 — production-readiness fields.
    confidence: str = "unknown"  # "high" | "medium" | "low"
    selection_reason: str = ""
    num_calibration_queries: int = 0
    # v13.1.3 — three-zone selection.
    zone: str = "unknown"  # "confident" | "plateau" | "capacity_pressed" | "ambiguous"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CorpusProfile":
        if d.get("profile_version") != PROFILE_VERSION:
            raise ProfileValidationError(
                f"profile_version mismatch: got {d.get('profile_version')!r}, "
                f"expected {PROFILE_VERSION!r}")
        known = set(cls.__dataclass_fields__.keys())
        return cls(**{k: v for k, v in d.items() if k in known})

    def dimensions_axis(self) -> str:
        """Value for TierManifest.ComponentVersions.dimensions — symbolic,
        not semantic. Two profiles at the same geometry but different
        provenance produce different axis strings, which is correct."""
        return f"D{self.recommended_dim}:k{self.recommended_k}"

    def matches_source(self, source_path: str, record_count: int) -> bool:
        """Recompute source_hash and compare. True if corpus unchanged."""
        return compute_source_hash(source_path, record_count) == self.source_hash


def compute_source_hash(source_path: str, record_count: int) -> str:
    """Sampled-content hash over the source file.

    Streams `_SOURCE_HASH_PROBES` deterministic byte offsets, hashes
    `_SOURCE_HASH_PROBE_BYTES` at each. Combined with record_count and
    total byte size, catches:

      - file replaced (byte size changes, offsets hash differently)
      - records appended (byte size changes)
      - records removed (byte size changes)
      - in-place edits at any of the probe offsets (hash changes)

    Weakness: a targeted edit that avoids every probe offset would
    evade detection. Acceptable — we prioritize O(1) time over
    cryptographic guarantees. A true integrity check is the operator's
    responsibility at ingest boundaries.
    """
    path = Path(source_path)
    size = path.stat().st_size
    h = hashlib.sha256()
    h.update(f"size={size}|count={record_count}|probes={_SOURCE_HASH_PROBES}".encode())
    if size == 0:
        return h.hexdigest()[:32]
    # Deterministic probe offsets, evenly spread. First and last bytes
    # are always probed; remaining probes are evenly spaced in between.
    with open(path, "rb") as f:
        for i in range(_SOURCE_HASH_PROBES):
            offset = int(i * max(1, size - _SOURCE_HASH_PROBE_BYTES) / max(1, _SOURCE_HASH_PROBES - 1))
            offset = min(offset, max(0, size - _SOURCE_HASH_PROBE_BYTES))
            f.seek(offset)
            chunk = f.read(_SOURCE_HASH_PROBE_BYTES)
            h.update(chunk)
    return h.hexdigest()[:32]


def load_profile(path: str | Path) -> CorpusProfile:
    """Read and validate a corpus_profile.json."""
    p = Path(path)
    if not p.exists():
        raise ProfileValidationError(f"profile not found: {p}")
    with open(p) as f:
        d = json.load(f)
    return CorpusProfile.from_dict(d)


def save_profile(profile: CorpusProfile, path: str | Path) -> None:
    """Write corpus_profile.json. Overwrites; caller enforces --force semantics."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(profile.to_dict(), f, indent=2, sort_keys=True)


def resolve_sample_size(corpus_size: int, *, floor: int = 10_000, cap: int = 50_000,
                        fraction: float = 0.005) -> int:
    """PlanC §10 Q1 resolution: `min(cap, max(floor, int(corpus_size * fraction)))`.

    Corpus 1M → 10K (1.0%). Corpus 10M → 50K (0.5%, cap). Corpus 21M → 50K (0.24%).
    """
    if corpus_size <= 0:
        return floor
    return min(cap, max(floor, int(corpus_size * fraction)))
