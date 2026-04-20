"""TierRouter classification tests."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from decode13 import Tier, TierRouter


def test_full_sro_is_tier1():
    r = TierRouter()
    assert r.classify(
        subject="joe_misiti",
        relation="member_of_sports_team",
        obj="melbourne_football_club",
    ) == Tier.STRUCTURED_ATOMIC


def test_sr_with_text_object_is_tier1():
    r = TierRouter()
    t = r.classify(
        subject="france", relation="capital",
        obj="", text="Paris",
    )
    assert t == Tier.STRUCTURED_ATOMIC


def test_free_text_is_tier2_speculative():
    r = TierRouter()
    t = r.classify(text="The capital of France is Paris.")
    assert t == Tier.EXTRACTED_TRIPLE


def test_short_text_is_tier3():
    r = TierRouter()
    t = r.classify(text="Hi.")
    assert t == Tier.EMERGENT_STRUCTURE


def test_explicit_sro_override():
    r = TierRouter()
    t = r.classify(text="arbitrary text", explicit_sro=True)
    assert t == Tier.STRUCTURED_ATOMIC


def test_from_record():
    r = TierRouter()
    rec = {"subject": "x", "relation": "is", "object": "y"}
    assert r.from_record(rec) == Tier.STRUCTURED_ATOMIC
    rec2 = {"text": "The quick brown fox jumps over the lazy dog."}
    assert r.from_record(rec2) == Tier.EXTRACTED_TRIPLE
    rec3 = {"text": ""}
    assert r.from_record(rec3) == Tier.EMERGENT_STRUCTURE


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
    print(f"\ntest_tier_router: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
