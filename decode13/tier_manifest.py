"""TierManifest + ComponentVersions + ManifestRegistry13.

Extends G.A8.1's SymmetryManifest (canonical/manifest.py) with:

  - tier: which of the three tiers encoded this vector
  - component_versions: per-axis version hashes (escape / possessive /
    acronym / extractor / ner). Stored individually so decode-side
    queries that don't use a particular axis can match against vectors
    encoded under a different version of that axis.
  - composite_hash: a structured hash (PlanB §4.4). Partial compatibility
    matching is the whole reason this exists — most normalization
    updates should NOT require corpus-wide re-encode.
  - tenant_domain: scope identifier for multi-tenant isolation (§9).

Per-vector storage layout:
  The registry stores one TierManifest *per unique (tier, extractor,
  ner, confidence bucket, gate) combination* — typically a handful per
  corpus. Each encoded vector gets a 2-byte int16 index into that
  interned list. For a 21M Tier-1 corpus with one manifest shape, the
  per-vector footprint is 2 bytes + one-time ~1KB manifest, instead of
  21M Python dataclass instances at ~500 bytes apiece.

The C++ CSR-backed BSCCompactIndex / BSCLSHIndex own the actual vectors.
Everything here is *metadata* — kept as numpy arrays so the hot path
hits flat memory, not Python dicts.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from canonical.manifest import SymmetryManifest  # noqa: E402

from .escape_decode import VERSION as ESCAPE_VERSION
from .extractors import VERSION as EXTRACTOR_VERSION, NER_VERSION
from .extraction_pipeline import VERSION as EXTRACTION_PIPELINE_VERSION
from .structured_pipeline import VERSION as STRUCTURED_VERSION
from .emergent_pipeline import VERSION as EMERGENT_VERSION
from .tier_types import Tier


TIER_PIPELINE_VERSION = "tier-routed-v13"

# Tier → int8 encoding for numpy storage (keeps tier_id arrays compact).
_TIER_TO_INT = {
    Tier.STRUCTURED_ATOMIC: 1,
    Tier.EXTRACTED_TRIPLE: 2,
    Tier.EMERGENT_STRUCTURE: 3,
}
_INT_TO_TIER = {v: k for k, v in _TIER_TO_INT.items()}


def tier_to_int(t: Tier) -> int:
    return _TIER_TO_INT[t]


def int_to_tier(i: int) -> Tier:
    return _INT_TO_TIER[int(i)]


@dataclass
class ComponentVersions:
    escape: str = ESCAPE_VERSION
    possessive: str = ""
    acronym: str = ""
    stopword: str = ""
    extractor: str = ""
    ner: str = ""
    structured: str = STRUCTURED_VERSION
    extraction_pipeline: str = ""
    emergent: str = ""
    # v13.1 / PlanC — dimensions axis. Symbolic, not semantic.
    #   v13.0 shards loaded without this field land on the sentinel
    #   "v13.0-default" which query-time maps to D=16384 / k=128 for
    #   the BSC cosine kernel. Profile-backed shards carry "D{n}:k{m}".
    #   Hard axis in is_compatible_with — no partial match.
    dimensions: str = "v13.0-default"

    def axes(self) -> List[str]:
        return list(self.__dataclass_fields__.keys())

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "ComponentVersions":
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})


def _compose(cv: ComponentVersions, tier: Tier, tenant_domain: str) -> str:
    payload = {
        "tier": tier.value,
        "tenant_domain": tenant_domain,
        "components": cv.to_dict(),
    }
    s = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(s).hexdigest()[:16]


@dataclass
class TierManifest:
    tier: Tier = Tier.EMERGENT_STRUCTURE
    components: ComponentVersions = field(default_factory=ComponentVersions)
    extractor: str = "none"
    ner_model: str = "none"
    extraction_confidence: float = 0.0
    gate_agreement: bool = False
    tenant_domain: str = "default::default"
    pipeline_version: str = TIER_PIPELINE_VERSION
    composite_hash: str = ""

    def __post_init__(self):
        if not self.composite_hash:
            self.composite_hash = _compose(
                self.components, self.tier, self.tenant_domain)

    # ── serialization ───────────────────────────────────────
    def to_dict(self) -> Dict:
        d = asdict(self)
        d["tier"] = self.tier.value
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "TierManifest":
        cp = d.get("components", {}) or {}
        cv = ComponentVersions.from_dict(cp) if isinstance(cp, dict) else ComponentVersions()
        # Grandfather: if the stored components dict lacks `dimensions`,
        # this is a pre-v13.1 shard. Force composite_hash recompute so it
        # matches what a fresh v13.1 decode pipeline with
        # dimensions="v13.0-default" produces. Option A from
        # PlanC_v13_1_implementation.md §3.
        is_legacy = isinstance(cp, dict) and "dimensions" not in cp
        stored_hash = "" if is_legacy else d.get("composite_hash", "")
        return cls(
            tier=Tier(d.get("tier", Tier.EMERGENT_STRUCTURE.value)),
            components=cv,
            extractor=d.get("extractor", "none"),
            ner_model=d.get("ner_model", "none"),
            extraction_confidence=float(d.get("extraction_confidence", 0.0)),
            gate_agreement=bool(d.get("gate_agreement", False)),
            tenant_domain=d.get("tenant_domain", "default::default"),
            pipeline_version=d.get("pipeline_version", TIER_PIPELINE_VERSION),
            composite_hash=stored_hash,
        )

    def dimensions_dk(self) -> tuple[int, int]:
        """Parse `components.dimensions` into (D, k) integers.

        Handles:
          - "v13.0-default"  → (16384, 128) hardcoded legacy geometry.
          - "D{n}:k{m}"      → parsed values, validated positive.
        Raises ValueError on malformed values."""
        dim_str = self.components.dimensions
        if dim_str == "v13.0-default":
            return (16384, 128)
        if dim_str.startswith("D") and ":k" in dim_str:
            try:
                d_part, k_part = dim_str.split(":k", 1)
                d = int(d_part[1:])
                k = int(k_part)
                if d > 0 and k > 0:
                    return (d, k)
            except Exception:
                pass
        raise ValueError(
            f"malformed dimensions axis: {dim_str!r} — "
            f"expected 'v13.0-default' or 'D{{n}}:k{{m}}'")

    # ── compatibility ───────────────────────────────────────
    def is_compatible_with(
        self,
        other: "TierManifest",
        axes_used: Optional[Set[str]] = None,
    ) -> bool:
        """Partial-compatibility matching (§4.4)."""
        if self.tenant_domain != other.tenant_domain:
            return False
        if self.pipeline_version != other.pipeline_version:
            return False
        if axes_used is None:
            return self.composite_hash == other.composite_hash
        a = self.components
        b = other.components
        for axis in axes_used:
            va = getattr(a, axis, None)
            vb = getattr(b, axis, None)
            if va is None or vb is None:
                return False
            if va != vb:
                return False
        return True

    # ── factory from G.A8.1 SymmetryManifest ────────────────
    @classmethod
    def from_symmetry(
        cls,
        symmetry: SymmetryManifest,
        tier: Tier,
        extractor: str = "none",
        ner_model: str = "none",
        extraction_confidence: float = 1.0,
        gate_agreement: bool = False,
        tenant_domain: str = "default::default",
        dimensions: Optional[str] = None,
    ) -> "TierManifest":
        # dimensions: caller passes the profile-derived axis string
        # (e.g. "D16384:k128"). If None, we read A81_DIMENSIONS_AXIS
        # from the environment — set by encode.py main() after profile
        # loading — then fall back to the legacy sentinel.
        if dimensions is None:
            import os as _os
            dimensions = _os.environ.get("A81_DIMENSIONS_AXIS", "v13.0-default")
        cv = ComponentVersions(
            possessive=symmetry.possessive_version,
            acronym=symmetry.acronym_hash,
            stopword=symmetry.stopword_hash,
            dimensions=dimensions,
        )
        if tier == Tier.EXTRACTED_TRIPLE:
            cv.extractor = EXTRACTOR_VERSION
            cv.ner = NER_VERSION
            cv.extraction_pipeline = EXTRACTION_PIPELINE_VERSION
        elif tier == Tier.EMERGENT_STRUCTURE:
            cv.emergent = EMERGENT_VERSION
        return cls(
            tier=tier,
            components=cv,
            extractor=extractor,
            ner_model=ner_model,
            extraction_confidence=extraction_confidence,
            gate_agreement=gate_agreement,
            tenant_domain=tenant_domain,
        )


class ManifestRegistry13:
    """Per-vector manifest registry backed by flat numpy arrays.

    Layout:
      _manifests       : List[TierManifest]        interned (small, ~1-10)
      _intern_key_to_id: Dict[tuple, int]          (tier, extractor, ner,
                                                    conf_bucket, gate) → mid
      _manifest_id     : np.int16[N]               per-vector index into
                                                    _manifests
      _n               : int                        # registered vectors
      _capacity        : int                        grown amortized ×2

    The registry exposes precompute_compat(axes_used) which returns a
    small boolean vector (one per interned manifest), so a retrieval
    hot path can do O(1) per-candidate compatibility checks by indexing
    into this vector with the manifest_id.
    """

    GROW_MULT = 2
    INIT_CAP = 4096

    def __init__(self, decode_manifest: TierManifest):
        self.decode_manifest = decode_manifest
        self._manifests: List[TierManifest] = []
        self._intern_key_to_id: Dict[tuple, int] = {}
        self._manifest_id: np.ndarray = np.zeros(0, dtype=np.int16)
        self._n = 0
        self._capacity = 0

    # ── write path ──────────────────────────────────────────
    def _intern(self, manifest: TierManifest) -> int:
        key = (
            manifest.tier,
            manifest.extractor,
            manifest.ner_model,
            round(float(manifest.extraction_confidence), 2),
            bool(manifest.gate_agreement),
            manifest.composite_hash,
            manifest.tenant_domain,
        )
        mid = self._intern_key_to_id.get(key)
        if mid is not None:
            return mid
        mid = len(self._manifests)
        if mid >= 32767:
            raise RuntimeError(
                f"Manifest intern table exceeded int16 range ({mid}); "
                f"increase dtype width.")
        self._manifests.append(manifest)
        self._intern_key_to_id[key] = mid
        return mid

    def _ensure_capacity(self, required: int) -> None:
        if required <= self._capacity:
            return
        new_cap = max(self._capacity * self.GROW_MULT, self.INIT_CAP, required)
        new_arr = np.zeros(new_cap, dtype=np.int16)
        if self._n > 0:
            new_arr[:self._n] = self._manifest_id[:self._n]
        self._manifest_id = new_arr
        self._capacity = new_cap

    def register(self, vec_id: int, manifest: TierManifest) -> None:
        mid = self._intern(manifest)
        self._ensure_capacity(vec_id + 1)
        self._manifest_id[vec_id] = mid
        if vec_id + 1 > self._n:
            self._n = vec_id + 1

    def finalize(self) -> None:
        """Trim to actual size. Call after encode when no more registers
        are coming — releases growth slack."""
        if self._capacity > self._n:
            self._manifest_id = self._manifest_id[:self._n].copy()
            self._capacity = self._n

    # ── read path ──────────────────────────────────────────
    def manifest_for(self, vec_id: int) -> Optional[TierManifest]:
        if vec_id < 0 or vec_id >= self._n:
            return None
        return self._manifests[int(self._manifest_id[vec_id])]

    def tier_of(self, vec_id: int) -> Optional[Tier]:
        m = self.manifest_for(vec_id)
        return m.tier if m else None

    def is_compatible(
        self,
        vec_id: int,
        axes_used: Optional[Set[str]] = None,
    ) -> bool:
        m = self.manifest_for(vec_id)
        if m is None:
            return False
        return self.decode_manifest.is_compatible_with(m, axes_used=axes_used)

    def compatible_ids(
        self,
        candidate_ids: List[int],
        axes_used: Optional[Set[str]] = None,
    ) -> List[int]:
        compat = self.precompute_compat(axes_used)
        out: List[int] = []
        for vid in candidate_ids:
            if vid < 0 or vid >= self._n:
                continue
            mid = int(self._manifest_id[vid])
            if compat[mid]:
                out.append(vid)
        return out

    def precompute_compat(
        self,
        axes_used: Optional[Set[str]] = None,
    ) -> np.ndarray:
        """Boolean vector, one entry per interned manifest.

        The retrieval hot path calls this once per subquery and then does
        `compat_per_manifest[manifest_id[vid]]` for each candidate —
        flat-memory O(1) lookup, no dict probes.
        """
        if not self._manifests:
            return np.zeros(0, dtype=bool)
        out = np.zeros(len(self._manifests), dtype=bool)
        for i, m in enumerate(self._manifests):
            out[i] = self.decode_manifest.is_compatible_with(
                m, axes_used=axes_used)
        return out

    def manifest_ids_for(self, vec_ids: np.ndarray) -> np.ndarray:
        """Return the interned manifest-id for each vec_id (vectorized)."""
        return self._manifest_id[vec_ids]

    def summary(self) -> Dict:
        tier_counts = {t.value: 0 for t in Tier}
        if self._n > 0:
            # For each interned manifest, count how many vectors reference it.
            ids = self._manifest_id[:self._n]
            for mid, m in enumerate(self._manifests):
                tier_counts[m.tier.value] += int((ids == mid).sum())
        compat_full = int(self.precompute_compat(None)[self._manifest_id[:self._n]].sum()) \
                      if self._n > 0 else 0
        return {
            "total_vectors": int(self._n),
            "interned_manifests": len(self._manifests),
            "tier_counts": tier_counts,
            "fully_compatible": compat_full,
            "decode_tier": self.decode_manifest.tier.value,
            "decode_composite": self.decode_manifest.composite_hash,
        }

    # ── access for flat bulk ops ────────────────────────────
    @property
    def n(self) -> int:
        return self._n

    @property
    def manifest_id_array(self) -> np.ndarray:
        """Read-only view of the per-vector manifest-id array. Length = n."""
        return self._manifest_id[:self._n]

    @property
    def interned(self) -> List[TierManifest]:
        return self._manifests

    # ── persistence ─────────────────────────────────────────
    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "decode_manifest": self.decode_manifest.to_dict(),
            "manifests": [m.to_dict() for m in self._manifests],
            "n": self._n,
        }
        with open(path, "w") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        # The flat array is saved as a sidecar .npy next to the json.
        np.save(str(path.with_suffix(".npy")), self._manifest_id[:self._n])

    @classmethod
    def load(cls, path: Path) -> "ManifestRegistry13":
        path = Path(path)
        with open(path) as f:
            payload = json.load(f)
        decode = TierManifest.from_dict(payload["decode_manifest"])
        reg = cls(decode)
        reg._manifests = [TierManifest.from_dict(m)
                          for m in payload.get("manifests", [])]
        reg._intern_key_to_id = {
            (m.tier, m.extractor, m.ner_model,
             round(float(m.extraction_confidence), 2),
             bool(m.gate_agreement), m.composite_hash, m.tenant_domain): i
            for i, m in enumerate(reg._manifests)
        }
        n = int(payload.get("n", 0))
        npy_path = path.with_suffix(".npy")
        if n > 0 and npy_path.exists():
            reg._manifest_id = np.load(str(npy_path))
            reg._n = len(reg._manifest_id)
            reg._capacity = reg._n
        return reg
