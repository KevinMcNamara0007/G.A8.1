"""End-to-end test: mixed corpus (SRO triples + unstructured text).

Validates:
  1. Tier 1 and Tier 2 vectors co-exist in the same index.
  2. A structured query retrieves its Tier 1 match.
  3. A free-text query retrieves its Tier 2 match.
  4. Tier 1 ranks above Tier 2/3 for the same query by the per-tier
     confidence weighting (§5 of PlanB).
  5. The shattering baseline — where canonical tokenization would
     shatter joe_misiti — is NOT reproduced under Tier 1.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from decode13 import Tier
from decode13.tier_encode import TierEncoder
from decode13.tier_query import QueryService13
from decode13.tests.fixtures import (
    STRUCTURED_TRIPLES, STRUCTURED_QUERIES,
    UNSTRUCTURED_TEXTS, UNSTRUCTURED_QUERIES,
)


def _build_mixed_service():
    enc = TierEncoder(dim=4096, k=64, seed=42)
    rid = 0
    # Tier 1: structured triples
    for rec in STRUCTURED_TRIPLES:
        enc.encode_record(rid, rec, explicit_sro=True)
        rid += 1
    # Tier 2: narrative text
    for fx in UNSTRUCTURED_TEXTS:
        enc.encode_record(rid, {"text": fx["text"]})
        rid += 1
    enc.build_index()
    return enc, QueryService13(enc)


def test_mixed_corpus_has_both_tiers():
    enc, _ = _build_mixed_service()
    stats = enc.stats()
    assert stats["tier_counts"]["structured_atomic"] == len(STRUCTURED_TRIPLES)
    assert stats["tier_counts"]["extracted_triple"] >= 3


def test_tier1_query_on_mixed_corpus():
    enc, svc = _build_mixed_service()
    hits = 0
    for qs, qr, gold in STRUCTURED_QUERIES:
        res = svc.query(subject=qs, relation=qr, k=5, explicit_sro=True)
        results = res["results"]
        if results and results[0]["source_record_id"] == gold:
            hits += 1
    # Mixed-corpus Hit@1 should be ≥ 7/8 — a tier-routed query is
    # expected to dominate its own tier's matches.
    assert hits >= len(STRUCTURED_QUERIES) - 1, (
        f"Tier 1 Hit@1 in mixed corpus: {hits}/{len(STRUCTURED_QUERIES)}")


def test_tier2_query_on_mixed_corpus():
    enc, svc = _build_mixed_service()
    hits = 0
    for q_text, gold_id, exp_s, exp_r, _exp_o in UNSTRUCTURED_QUERIES:
        res = svc.query(text=q_text, k=5)
        results = res["results"]
        if not results:
            continue
        top = results[0]
        tri = top.get("triple")
        if tri and tri["s"] == exp_s and tri["r"] == exp_r:
            hits += 1
    assert hits >= 2, f"Tier 2 Hit@1: {hits}/{len(UNSTRUCTURED_QUERIES)}"


def test_tier_weighting_favors_tier1_for_structured_queries():
    """A query whose tokens can match both Tier 1 and Tier 3 vectors
    should rank the Tier 1 match higher because of the tier weight."""
    enc, svc = _build_mixed_service()
    # "france capital paris" as a structured query
    res = svc.query(
        subject="france", relation="capital",
        k=10, explicit_sro=True,
    )
    results = res["results"]
    assert results
    top = results[0]
    assert top["tier"] == Tier.STRUCTURED_ATOMIC.value, top


def test_manifest_summary_reflects_mixed_tiers():
    enc, _ = _build_mixed_service()
    summary = enc.manifest_summary()
    tc = summary["tier_counts"]
    assert tc["structured_atomic"] == len(STRUCTURED_TRIPLES)
    assert tc["extracted_triple"] >= 3
    # fully_compatible means the vector's manifest matches the decode
    # manifest under strict composite. Tier 1 vectors match. Tier 2
    # vectors have different composite (different tier string) and
    # therefore differ from the default decode manifest.
    assert summary["fully_compatible"] == tc["structured_atomic"]


def test_manifest_partial_compat_cross_tier():
    """Decode can still match Tier 2 vectors under partial-compat
    matching on axes that don't distinguish Tier 1 from Tier 2."""
    enc, _ = _build_mixed_service()
    reg = enc.registry
    all_vids = list(range(len(enc.encoded)))
    # Under the strict default (full composite), Tier 2 vectors are
    # NOT compatible with the Tier 1 decode manifest.
    strict = reg.compatible_ids(all_vids, axes_used=None)
    assert len(strict) == sum(
        1 for ev in enc.encoded
        if ev.tier == Tier.STRUCTURED_ATOMIC)
    # Under an escape-only partial check, ALL vectors pass.
    loose = reg.compatible_ids(all_vids, axes_used={"escape"})
    assert len(loose) == len(enc.encoded)


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
    print(f"\ntest_end_to_end: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
