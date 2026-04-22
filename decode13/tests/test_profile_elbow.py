"""v13.1.3 three-zone selector tests."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from decode13.profile.elbow import (  # noqa: E402
    CONSERVATIVE_FALLBACK_DIM, CONSERVATIVE_FALLBACK_K,
    GRID_EXTENDED, GRID_POWER_OF_TWO,
    grid, k_for_dim, noise_bound, pareto_front, recommend,
    round_up_to_grid, tier_elbow, worst_tier_recall,
)


def test_round_up_power_of_two():
    assert round_up_to_grid(1024, extended=False) == 1024
    assert round_up_to_grid(1025, extended=False) == 2048
    assert round_up_to_grid(4097, extended=False) == 8192
    assert round_up_to_grid(9830, extended=False) == 16384
    assert round_up_to_grid(32769, extended=False) == 32768


def test_round_up_extended_grid():
    assert round_up_to_grid(4097, extended=True) == 6144
    assert round_up_to_grid(8193, extended=True) == 12288
    assert round_up_to_grid(9830, extended=True) == 12288


def test_grid_selector():
    assert grid(False) == GRID_POWER_OF_TWO
    assert grid(True) == GRID_EXTENDED


def test_legacy_k_for_dim():
    assert k_for_dim(16384) == 128
    assert k_for_dim(4096) == 64


def test_noise_bound_math():
    assert noise_bound(0, 0.8) == 0.5
    nb = noise_bound(100, 0.8)
    assert 0.07 < nb < 0.09
    assert noise_bound(500, 0.8) < noise_bound(100, 0.8)


def test_worst_tier_recall_picks_min():
    assert worst_tier_recall({"recall_by_tier": {"t1": 0.95, "t2": 0.60}}) == 0.60
    assert worst_tier_recall({"recall_by_tier": {}}) == 0.0


def test_legacy_tier_elbow_still_works():
    r = {1024: 0.40, 2048: 0.70, 4096: 0.95, 8192: 0.9505, 16384: 0.951}
    assert tier_elbow(r, threshold_frac=0.02) == 4096


# ── Zone 2: plateau ──────────────────────────────────────────

def _edge_like_sweep():
    """The actual v13.1.0 edge-corpus sweep (best-k-per-D)."""
    return [
        {"dim": 1024, "k": 32, "p50_latency_ms": 2.6,
         "recall_by_tier": {"t": 0.72}},
        {"dim": 2048, "k": 90, "p50_latency_ms": 7.6,
         "recall_by_tier": {"t": 0.76}},
        {"dim": 4096, "k": 32, "p50_latency_ms": 2.7,
         "recall_by_tier": {"t": 0.80}},
        {"dim": 6144, "k": 78, "p50_latency_ms": 6.6,
         "recall_by_tier": {"t": 0.80}},
        {"dim": 8192, "k": 45, "p50_latency_ms": 3.9,
         "recall_by_tier": {"t": 0.84}},
        {"dim": 12288, "k": 55, "p50_latency_ms": 4.8,
         "recall_by_tier": {"t": 0.80}},
        {"dim": 16384, "k": 128, "p50_latency_ms": 9.7,
         "recall_by_tier": {"t": 0.80}},
        {"dim": 32768, "k": 362, "p50_latency_ms": 30.6,
         "recall_by_tier": {"t": 0.84}},
    ]


def test_plateau_picks_smallest_D_at_headroom_1_0():
    """Zone 2 fires: 6 distinct Ds within 0.05 of best (0.84).
    Smallest D in plateau at headroom=1.0 → D=4096."""
    rows = _edge_like_sweep()
    result = recommend(rows, num_queries=25, extended_grid=True, headroom=1.0)
    assert result.zone == "plateau", f"expected zone=plateau, got {result.zone}"
    assert result.recommended_dim == 4096, (
        f"expected 4096, got {result.recommended_dim}. "
        f"reason={result.selection_reason}")


def test_plateau_promotes_to_6144_at_headroom_1_2():
    """Edge-corpus sweep, headroom=1.2 → D=6144 (4096 × 1.2 = 4915 →
    smallest extended-grid D ≥ 4915 that's still in the plateau = 6144)."""
    rows = _edge_like_sweep()
    result = recommend(rows, num_queries=25, extended_grid=True, headroom=1.2)
    assert result.zone == "plateau"
    assert result.recommended_dim == 6144, (
        f"expected 6144, got {result.recommended_dim}")


def test_plateau_promotes_to_8192_at_headroom_2_0():
    """Edge-corpus sweep, headroom=2.0 → D=8192."""
    rows = _edge_like_sweep()
    result = recommend(rows, num_queries=25, extended_grid=True, headroom=2.0)
    assert result.zone == "plateau"
    assert result.recommended_dim == 8192


def test_plateau_excludes_low_D():
    """D=1024 and D=2048 (recall 0.72, 0.76) must not be in the plateau
    — they're > 0.05 below best (0.84)."""
    rows = _edge_like_sweep()
    result = recommend(rows, num_queries=25, extended_grid=True, headroom=1.0)
    assert 1024 not in result.plateau_dims
    assert 2048 not in result.plateau_dims
    assert 4096 in result.plateau_dims


# ── Zone 3: capacity pressed ─────────────────────────────────

def test_capacity_pressed_all_low_recall():
    """All recall below 0.5 → cfg default fallback, zone=capacity_pressed."""
    rows = [
        {"dim": 1024, "k": 32, "p50_latency_ms": 2,
         "recall_by_tier": {"t": 0.20}},
        {"dim": 4096, "k": 64, "p50_latency_ms": 5,
         "recall_by_tier": {"t": 0.30}},
        {"dim": 16384, "k": 128, "p50_latency_ms": 20,
         "recall_by_tier": {"t": 0.40}},
        {"dim": 32768, "k": 362, "p50_latency_ms": 40,
         "recall_by_tier": {"t": 0.45}},
    ]
    result = recommend(rows, num_queries=500, extended_grid=False, headroom=1.2)
    assert result.zone == "capacity_pressed"
    assert result.recommended_dim == CONSERVATIVE_FALLBACK_DIM
    assert result.recommended_k == CONSERVATIVE_FALLBACK_K


# ── Zone 1: confident monotonic ──────────────────────────────

def test_confident_zone_monotonic_no_plateau():
    """Clear monotonic rise with only 2 Ds near best → no plateau,
    spread passes confidence gate → Pareto best."""
    rows = [
        {"dim": 1024, "k": 32, "p50_latency_ms": 2,
         "recall_by_tier": {"t": 0.30}},
        {"dim": 4096, "k": 64, "p50_latency_ms": 5,
         "recall_by_tier": {"t": 0.55}},
        {"dim": 16384, "k": 128, "p50_latency_ms": 20,
         "recall_by_tier": {"t": 0.95}},
    ]
    result = recommend(rows, num_queries=500, extended_grid=False, headroom=1.0)
    assert result.zone == "confident", (
        f"expected confident, got {result.zone} ({result.selection_reason})")
    assert result.recommended_dim == 16384


# ── Ambiguous fallback ───────────────────────────────────────

def test_ambiguous_fallback_when_neither_fires():
    """Only 2 rows near best, spread below noise, not capacity pressed."""
    rows = [
        {"dim": 1024, "k": 32, "p50_latency_ms": 2,
         "recall_by_tier": {"t": 0.80}},
        {"dim": 16384, "k": 128, "p50_latency_ms": 20,
         "recall_by_tier": {"t": 0.82}},
    ]
    result = recommend(rows, num_queries=25, extended_grid=False, headroom=1.2)
    assert result.zone == "ambiguous"
    assert result.recommended_dim == CONSERVATIVE_FALLBACK_DIM


def test_empty_rows_uses_cfg_default():
    result = recommend([], num_queries=0)
    assert result.recommended_dim == CONSERVATIVE_FALLBACK_DIM
    assert result.recommended_k == CONSERVATIVE_FALLBACK_K


def test_pareto_front_skips_dominated():
    rows = [
        {"dim": 1024, "k": 32, "p50_latency_ms": 2,
         "recall_by_tier": {"t": 0.30}},
        {"dim": 4096, "k": 64, "p50_latency_ms": 10,
         "recall_by_tier": {"t": 0.80}},
        {"dim": 8192, "k": 45, "p50_latency_ms": 4,
         "recall_by_tier": {"t": 0.84}},
        {"dim": 16384, "k": 128, "p50_latency_ms": 30,
         "recall_by_tier": {"t": 0.85}},
    ]
    front = pareto_front(rows)
    dims = {(r["dim"], r["k"]) for r in front}
    assert (4096, 64) not in dims  # dominated by (8192, 45)
    assert (8192, 45) in dims
    assert (1024, 32) in dims       # lowest latency — on front
    assert (16384, 128) in dims     # highest recall — on front


if __name__ == "__main__":
    tests = [
        test_round_up_power_of_two,
        test_round_up_extended_grid,
        test_grid_selector,
        test_legacy_k_for_dim,
        test_noise_bound_math,
        test_worst_tier_recall_picks_min,
        test_legacy_tier_elbow_still_works,
        test_plateau_picks_smallest_D_at_headroom_1_0,
        test_plateau_promotes_to_6144_at_headroom_1_2,
        test_plateau_promotes_to_8192_at_headroom_2_0,
        test_plateau_excludes_low_D,
        test_capacity_pressed_all_low_recall,
        test_confident_zone_monotonic_no_plateau,
        test_ambiguous_fallback_when_neither_fires,
        test_empty_rows_uses_cfg_default,
        test_pareto_front_skips_dominated,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
    print(f"\ntest_profile_elbow: {'FAIL' if failed else 'PASS'} "
          f"({len(tests) - failed}/{len(tests)})")
    sys.exit(1 if failed else 0)
