#!/usr/bin/env python3
"""
G.A8.1 — Closed-Loop Canonicalization Tests
============================================

Covers the contract from Closed_Loop_Encode_Decode_Plan.docx:
  - Encode and decode produce the SAME canonical token stream (§2.1 symmetry)
  - Variant fan-out emits up to 4 forms along possession+acronym axes (§2.3)
  - SymmetryManifest round-trips and detects drift (§2.2)
  - Instrumentation counts Hit@5-but-not-Hit@1 correctly (§4)

Run:  python3 -m pytest tests/test_canonicalization.py -v
 or:  python3 tests/test_canonicalization.py
"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from canonical import (
    CanonicalizationPipeline,
    CanonicalStream,
    SymmetryManifest,
    ManifestVersionRegistry,
    VariantGenerator,
    QueryInstrumentation,
    QueryTrace,
    PIPELINE_VERSION,
)


# ── §2.1 Symmetry: encode-side and decode-side produce the same stream ──

def test_encode_decode_stream_identical_for_triple():
    """Clean triples must canonicalize the same way whether fed as
    (s, r, o) at encode time or as a raw query at decode time when the
    query happens to match the triple's surface form."""
    p = CanonicalizationPipeline()

    encode_stream = p.canonicalize(
        subject="Alan Turing", relation="invented",
        obj="the Turing machine")
    query_stream = p.canonicalize_query("alan turing invented turing machine")

    assert encode_stream.tokens == query_stream.tokens, (
        "encode/decode token streams diverged: "
        f"{encode_stream.tokens} vs {query_stream.tokens}")


def test_stopword_strip_is_deterministic():
    """Stop words are stripped identically on both paths."""
    p = CanonicalizationPipeline()
    stream = p.canonicalize_query("the quick brown fox is over the lazy dog")
    assert "the" not in stream.tokens
    assert "is" not in stream.tokens
    assert stream.tokens == ["quick", "brown", "fox", "over", "lazy", "dog"]


def test_partial_extraction_flags():
    """Plan §2.1 — extraction must tolerate SR / RO / SO / S / O."""
    p = CanonicalizationPipeline()
    stream = p.canonicalize(subject="Turing")
    assert stream.partial == frozenset({"s"})
    assert stream.tokens == ["turing"]

    stream = p.canonicalize(obj="machine learning")
    # "machine" is the expansion of an acronym hit? No — "ml" would be.
    # Plain object path: stop-word strip only.
    assert stream.partial == frozenset({"o"})
    assert "machine" in stream.tokens and "learning" in stream.tokens


# ── §2.3 Variant fan-out ──

def test_variant_count_bounded_by_four():
    """Plan §2.3: combined three-axis starting set caps fan-out at 4."""
    p = CanonicalizationPipeline()
    vg = VariantGenerator(p)

    variants = vg.generate("user's ML wallet")
    assert 1 <= len(variants) <= 4
    assert any(v.is_canonical for v in variants)


def test_possessive_variant_preserves_alternate_surface():
    p = CanonicalizationPipeline()
    vg = VariantGenerator(p)
    variants = vg.generate("user's wallet")
    labels = {v.label for v in variants}
    assert "canonical" in labels
    # Possessive variant should appear because alternates were captured
    assert any("possessive" in v.axes for v in variants)


def test_acronym_variant_emits_both_forms():
    p = CanonicalizationPipeline()
    vg = VariantGenerator(p)
    canonical_vars = vg.generate("ML researcher")

    token_sets = [set(v.tokens) for v in canonical_vars]
    # One variant should contain the expansion ("machine"/"learning")
    assert any("machine" in ts for ts in token_sets)
    # One variant should contain the compact acronym ("ml")
    assert any("ml" in ts for ts in token_sets)


def test_combined_axis_variant_produced():
    p = CanonicalizationPipeline()
    vg = VariantGenerator(p)
    variants = vg.generate("user's ML wallet")
    axes = [tuple(sorted(v.axes)) for v in variants]
    # Expect canonical + possessive-only + acronym-only + combined
    assert () in axes
    assert ("possessive",) in axes
    assert ("acronym",) in axes
    assert ("acronym", "possessive") in axes
    assert len(variants) == 4


def test_single_axis_config_halves_fanout():
    """Operators can disable axes — fan-out shrinks accordingly."""
    p = CanonicalizationPipeline()
    vg = VariantGenerator(p, enabled_axes=frozenset({"acronym"}))
    variants = vg.generate("user's ML wallet")
    # Only canonical + acronym (possessive axis disabled)
    labels = {v.label for v in variants}
    assert labels == {"canonical", "acronym"}


# ── §2.2 Manifest + registry ──

def test_manifest_round_trip(tmp_path):
    p = CanonicalizationPipeline()
    path = tmp_path / "symmetry_manifest.json"
    p.manifest.save(path)

    reloaded = SymmetryManifest.load(path)
    assert reloaded is not None
    assert reloaded.to_dict() == p.manifest.to_dict()
    assert reloaded.compatible_with(p.manifest)


def test_manifest_detects_stopword_drift(tmp_path):
    """Changing the stopword list must flip compatibility to False."""
    # Build a pipeline whose stopword hash differs from default
    alt_stop = tmp_path / "alt_stopwords.txt"
    alt_stop.write_text("the\na\n")  # shorter list = different hash

    resources = ROOT / "canonical" / "resources"
    p_default = CanonicalizationPipeline()
    p_alt = CanonicalizationPipeline(
        stopwords_path=alt_stop,
        acronyms_path=resources / "acronyms_v1.tsv",
        possessives_path=resources / "possessive_v1.tsv",
    )

    assert not p_default.manifest.compatible_with(p_alt.manifest)
    assert p_default.manifest.drift_reason(p_alt.manifest) == "stopword_hash"


def test_registry_tracks_mixed_shard_compatibility(tmp_path):
    p = CanonicalizationPipeline()
    registry = ManifestVersionRegistry(p.manifest)

    # Shard 0 compatible
    registry.register(0, p.manifest)
    # Shard 1 incompatible (simulated drift)
    drifted = SymmetryManifest.from_dict({
        **p.manifest.to_dict(),
        "stopword_hash": "deadbeefdeadbeef",
    })
    registry.register(1, drifted)

    assert registry.is_compatible(0)
    assert not registry.is_compatible(1)
    summary = registry.summary()
    assert summary["total_shards"] == 2
    assert summary["compatible_shards"] == 1
    assert summary["drift_events"] == 1


def test_pipeline_version_is_stamped():
    p = CanonicalizationPipeline()
    assert p.manifest.pipeline_version == PIPELINE_VERSION


# ── §4 Instrumentation: Hit@5-not-Hit@1 rolling counter ──

def test_instrumentation_rolls_hit5_not_hit1():
    inst = QueryInstrumentation(rolling_window=10)

    # 3 hit-at-5-only (the "middle band" §3.1 describes)
    for _ in range(3):
        inst.record(QueryTrace(hit_at_1=False, hit_at_5=True))
    # 5 perfect
    for _ in range(5):
        inst.record(QueryTrace(hit_at_1=True, hit_at_5=True))
    # 2 misses
    for _ in range(2):
        inst.record(QueryTrace(hit_at_1=False, hit_at_5=False))

    summary = inst.summary()
    assert summary["queries"] == 10
    assert summary["hit_at_1"] == 5
    assert summary["hit_at_5"] == 8
    assert summary["hit5_not_hit1"] == 3
    assert summary["rolling_hit5_not_hit1"] == 3


def test_instrumentation_log_writes_jsonl(tmp_path):
    log = tmp_path / "closed_loop.jsonl"
    inst = QueryInstrumentation(log_path=str(log))
    inst.record(QueryTrace(query="foo", hit_at_1=True, hit_at_5=True,
                           winning_variant="canonical"))
    inst.record(QueryTrace(query="bar", hit_at_1=False, hit_at_5=True,
                           winning_variant="possessive"))

    lines = log.read_text().splitlines()
    assert len(lines) == 2
    rec0 = json.loads(lines[0])
    assert rec0["query"] == "foo"
    assert rec0["winning_variant"] == "canonical"


def test_winner_by_variant_tracked():
    """Plan §3.3: rising 'canonical' winner share is the convergence
    signature — the instrumentation must expose it."""
    inst = QueryInstrumentation()
    for _ in range(7):
        inst.record(QueryTrace(winning_variant="canonical"))
    for _ in range(2):
        inst.record(QueryTrace(winning_variant="possessive"))
    for _ in range(1):
        inst.record(QueryTrace(winning_variant="acronym"))

    s = inst.summary()
    assert s["winner_by_variant"] == {
        "canonical": 7, "possessive": 2, "acronym": 1,
    }
    assert s["canonical_winner"] == 7
    assert s["variant_winner"] == 3


# ── Sanity: extraction normalizes dict-ish JSONL mapping the same way ──

def test_jsonl_style_mapping_produces_stable_tokens():
    """v12.5 maps JSONL message fields to subject/relation/object. The
    closed-loop pipeline must produce the same canonical stream regardless
    of whether a record arrives pre-mapped or as free text."""
    p = CanonicalizationPipeline()
    mapped = p.canonicalize(
        subject="alice", relation="twitter",
        obj="deploying machine learning models")
    free = p.canonicalize_query("alice twitter deploying machine learning models")
    assert mapped.tokens == free.tokens


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
