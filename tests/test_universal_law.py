"""Universal law (encode pipeline constants) — empirical pins.

Pins the post-2026-05-12 derive_k_constants contract:

    max_slots         =  round(2·√k)         capped at `ceiling`
    salient_tokens    =  k // 2

with no corpus-dependent terms. The historical p99 lift is opt-in only
(`lift_for_p99=True`), defaults off, and may be removed in a future
release after a longer empirical campaign.

The empirical evidence that motivated this default-flip is the May 2026
EDGE max_slots sweep — see MOE/EDGE/_sweep/sweep_results.json — where
across D ∈ {1024, 2048, 4096, 8192} on a narrative corpus with p99=65,
the law value `max_slots = 2·√k ∈ {11, 13, 16, 19}` matched or beat
the lifted value `max(2·√k, 65)` on Hit@1 at every D. Plate's
superposition-capacity argument explains it: extra slot bindings load
more active bits into the superposed final vector at fixed D, so they
*cost* discriminability when our retrieval is cosine-on-superposition
(no unbinding).

If anyone re-introduces a corpus-dependent lift in the default path,
these tests fail and force a conversation.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

# G.A8.1 root onto sys.path so `from encode._autotune import …` resolves.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from encode._autotune import derive_k_constants  # noqa: E402


# ── canonical (k, expected) values ───────────────────────────────────────
#
# Computed by hand from the universal law:
#     max_slots         = round(2 · sqrt(k))
#     salient_tokens    = k // 2
#
# At canonical k values that arise from the EHC D grid
# {256, 512, 1024, 2048, 4096, 8192, 16384, 32768} via k = round(sqrt(D)):
#
#     D=  256 → k=16     max_slots=  round(2·4)    = 8     salient=  8
#     D=  512 → k=23     max_slots=  round(2·4.80) = 10    salient= 11
#     D= 1024 → k=32     max_slots=  round(2·5.66) = 11    salient= 16
#     D= 2048 → k=45     max_slots=  round(2·6.71) = 13    salient= 22
#     D= 4096 → k=64     max_slots=  round(2·8.00) = 16    salient= 32
#     D= 8192 → k=91     max_slots=  round(2·9.54) = 19    salient= 45
#     D=16384 → k=128    max_slots=  round(2·11.31)= 23    salient= 64
#     D=32768 → k=181    max_slots=  round(2·13.45)= 27    salient= 90
#
CANONICAL_K_TO_CONSTANTS = [
    (16,    8,   8),
    (23,   10,  11),
    (32,   11,  16),
    (45,   13,  22),
    (64,   16,  32),
    (91,   19,  45),
    (128,  23,  64),
    (181,  27,  90),
]


# ── 1. the law itself ────────────────────────────────────────────────────

@pytest.mark.parametrize("k,expected_slots,expected_salient",
                          CANONICAL_K_TO_CONSTANTS)
def test_law_canonical_k_values(k, expected_slots, expected_salient):
    """The triple (max_slots, salient_tokens) is determined entirely by k."""
    out = derive_k_constants(k)
    assert out["max_slots"] == expected_slots, (
        f"law violated at k={k}: max_slots={out['max_slots']}, "
        f"expected {expected_slots} = round(2·√{k})")
    assert out["salient_tokens"] == expected_salient, (
        f"law violated at k={k}: salient_tokens={out['salient_tokens']}, "
        f"expected {expected_salient} = {k}//2")


def test_law_formula_matches_2_sqrt_k():
    """Exhaustive: max_slots == round(2·√k) for all k in [1, 256]."""
    for k in range(1, 257):
        expected = max(1, int(round(2.0 * math.sqrt(k))))
        actual = derive_k_constants(k)["max_slots"]
        # The ceiling at 256 caps the largest k's; bound the check there.
        if expected <= 256:
            assert actual == expected, (
                f"max_slots law violated at k={k}: got {actual}, "
                f"expected round(2·√k)={expected}")


def test_law_formula_matches_k_over_2():
    """Exhaustive: salient_tokens == k // 2 for all k in [1, 256]."""
    for k in range(1, 257):
        expected = max(1, k // 2)
        actual = derive_k_constants(k)["salient_tokens"]
        assert actual == expected, (
            f"salient_tokens law violated at k={k}: got {actual}, "
            f"expected k//2={expected}")


# ── 2. p99_atoms must NOT affect the default output ──────────────────────

@pytest.mark.parametrize("k", [16, 23, 32, 45, 64, 91, 128])
@pytest.mark.parametrize("p99", [0, 1, 5, 65, 100, 200, 500, 10_000])
def test_p99_atoms_does_not_lift_by_default(k, p99):
    """The whole point of the May 2026 default-flip: passing p99_atoms
    in `derive_k_constants(k, p99_atoms=p)` MUST NOT change max_slots
    unless `lift_for_p99=True` is also passed. p99_atoms is preserved
    as an audit-only parameter."""
    baseline = derive_k_constants(k)["max_slots"]
    with_p99 = derive_k_constants(k, p99_atoms=p99)["max_slots"]
    assert baseline == with_p99, (
        f"derive_k_constants(k={k}, p99_atoms={p99}) silently lifted "
        f"max_slots from {baseline} to {with_p99}; the default is "
        f"supposed to ignore p99_atoms unless lift_for_p99=True")


def test_audit_parameter_p99_does_not_disappear_quietly():
    """Sentinel for the most concerning regression: a future refactor
    silently re-enables the lift via signature changes. If p99_atoms
    ever lifts max_slots by default, this fails loudly with a clear
    pointer to the empirical-sweep evidence."""
    # k=32, 2·√32 ≈ 11.31 → 11. Heuristic-baseline would have lifted to p99=65.
    law_only = derive_k_constants(32)["max_slots"]
    with_p99 = derive_k_constants(32, p99_atoms=65)["max_slots"]
    assert law_only == 11
    assert with_p99 == 11, (
        "max_slots silently lifted by p99=65 — review "
        "MOE/EDGE/_sweep/sweep_results.json before re-enabling the lift; "
        "the May 2026 sweep showed -4 pp Hit@1 at this regime")


# ── 3. lift_for_p99=True opt-in still works (escape hatch) ───────────────

def test_explicit_lift_restores_old_behavior():
    """`lift_for_p99=True` is the opt-in escape hatch. It re-enables
    the historical `max(2·√k, p99_atoms)` rule for callers who have
    empirically verified the lift helps their specific corpus."""
    # k=32 → law = 11. p99 = 65 > 11 → lift should kick in.
    out = derive_k_constants(32, p99_atoms=65, lift_for_p99=True)
    assert out["max_slots"] == 65, (
        f"lift_for_p99=True with k=32, p99=65 should produce "
        f"max_slots=65; got {out['max_slots']}")


def test_explicit_lift_no_op_when_law_already_dominates():
    """If 2·√k already exceeds p99_atoms, lift_for_p99=True is a no-op."""
    # k=128 → 2·√128 ≈ 22.6 → 23. p99=5 << 23 → law wins.
    out = derive_k_constants(128, p99_atoms=5, lift_for_p99=True)
    assert out["max_slots"] == 23


def test_explicit_lift_respects_ceiling():
    """The ceiling caps even the lifted value."""
    out = derive_k_constants(64, p99_atoms=10_000, lift_for_p99=True,
                              ceiling=256)
    assert out["max_slots"] == 256


def test_explicit_lift_requires_p99():
    """`lift_for_p99=True` with no `p99_atoms` is a defaulted no-op
    (you opted in but didn't supply a value)."""
    out_law  = derive_k_constants(32)
    out_lift = derive_k_constants(32, lift_for_p99=True)
    assert out_law["max_slots"] == out_lift["max_slots"] == 11


# ── 4. invariants ────────────────────────────────────────────────────────

def test_outputs_have_floor_of_one():
    """max_slots and salient_tokens are clamped to ≥ 1, even at k=0."""
    out = derive_k_constants(0)
    assert out["max_slots"] >= 1
    assert out["salient_tokens"] >= 1
    out = derive_k_constants(1)
    assert out["max_slots"] >= 1
    assert out["salient_tokens"] >= 1


def test_ceiling_is_respected_by_default():
    """At pathological k, max_slots is capped at ceiling. The law itself
    can exceed the ceiling at e.g. k=20000 (2·√20000 ≈ 283); the cap
    keeps encode-time bounded."""
    out = derive_k_constants(20_000, ceiling=256)
    assert out["max_slots"] == 256


def test_no_corpus_dependent_terms_in_default_output():
    """Differential: vary every non-k parameter; default max_slots must
    be a function of k alone."""
    base = derive_k_constants(64)["max_slots"]
    assert derive_k_constants(64, p99_atoms=0)["max_slots"]      == base
    assert derive_k_constants(64, p99_atoms=10_000)["max_slots"] == base
    assert derive_k_constants(64, ceiling=4096)["max_slots"]     == base
    # The ONLY way to change the answer at k=64 is the opt-in lift:
    assert derive_k_constants(64, p99_atoms=200,
                               lift_for_p99=True)["max_slots"] != base
