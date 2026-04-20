"""Tier 2 tests: unstructured narrative → atomic triple encode/decode.

Mirrors the §2 example: 'The capital of France is Paris' should emit
(France, capital, Paris) as a validated triple, and a query for 'What
is the capital of France?' should retrieve it."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from decode13 import ExtractionPipeline, Tier
from decode13.extractors import RuleBasedFactSeparator, HeuristicNER, dual_gate
from decode13.tier_encode import TierEncoder
from decode13.tier_query import QueryService13
from decode13.tests.fixtures import UNSTRUCTURED_TEXTS, UNSTRUCTURED_QUERIES


def test_rule_based_extracts_capital_of_france():
    ext = RuleBasedFactSeparator()
    tris = ext.extract("The capital of France is Paris.")
    assert len(tris) >= 1
    # At least one triple should be (france, capital, paris)
    match = [(t.subject, t.relation, t.obj) for t in tris]
    assert ("france", "capital", "paris") in match, match


def test_dual_gate_agrees_on_obvious_facts():
    primary = RuleBasedFactSeparator()
    secondary = HeuristicNER()
    sent = "The capital of France is Paris."
    p = primary.extract(sent)
    s = secondary.extract(sent)
    merged = dual_gate(p, s, mode="default")
    # The (france, capital, paris) triple must appear and be gate-agreed.
    agreed = [t for t in merged if t.gate_agreement]
    assert any(
        (t.subject == "france" and t.relation == "capital" and t.obj == "paris")
        for t in agreed
    ), f"Expected gate agreement on (france, capital, paris); got {[(t.subject,t.relation,t.obj,t.gate_agreement) for t in merged]}"


def test_extraction_pipeline_on_france_profile():
    pipe = ExtractionPipeline()
    fx = UNSTRUCTURED_TEXTS[0]  # france_profile
    dec = pipe.extract(fx["text"])
    assert dec.tier == Tier.EXTRACTED_TRIPLE, dec
    emitted = {(t.subject, t.relation, t.obj) for t in dec.triples}
    assert ("france", "capital", "paris") in emitted, emitted
    # At least two of the three expected triples must be produced.
    expected = set(tuple(t) for t in fx["expected_triples"])
    hit = emitted & expected
    assert len(hit) >= 2, f"expected {expected} ∩ emitted = {hit}"


def test_tier2_encode_decode_end_to_end():
    enc = TierEncoder(dim=4096, k=64, seed=42)
    for i, fx in enumerate(UNSTRUCTURED_TEXTS):
        # Record shape that the tier router treats as Tier 2.
        rec = {"text": fx["text"]}
        enc.encode_record(i, rec)
    enc.build_index()

    # Stats: every fixture should have produced ≥1 Tier 2 vector.
    stats = enc.stats()
    assert stats["tier_counts"]["extracted_triple"] >= 3, stats

    svc = QueryService13(enc)
    hits = 0
    for q_text, gold_id, exp_s, exp_r, exp_o in UNSTRUCTURED_QUERIES:
        res = svc.query(text=q_text, k=5)
        results = res["results"]
        # Record a hit if the top result's triple subject/relation match
        # the expected fact. Object match is allowed to vary (the rule-
        # based extractor may or may not include it).
        top = results[0] if results else None
        if top is None:
            continue
        tri = top.get("triple")
        if tri and tri["s"] == exp_s and tri["r"] == exp_r:
            hits += 1
    assert hits >= 2, (
        f"Expected ≥2 correct Tier 2 retrievals, got {hits}/{len(UNSTRUCTURED_QUERIES)}")


def test_extraction_failure_falls_to_tier3():
    pipe = ExtractionPipeline()
    # Nonsense that won't match any pattern
    dec = pipe.extract("xyzzy plugh frobnicate grault")
    assert dec.tier == Tier.EMERGENT_STRUCTURE
    assert dec.triples == []


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
    print(f"\ntest_extracted_triple: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
