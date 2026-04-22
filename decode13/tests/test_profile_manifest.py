"""v13.1 TierManifest dimensions-axis + grandfather tests."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from canonical.pipeline import CanonicalizationPipeline  # noqa: E402
from decode13.tier_manifest import (  # noqa: E402
    ComponentVersions, TierManifest,
)
from decode13.tier_types import Tier  # noqa: E402


def test_default_dimensions_is_legacy_sentinel():
    cv = ComponentVersions()
    assert cv.dimensions == "v13.0-default"


def test_from_symmetry_accepts_dimensions():
    cp = CanonicalizationPipeline()
    tm = TierManifest.from_symmetry(
        cp.manifest, Tier.STRUCTURED_ATOMIC, dimensions="D16384:k128")
    assert tm.components.dimensions == "D16384:k128"


def test_from_symmetry_reads_env_var(monkeypatch=None):
    # Manual env-var test (no pytest fixtures).
    import os
    old = os.environ.get("A81_DIMENSIONS_AXIS")
    os.environ["A81_DIMENSIONS_AXIS"] = "D4096:k64"
    try:
        cp = CanonicalizationPipeline()
        tm = TierManifest.from_symmetry(cp.manifest, Tier.STRUCTURED_ATOMIC)
        assert tm.components.dimensions == "D4096:k64"
    finally:
        if old is None:
            del os.environ["A81_DIMENSIONS_AXIS"]
        else:
            os.environ["A81_DIMENSIONS_AXIS"] = old


def test_dimensions_dk_parses_v13_1():
    cp = CanonicalizationPipeline()
    tm = TierManifest.from_symmetry(
        cp.manifest, Tier.STRUCTURED_ATOMIC, dimensions="D8192:k90")
    assert tm.dimensions_dk() == (8192, 90)


def test_dimensions_dk_legacy_sentinel():
    cp = CanonicalizationPipeline()
    tm = TierManifest.from_symmetry(
        cp.manifest, Tier.STRUCTURED_ATOMIC, dimensions="v13.0-default")
    assert tm.dimensions_dk() == (16384, 128)


def test_dimensions_dk_malformed_raises():
    cp = CanonicalizationPipeline()
    tm = TierManifest.from_symmetry(
        cp.manifest, Tier.STRUCTURED_ATOMIC, dimensions="bogus")
    try:
        tm.dimensions_dk()
    except ValueError:
        return
    assert False, "malformed dimensions should raise"


def test_legacy_dict_roundtrip_grandfather():
    """A dict missing `dimensions` in components (pre-v13.1) should:
      1. Load with the sentinel default.
      2. Have its composite_hash recomputed so it matches a freshly
         constructed v13.1 manifest with the sentinel default."""
    cp = CanonicalizationPipeline()
    fresh = TierManifest.from_symmetry(
        cp.manifest, Tier.STRUCTURED_ATOMIC, dimensions="v13.0-default")
    # Simulate a legacy on-disk shape: components dict lacks `dimensions`.
    d = fresh.to_dict()
    d["components"].pop("dimensions", None)
    # And legacy composite_hash would have been computed without the
    # dimensions field — we simulate that by setting a bogus value.
    d["composite_hash"] = "LEGACY_HASH_NO_DIMS"
    loaded = TierManifest.from_dict(d)
    assert loaded.components.dimensions == "v13.0-default"
    # Grandfather path: from_dict forced a recompute, so loaded's hash
    # should equal a freshly-computed hash, NOT the legacy bogus one.
    assert loaded.composite_hash == fresh.composite_hash
    assert loaded.composite_hash != "LEGACY_HASH_NO_DIMS"


def test_v13_1_dict_roundtrip_preserves_hash():
    """A dict that DOES include `dimensions` preserves the stored hash."""
    cp = CanonicalizationPipeline()
    tm = TierManifest.from_symmetry(
        cp.manifest, Tier.STRUCTURED_ATOMIC, dimensions="D4096:k64")
    d = tm.to_dict()
    original_hash = d["composite_hash"]
    assert "dimensions" in d["components"]
    loaded = TierManifest.from_dict(d)
    assert loaded.composite_hash == original_hash


def test_different_dimensions_produce_different_hashes():
    cp = CanonicalizationPipeline()
    a = TierManifest.from_symmetry(
        cp.manifest, Tier.STRUCTURED_ATOMIC, dimensions="D16384:k128")
    b = TierManifest.from_symmetry(
        cp.manifest, Tier.STRUCTURED_ATOMIC, dimensions="D4096:k64")
    assert a.composite_hash != b.composite_hash, (
        "dimensions axis must differentiate composite hashes")


if __name__ == "__main__":
    tests = [
        test_default_dimensions_is_legacy_sentinel,
        test_from_symmetry_accepts_dimensions,
        test_from_symmetry_reads_env_var,
        test_dimensions_dk_parses_v13_1,
        test_dimensions_dk_legacy_sentinel,
        test_dimensions_dk_malformed_raises,
        test_legacy_dict_roundtrip_grandfather,
        test_v13_1_dict_roundtrip_preserves_hash,
        test_different_dimensions_produce_different_hashes,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
    print(f"\ntest_profile_manifest: {'FAIL' if failed else 'PASS'} "
          f"({len(tests) - failed}/{len(tests)})")
    sys.exit(1 if failed else 0)
