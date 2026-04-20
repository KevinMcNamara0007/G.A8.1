"""TierManifest + ManifestRegistry13 compatibility tests."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from canonical.pipeline import CanonicalizationPipeline
from decode13.tier_manifest import (
    ManifestRegistry13, TierManifest, ComponentVersions,
)
from decode13.tier_types import Tier


def test_composite_hash_is_deterministic():
    canonical = CanonicalizationPipeline()
    a = TierManifest.from_symmetry(canonical.manifest, Tier.STRUCTURED_ATOMIC)
    b = TierManifest.from_symmetry(canonical.manifest, Tier.STRUCTURED_ATOMIC)
    assert a.composite_hash == b.composite_hash
    # Different tier → different hash
    c = TierManifest.from_symmetry(canonical.manifest, Tier.EXTRACTED_TRIPLE)
    assert a.composite_hash != c.composite_hash


def test_partial_compatibility_matching():
    canonical = CanonicalizationPipeline()
    # Encode-time manifest: Tier 1 structured_atomic
    enc = TierManifest.from_symmetry(canonical.manifest, Tier.STRUCTURED_ATOMIC)
    # Decode-time manifest: same tier, but suppose the acronym table
    # changed after encode. We simulate that by cloning enc and bumping
    # the acronym hash.
    dec_components = ComponentVersions(
        escape=enc.components.escape,
        possessive=enc.components.possessive,
        acronym="DIFFERENT_ACRONYM_HASH",
        stopword=enc.components.stopword,
        structured=enc.components.structured,
    )
    dec = TierManifest(
        tier=Tier.STRUCTURED_ATOMIC,
        components=dec_components,
        tenant_domain=enc.tenant_domain,
    )
    # Strict match fails
    assert dec.is_compatible_with(enc, axes_used=None) is False
    # But if the query doesn't use the acronym axis (escape only),
    # they should be compatible.
    assert dec.is_compatible_with(enc, axes_used={"escape", "structured"}) is True
    # And if the query DOES use acronym, compat is lost.
    assert dec.is_compatible_with(
        enc, axes_used={"escape", "acronym"}) is False


def test_tenant_isolation():
    canonical = CanonicalizationPipeline()
    a = TierManifest.from_symmetry(
        canonical.manifest, Tier.STRUCTURED_ATOMIC,
        tenant_domain="acme::logs")
    b = TierManifest.from_symmetry(
        canonical.manifest, Tier.STRUCTURED_ATOMIC,
        tenant_domain="other::logs")
    # Different tenants → never compatible, even on all axes
    assert a.is_compatible_with(b, axes_used=None) is False
    assert a.is_compatible_with(b, axes_used={"escape"}) is False


def test_registry_save_load_roundtrip():
    canonical = CanonicalizationPipeline()
    decode_m = TierManifest.from_symmetry(
        canonical.manifest, Tier.STRUCTURED_ATOMIC)
    reg = ManifestRegistry13(decode_m)
    m_t1 = TierManifest.from_symmetry(
        canonical.manifest, Tier.STRUCTURED_ATOMIC,
        extraction_confidence=1.0, gate_agreement=True)
    m_t2 = TierManifest.from_symmetry(
        canonical.manifest, Tier.EXTRACTED_TRIPLE,
        extractor="rule_based_fact_separator", ner_model="heuristic-ner-v1",
        extraction_confidence=0.9, gate_agreement=True)
    reg.register(0, m_t1)
    reg.register(1, m_t2)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tier_manifest.json"
        reg.save(path)
        reloaded = ManifestRegistry13.load(path)

    s = reloaded.summary()
    assert s["total_vectors"] == 2
    assert s["tier_counts"]["structured_atomic"] == 1
    assert s["tier_counts"]["extracted_triple"] == 1


def test_registry_compatible_ids_filters_tier_mismatch():
    canonical = CanonicalizationPipeline()
    decode_m = TierManifest.from_symmetry(
        canonical.manifest, Tier.STRUCTURED_ATOMIC)
    reg = ManifestRegistry13(decode_m)
    # vec 0: same tier, same hash → compatible
    reg.register(0, TierManifest.from_symmetry(
        canonical.manifest, Tier.STRUCTURED_ATOMIC))
    # vec 1: different tier — not compatible under strict check
    reg.register(1, TierManifest.from_symmetry(
        canonical.manifest, Tier.EXTRACTED_TRIPLE))

    full_compat = reg.compatible_ids([0, 1], axes_used=None)
    assert full_compat == [0]
    # With axes_used that EXCLUDE the tier-discriminating fields, the
    # two vectors can look compatible — that's partial-compat in action.
    # But tier itself is folded into the composite via the tier string,
    # so tier-discrimination persists unless we use axes_used.
    loose = reg.compatible_ids([0, 1], axes_used={"escape"})
    # axes_used={"escape"} means we only check the escape axis; both
    # vectors share it, so both are compatible.
    assert 0 in loose and 1 in loose


if __name__ == "__main__":
    import traceback
    passed = failed = 0
    for name in [n for n in dir() if n.startswith("test_")]:
        try:
            globals()[name]()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {name}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\ntest_tier_manifest: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
