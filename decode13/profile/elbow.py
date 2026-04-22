"""Three-zone plateau-aware selector (v13.1.3, PlanC production review).

v13.1.2's binary confidence gate collapsed the decision to "downsize
confidently" vs "retreat to max." That missed the case most real
corpora live in: measurement is noisy but the noise is symmetric
around a plateau — multiple D values produce indistinguishable recall
above an absolute floor. Retreating to max in that regime is
*anti-conservative*: it costs memory to hide behind statistical
certainty that the data actively says isn't there.

Three zones replace the binary gate:

  Zone 1 — confident monotonic.  Spread > k*noise AND recall rises with D.
                                 Pick Pareto-front best (max recall, tie-break
                                 lower latency, tie-break smaller memory).

  Zone 2 — plateau.              ≥3 distinct D values cluster within
                                 `plateau_epsilon` of best_recall AND
                                 best_recall ≥ `ABSOLUTE_RECALL_FLOOR`.
                                 Pick smallest D in plateau; `headroom > 1.0`
                                 promotes to the next-larger grid D that's
                                 still in the plateau.

  Zone 3 — capacity pressed.     best_recall < `ABSOLUTE_RECALL_FLOOR`.
                                 Even max D doesn't retrieve well; fall back
                                 to cfg default so operators match v13.0 and
                                 investigate why capacity is binding.

  Fallback — ambiguous.          No plateau, no monotonic signal, no capacity
                                 pressure. Sweep is small or contradictory.
                                 Fall back to cfg default.

The key asymmetry the review surfaced: when the data says "D doesn't
matter" (plateau), the honest conservative choice is the SMALLEST D,
not the largest. Smaller D costs less and the measurement itself
rejects the claim that larger D would help.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# ── Grid ─────────────────────────────────────────────────────
GRID_POWER_OF_TWO = (1024, 2048, 4096, 8192, 16384, 32768)
GRID_EXTENDED = (1024, 2048, 4096, 6144, 8192, 12288, 16384, 32768)

# ── Zone knobs ───────────────────────────────────────────────
# Default headroom for Zone 2 plateau selection. Promotes from the
# smallest-D floor to an intermediate "middle of the plateau" pick.
# The old v13.1.2 problem with 1.2 was that it multiplied a D-collapse
# selection; in plateau context the promotion is measurement-supported
# (the target D must itself be in the plateau), so 1.2 is principled.
DEFAULT_HEADROOM = 1.2

# "Plateau member" = recall within this absolute gap of best_recall.
# 0.05 = 5 percentage points. Fixed absolute threshold is simpler and
# more interpretable than noise-scaled thresholds, and it naturally
# disqualifies clearly-weaker Ds (e.g. 0.72 vs best 0.84 → gap 0.12 > 0.05).
PLATEAU_EPSILON = 0.05

# Minimum number of distinct D values in the plateau to trust it as
# a plateau. Two Ds near-best could be coincidence; three+ is a pattern.
PLATEAU_MIN_DIMS = 3

# Recall floor for Zone 2 eligibility. Below this, "plateau at low
# recall" means capacity pressure, not D-insensitivity.
ABSOLUTE_RECALL_FLOOR = 0.50

# Zone 1 confidence gates. Used when plateau doesn't fire and we need
# to decide whether the spread is real signal or noise.
MIN_QUERIES_FOR_CONFIDENT = 50
CONFIDENT_SPREAD_MULTIPLIER = 1.5  # spread must exceed this × noise_bound

# Conservative fallback dims when nothing else applies. Matched to
# v13.0 defaults; grandfather sentinel in TierManifest handles the
# loaded shard geometry.
CONSERVATIVE_FALLBACK_DIM = 16384
CONSERVATIVE_FALLBACK_K = 128


def grid(extended: bool) -> Tuple[int, ...]:
    return GRID_EXTENDED if extended else GRID_POWER_OF_TWO


def round_up_to_grid(value: float, *, extended: bool) -> int:
    g = grid(extended)
    if value <= 0:
        return g[0]
    for d in g:
        if d >= value:
            return d
    return g[-1]


def noise_bound(num_queries: int, mean_recall: float) -> float:
    """Wilson CI half-width: 1.96 √(p(1-p)/N). Returns 0.5 on N<=0."""
    if num_queries <= 0:
        return 0.5
    p = max(0.01, min(0.99, float(mean_recall)))
    return 1.96 * math.sqrt(p * (1.0 - p) / float(num_queries))


def worst_tier_recall(row: Dict) -> float:
    """Worst-case-mixed score: a (D, k) is only as good as its weakest tier."""
    rb = row.get("recall_by_tier", {}) or {}
    return float(min(rb.values())) if rb else 0.0


def mean_tier_recall(row: Dict) -> float:
    rb = row.get("recall_by_tier", {}) or {}
    return float(sum(rb.values()) / len(rb)) if rb else 0.0


def pareto_front(rows: Sequence[Dict], *, score_fn=worst_tier_recall) -> List[Dict]:
    """(score, latency) front. Higher score better; lower latency better."""
    front: List[Dict] = []
    for r in rows:
        s_r = score_fn(r)
        l_r = float(r.get("p50_latency_ms", math.inf))
        dominated = False
        for other in rows:
            if other is r:
                continue
            s_o = score_fn(other)
            l_o = float(other.get("p50_latency_ms", math.inf))
            if (s_o >= s_r and l_o <= l_r and (s_o > s_r or l_o < l_r)):
                dominated = True
                break
        if not dominated:
            front.append(r)
    return front


@dataclass
class ElbowResult:
    recommended_dim: int = 0
    recommended_k: int = 0
    selection_reason: str = ""
    zone: str = "unknown"  # "confident" | "plateau" | "capacity_pressed" | "ambiguous"
    confidence: str = "unknown"  # "high" | "medium" | "low"
    noise_bound: float = 0.0
    recall_spread: float = 0.0
    best_recall: float = 0.0
    plateau_dims: List[int] = field(default_factory=list)
    pareto_front: List[Dict] = field(default_factory=list)
    per_tier_elbow: Dict[str, int] = field(default_factory=dict)
    grid_used: str = "power_of_two"
    notes: str = ""
    headroom_multiplier: float = DEFAULT_HEADROOM
    worst_case_elbow: int = 0


def _per_tier_elbow_diagnostic(rows: Sequence[Dict]) -> Dict[str, int]:
    """Audit-only per-tier smallest-D plateau. Not used for selection."""
    tiers: Dict[str, Dict[int, float]] = {}
    for r in rows:
        d = int(r["dim"])
        for t, rec in (r.get("recall_by_tier", {}) or {}).items():
            tiers.setdefault(t, {})
            if d not in tiers[t] or rec > tiers[t][d]:
                tiers[t][d] = float(rec)
    out: Dict[str, int] = {}
    for t, per_d in tiers.items():
        dims = sorted(per_d.keys())
        if not dims:
            continue
        chosen = dims[-1]
        for i in range(len(dims) - 1):
            d = dims[i]
            r_here = per_d[d]
            r_next = per_d[dims[i + 1]]
            budget = max(0.0, 1.0 - r_here)
            if (r_next - r_here) < 0.10 * budget:
                chosen = d
                break
        out[t] = chosen
    return out


def _promote_via_headroom(
    picked_dim: int,
    picked_k: int,
    plateau_rows: Sequence[Dict],
    extended_grid: bool,
    headroom: float,
) -> Tuple[int, int]:
    """Headroom promotion: walk up the grid, pick smallest grid D ≥
    picked_dim × headroom that has a row IN the plateau set. Use the
    lowest-latency row at that D; break ties by smaller k."""
    if headroom <= 1.0:
        return picked_dim, picked_k
    target = picked_dim * headroom
    g = grid(extended_grid)
    for d in g:
        if d >= target:
            cands = [r for r in plateau_rows if int(r["dim"]) == d]
            if cands:
                best = min(cands, key=lambda r: (float(r.get("p50_latency_ms", math.inf)),
                                                 int(r["k"])))
                return int(best["dim"]), int(best["k"])
            break  # no measurement at this D in plateau → don't leapfrog further
    return picked_dim, picked_k


def recommend(
    sweep_rows: Sequence[Dict],
    *,
    num_queries: int = 0,
    extended_grid: bool = False,
    headroom: float = DEFAULT_HEADROOM,
    cfg_default_dim: int = CONSERVATIVE_FALLBACK_DIM,
    cfg_default_k: int = CONSERVATIVE_FALLBACK_K,
    plateau_epsilon: float = PLATEAU_EPSILON,
    plateau_min_dims: int = PLATEAU_MIN_DIMS,
    absolute_recall_floor: float = ABSOLUTE_RECALL_FLOOR,
) -> ElbowResult:
    """Three-zone plateau-aware selector."""
    result = ElbowResult(
        grid_used=("extended" if extended_grid else "power_of_two"),
        headroom_multiplier=headroom)

    if not sweep_rows:
        result.recommended_dim = cfg_default_dim
        result.recommended_k = cfg_default_k
        result.zone = "ambiguous"
        result.confidence = "low"
        result.selection_reason = "no_sweep_rows_using_cfg_default"
        return result

    result.per_tier_elbow = _per_tier_elbow_diagnostic(sweep_rows)

    worst_scores = [worst_tier_recall(r) for r in sweep_rows]
    best_recall = max(worst_scores)
    mean_rec = sum(worst_scores) / len(worst_scores)
    spread = max(worst_scores) - min(worst_scores)
    nb = noise_bound(num_queries, mean_rec)
    result.noise_bound = nb
    result.recall_spread = spread
    result.best_recall = best_recall
    result.pareto_front = pareto_front(sweep_rows)

    # ── Zone 3: capacity pressed ─────────────────────────────
    if best_recall < absolute_recall_floor:
        result.recommended_dim = cfg_default_dim
        result.recommended_k = cfg_default_k
        result.zone = "capacity_pressed"
        result.confidence = "low"
        result.selection_reason = (
            f"capacity_pressed: best_recall={best_recall:.3f} below "
            f"floor {absolute_recall_floor:.2f}. Max measured D doesn't "
            f"retrieve well — investigate before downsizing.")
        result.notes = (
            f"All measured (D, k) rows produced recall ≤ {best_recall:.3f}. "
            f"The corpus appears capacity-constrained in the sweep range. "
            f"Keeping cfg default (D={cfg_default_dim}, k={cfg_default_k}) "
            f"matches v13.0 operational behavior.")
        return result

    # ── Zone 2: plateau detection ────────────────────────────
    near_best = [r for r in sweep_rows
                 if (best_recall - worst_tier_recall(r)) <= plateau_epsilon]
    distinct_dims_in_plateau = sorted({int(r["dim"]) for r in near_best})
    result.plateau_dims = distinct_dims_in_plateau

    if len(distinct_dims_in_plateau) >= plateau_min_dims:
        # Plateau fires. Smallest D in plateau; tie-break smaller k, then latency.
        pick = min(near_best, key=lambda r: (int(r["dim"]), int(r["k"]),
                                             float(r.get("p50_latency_ms", math.inf))))
        picked_dim, picked_k = int(pick["dim"]), int(pick["k"])
        pre_promote = (picked_dim, picked_k)
        picked_dim, picked_k = _promote_via_headroom(
            picked_dim, picked_k, near_best, extended_grid, headroom)
        promoted = (picked_dim, picked_k) != pre_promote

        result.recommended_dim = picked_dim
        result.recommended_k = picked_k
        result.worst_case_elbow = picked_dim
        result.zone = "plateau"
        # Confidence climbs with plateau breadth and query count.
        if len(distinct_dims_in_plateau) >= 4 and num_queries >= MIN_QUERIES_FOR_CONFIDENT:
            result.confidence = "high"
        else:
            result.confidence = "medium"
        result.selection_reason = (
            f"plateau_smallest_D{'_promoted' if promoted else ''}: "
            f"plateau_size={len(distinct_dims_in_plateau)}, "
            f"eps={plateau_epsilon:.3f}, best_recall={best_recall:.3f}. "
            f"Pre-headroom pick=D{pre_promote[0]}/k{pre_promote[1]}; "
            f"headroom={headroom:.2f} → D{picked_dim}/k{picked_k}.")
        result.notes = (
            f"Plateau detected: {len(distinct_dims_in_plateau)} distinct "
            f"D values within {plateau_epsilon:.2f} of best recall "
            f"{best_recall:.3f}. Selector picked smallest D in plateau "
            f"(D{pre_promote[0]}) then {'promoted via headroom' if promoted else 'applied headroom=1.0'} "
            f"to D{picked_dim}. When the data says D doesn't matter, "
            f"the small-D choice is the conservative one — it costs less "
            f"with the same measured recall.")
        return result

    # ── Zone 1: confident monotonic signal ───────────────────
    if spread > CONFIDENT_SPREAD_MULTIPLIER * nb and num_queries >= MIN_QUERIES_FOR_CONFIDENT:
        front = result.pareto_front
        pick = max(front, key=lambda r: (
            worst_tier_recall(r),
            -float(r.get("p50_latency_ms", math.inf)),
            -(int(r["dim"]) * int(r["k"])),
        ))
        picked_dim, picked_k = int(pick["dim"]), int(pick["k"])

        if headroom > 1.0:
            # In confident zone, headroom promotes only if next-larger
            # grid dim has measured recall ≥ picked recall.
            picked_recall = worst_tier_recall(pick)
            target = picked_dim * headroom
            by_dim_recall: Dict[int, float] = {}
            for r in sweep_rows:
                d = int(r["dim"])
                s = worst_tier_recall(r)
                if d not in by_dim_recall or s > by_dim_recall[d]:
                    by_dim_recall[d] = s
            for d in grid(extended_grid):
                if d >= target and by_dim_recall.get(d, -1.0) >= picked_recall:
                    best_at_d = max(
                        (r for r in sweep_rows if int(r["dim"]) == d),
                        key=lambda r: (worst_tier_recall(r),
                                       -float(r.get("p50_latency_ms", math.inf))),
                        default=None)
                    if best_at_d is not None:
                        picked_dim, picked_k = int(best_at_d["dim"]), int(best_at_d["k"])
                    break

        result.recommended_dim = picked_dim
        result.recommended_k = picked_k
        result.worst_case_elbow = picked_dim
        result.zone = "confident"
        result.confidence = "high"
        result.selection_reason = (
            f"confident_pareto_best: best_recall={best_recall:.3f} at "
            f"D={picked_dim}, k={picked_k}. Spread {spread:.3f} > "
            f"{CONFIDENT_SPREAD_MULTIPLIER}×noise {nb:.3f}; N={num_queries}.")
        result.notes = (
            f"Recall rises clearly with D (spread {spread:.3f} vs noise "
            f"{nb:.3f}). Picked Pareto-front max-recall point. Inspect "
            f"`pareto_front` in profile JSON for alternatives.")
        return result

    # ── Ambiguous fallback ───────────────────────────────────
    result.recommended_dim = cfg_default_dim
    result.recommended_k = cfg_default_k
    result.zone = "ambiguous"
    result.confidence = "low"
    result.selection_reason = (
        f"ambiguous: no plateau (plateau_size={len(distinct_dims_in_plateau)} "
        f"< {plateau_min_dims}), sub-noise spread ({spread:.3f} ≤ "
        f"{CONFIDENT_SPREAD_MULTIPLIER}×noise {nb:.3f}), N={num_queries}.")
    result.notes = (
        f"Sweep signal is ambiguous. No plateau formed and spread is "
        f"within noise. Raise query count (≥ {MIN_QUERIES_FOR_CONFIDENT}) "
        f"or investigate why the sweep doesn't resolve.")
    return result


# ── legacy shims retained for back-compat tests ──────────────
def k_for_dim(d: int) -> int:
    return max(1, int(round(d ** 0.5)))


def tier_elbow(recalls_by_dim, *, threshold_frac: float = 0.02) -> int:
    dims = sorted(recalls_by_dim.keys())
    if not dims:
        return 0
    for i, d in enumerate(dims[:-1]):
        r_here = recalls_by_dim[d]
        r_next = recalls_by_dim[dims[i + 1]]
        budget = max(0.0, 1.0 - r_here)
        threshold = threshold_frac * budget
        if r_next - r_here < threshold:
            return d
    return dims[-1]
