"""
G.A8.1 — SymmetryManifest and ManifestVersionRegistry

The manifest is the machine-readable form of the symmetry contract. Every
shard records exactly which normalization rules produced its encoded
vectors; at decode time the query normalizer reads the manifest and
applies matching rules. Without the manifest, encode and decode paths
drift silently over time.

Stored per-shard (not per-vector — all vectors in a shard share the same
rule-set by construction).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Optional


PIPELINE_VERSION = "closed-loop-1"
SRL_VERSION = "lightweight-v12.5"
POSSESSIVE_VERSION = "v1"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


@dataclass
class SymmetryManifest:
    pipeline_version: str = PIPELINE_VERSION
    stopword_hash: str = ""
    acronym_hash: str = ""
    possessive_version: str = POSSESSIVE_VERSION
    srl_version: str = SRL_VERSION
    extraction_confidence: float = 1.0

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "SymmetryManifest":
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})

    @classmethod
    def from_resources(cls, stopword_path: Path, acronym_path: Path,
                       extraction_confidence: float = 1.0) -> "SymmetryManifest":
        return cls(
            stopword_hash=_sha256_file(stopword_path),
            acronym_hash=_sha256_file(acronym_path),
            extraction_confidence=extraction_confidence,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, sort_keys=True)

    @classmethod
    def load(cls, path: Path) -> Optional["SymmetryManifest"]:
        if not Path(path).exists():
            return None
        with open(path) as f:
            return cls.from_dict(json.load(f))

    def compatible_with(self, other: "SymmetryManifest") -> bool:
        """Two manifests are compatible when the rules that affect token
        emission match. extraction_confidence is metadata only — it does
        not affect geometry."""
        return (
            self.pipeline_version == other.pipeline_version
            and self.stopword_hash == other.stopword_hash
            and self.acronym_hash == other.acronym_hash
            and self.possessive_version == other.possessive_version
            and self.srl_version == other.srl_version
        )

    def drift_reason(self, other: "SymmetryManifest") -> str:
        if self.pipeline_version != other.pipeline_version:
            return f"pipeline: {self.pipeline_version} vs {other.pipeline_version}"
        if self.stopword_hash != other.stopword_hash:
            return "stopword_hash"
        if self.acronym_hash != other.acronym_hash:
            return "acronym_hash"
        if self.possessive_version != other.possessive_version:
            return "possessive_version"
        if self.srl_version != other.srl_version:
            return "srl_version"
        return ""


class ManifestVersionRegistry:
    """Maps shard_id -> encode-time manifest; checks compatibility against
    the live decode-time manifest.

    Query-time compatibility check is O(1) per shard. Drift is logged;
    policy (lazy re-encode vs. hard-fail) is left to the caller because
    the plan's Open Question §7 Q2 is not yet settled.
    """

    def __init__(self, decode_manifest: SymmetryManifest):
        self.decode_manifest = decode_manifest
        self._by_shard: Dict[int, SymmetryManifest] = {}
        self._drift_log: list = []

    def register(self, shard_id: int, manifest: SymmetryManifest) -> None:
        self._by_shard[shard_id] = manifest
        if not self.decode_manifest.compatible_with(manifest):
            reason = self.decode_manifest.drift_reason(manifest)
            self._drift_log.append({"shard_id": shard_id, "reason": reason})

    def is_compatible(self, shard_id: int) -> bool:
        enc = self._by_shard.get(shard_id)
        if enc is None:
            return False
        return self.decode_manifest.compatible_with(enc)

    def encoded_manifest(self, shard_id: int) -> Optional[SymmetryManifest]:
        return self._by_shard.get(shard_id)

    @property
    def drift_log(self) -> list:
        return list(self._drift_log)

    def summary(self) -> dict:
        total = len(self._by_shard)
        compat = sum(1 for sid in self._by_shard if self.is_compatible(sid))
        return {
            "total_shards": total,
            "compatible_shards": compat,
            "drift_events": len(self._drift_log),
            "decode_pipeline_version": self.decode_manifest.pipeline_version,
        }
