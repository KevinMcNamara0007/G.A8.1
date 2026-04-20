"""Tier 1 tests: SRO triple encode/decode preserves compound tokens.

This is the falsification test PlanB §7.2 calls out: on Wikidata-shape
inputs Tier 1 pass-through must NOT shatter compounds like joe_misiti
or member_of_sports_team.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from decode13 import StructuredAtomicPipeline, Tier
from decode13.tier_encode import TierEncoder
from decode13.tier_query import QueryService13
from decode13.tests.fixtures import STRUCTURED_TRIPLES, STRUCTURED_QUERIES


def test_tier1_atomizes_without_shattering():
    p = StructuredAtomicPipeline()
    d = p.emit(
        subject="joe_misiti",
        relation="member_of_sports_team",
        obj="melbourne_football_club",
    )
    assert d.tier == Tier.STRUCTURED_ATOMIC
    assert len(d.triples) == 1
    tri = d.triples[0]
    # Compound tokens preserved verbatim (lowercased, not split).
    assert tri.subject == "joe_misiti"
    assert tri.relation == "member_of_sports_team"
    assert tri.obj == "melbourne_football_club"
    # Each is a single atom in the token list.
    toks = p.tokens_from_triple(tri)
    assert toks == ["joe_misiti", "member_of_sports_team", "melbourne_football_club"]


def test_tier1_escape_decode_runs():
    p = StructuredAtomicPipeline()
    d = p.emit(
        subject="a&amp;b",
        relation="is",
        obj="c",
    )
    # HTML entity decoded — & survives, underscore placeholder does not.
    assert d.triples[0].subject == "a&b"


def test_encode_decode_preserves_atomic_triples():
    enc = TierEncoder(dim=4096, k=64, seed=42)
    for i, rec in enumerate(STRUCTURED_TRIPLES):
        enc.encode_record(i, rec, explicit_sro=True)
    enc.build_index()

    stats = enc.stats()
    # One vector per triple (Tier 1 emits exactly one).
    assert stats["n_vectors"] == len(STRUCTURED_TRIPLES), stats
    assert stats["tier_counts"]["structured_atomic"] == len(STRUCTURED_TRIPLES)

    svc = QueryService13(enc)
    hits_at_1 = 0
    hits_at_5 = 0
    for qs, qr, gold_idx in STRUCTURED_QUERIES:
        res = svc.query(subject=qs, relation=qr, obj="", k=5, explicit_sro=True)
        ranked = res["results"]
        # Gold record must appear in the top results. Because we queried
        # with (s, r) only (leaving o open), the top-ranked vector should
        # be the one whose S and R match.
        top_ids = [r["source_record_id"] for r in ranked[:5]]
        if top_ids and top_ids[0] == gold_idx:
            hits_at_1 += 1
        if gold_idx in top_ids:
            hits_at_5 += 1
    assert hits_at_1 == len(STRUCTURED_QUERIES), (
        f"Tier 1 Hit@1 should be perfect on atomic triples, "
        f"got {hits_at_1}/{len(STRUCTURED_QUERIES)}")
    assert hits_at_5 == len(STRUCTURED_QUERIES)


def test_shattering_baseline_regression():
    """Document the exact phenomenon PlanB describes: naive canonical
    tokenization of 'joe_misiti' produces different embedding than
    'joe_misiti' atomic, so query-by-atom fails to retrieve query-by-
    shatter."""
    # This test doesn't need the full encoder — just codebook.
    import sys
    for d in (2, 3, 4):
        p = Path(__file__).resolve().parents[d] / "EHC" / "build" / "bindings" / "python"
        if p.exists():
            sys.path.insert(0, str(p))
            break
    import ehc

    cfg = ehc.CodebookConfig()
    cfg.dim = 1024
    cfg.k = 32
    cfg.seed = 42
    cb = ehc.TokenCodebook(cfg)
    cb.build_from_vocabulary([])
    atomic = cb.encode_token("joe_misiti")
    shattered_j = cb.encode_token("joe")
    shattered_m = cb.encode_token("misiti")
    shattered = ehc.superpose([shattered_j, shattered_m])
    # Atomic and shattered representations are orthogonal / near-zero:
    sim = ehc.sparse_cosine(atomic, shattered)
    assert sim < 0.15, (
        f"Expected near-zero similarity between atomic 'joe_misiti' "
        f"and shattered 'joe'+'misiti'; got {sim:.3f}. "
        f"If this ever rises, the shattering problem would not have "
        f"occurred and the Tier 1 motivation disappears.")


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
    print(f"\ntest_structured_atomic: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
