"""Stage 1 — single-pass structural scanner (PlanC §4.1).

Streams JSONL, classifies via TierRouter, accumulates per-tier
histograms. Never materializes the corpus; all state is numpy arrays
bounded by tier count × histogram width, not record count.

Output: per-tier p50/p95/p99 of n_atoms / n_slots, and a sample-offset
array that Stage 2 uses to draw stratified samples without re-reading
the whole file.
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..tier_router import TierRouter
from ..tier_types import Tier


# Histogram widths. A record's n_atoms / n_slots above these is clipped
# into the top bin — the p99 summary in CorpusProfile preserves the
# long-tail signal, so clipping here only affects the histogram shape
# we report in the sweep record, not the (D, k) recommendation.
_ATOMS_HIST_WIDTH = 64
_SLOTS_HIST_WIDTH = 64

_TIERS = (Tier.STRUCTURED_ATOMIC, Tier.EXTRACTED_TRIPLE, Tier.EMERGENT_STRUCTURE)


def _count_atoms(record: dict) -> int:
    """Cheap n_atoms estimate — tokens that enter binding at Tier 1.

    For structured inputs, count tokens across S/R/O. For free text,
    a whitespace split approximates token count; the real token count
    is computed by the C++ pipeline at encode time. We only need the
    shape for histogram bucketing here.
    """
    n = 0
    for field in ("subject", "relation", "object"):
        v = record.get(field, "") or ""
        if v:
            n += len(v.split())
    text = record.get("text", "") or ""
    if text:
        n += len(text.split())
    return n


def _count_slots(record: dict) -> int:
    """Cheap n_slots estimate for Tier 2/3 — distinct role bindings a
    sentence would generate. Approximated as the count of capitalized
    spans + conjunction markers; refined by the extractor at encode."""
    text = (record.get("text") or record.get("object") or "") or ""
    if not text:
        return 0
    tokens = text.split()
    slots = sum(1 for t in tokens if t and t[0].isupper())
    # each `and`/`,` adds a potential secondary slot
    slots += text.count(",") + text.lower().count(" and ")
    return slots


def _percentile(hist: np.ndarray, pct: float) -> int:
    """Percentile over a histogram. Returns the bucket index."""
    total = int(hist.sum())
    if total == 0:
        return 0
    target = pct * total
    acc = 0
    for i in range(hist.shape[0]):
        acc += int(hist[i])
        if acc >= target:
            return i
    return hist.shape[0] - 1


def scan(
    source_path: str | Path,
    *,
    router: Optional[TierRouter] = None,
    sample_size: int = 10_000,
    seed: int = 42,
    progress_every: int = 1_000_000,
) -> Tuple[Dict, np.ndarray]:
    """Single streaming pass over the source JSONL.

    Returns:
      - A dict summary keyed by tier value (`structured_atomic` etc.)
        with `count`, `n_atoms_p50/p95/p99`, `n_slots_p50/p95/p99`,
        `char_len_p50/p95/p99`.
      - A sample offset array (`np.int64`) of `sample_size` file byte
        offsets drawn via reservoir sampling with tier stratification.
        Stage 2 seeks to these offsets directly.

    Memory is O(tier_count × histogram_width) + O(sample_size) —
    independent of corpus size.
    """
    router = router or TierRouter()
    path = Path(source_path)

    # Per-tier histograms as numpy ints (zero python containers per record).
    atoms_hist = {t: np.zeros(_ATOMS_HIST_WIDTH, dtype=np.int64) for t in _TIERS}
    slots_hist = {t: np.zeros(_SLOTS_HIST_WIDTH, dtype=np.int64) for t in _TIERS}
    char_hist  = {t: np.zeros(64, dtype=np.int64) for t in _TIERS}
    tier_counts = {t: 0 for t in _TIERS}

    # Reservoir sampling of byte offsets per tier — equal target fill
    # per tier with proportional reweighting at the end. Each slot is a
    # single int64; the reservoir is np.int64[sample_size].
    per_tier_target = max(1, sample_size // len(_TIERS))
    reservoirs = {t: np.zeros(per_tier_target, dtype=np.int64) for t in _TIERS}
    res_filled = {t: 0 for t in _TIERS}
    rng = random.Random(seed)

    total_records = 0
    t0 = time.perf_counter()
    with open(path, "rb") as f:
        while True:
            offset = f.tell()
            line = f.readline()
            if not line:
                break
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue
            total_records += 1
            if progress_every and total_records % progress_every == 0:
                el = time.perf_counter() - t0
                rate = total_records / el if el > 0 else 0
                print(f"    [scan] {total_records:,} records in "
                      f"{el:.1f}s ({rate:,.0f}/s)",
                      file=sys.stderr, flush=True)

            tier = router.from_record(record)
            tier_counts[tier] += 1

            n_atoms = _count_atoms(record)
            n_slots = _count_slots(record) if tier != Tier.STRUCTURED_ATOMIC else 0
            c_len = len(line)

            atoms_hist[tier][min(n_atoms, _ATOMS_HIST_WIDTH - 1)] += 1
            slots_hist[tier][min(n_slots, _SLOTS_HIST_WIDTH - 1)] += 1
            char_hist[tier][min(c_len // 128, 63)] += 1

            # Reservoir sampling per tier.
            k_filled = res_filled[tier]
            if k_filled < per_tier_target:
                reservoirs[tier][k_filled] = offset
                res_filled[tier] = k_filled + 1
            else:
                idx = rng.randrange(tier_counts[tier])
                if idx < per_tier_target:
                    reservoirs[tier][idx] = offset

    # Assemble summary. Percentiles are bucket indices — for n_atoms /
    # n_slots the bucket *is* the value; for char_len the bucket is
    # scaled by 128 back to bytes.
    summary = {"total_records": int(total_records)}
    for t in _TIERS:
        cnt = int(tier_counts[t])
        summary[t.value] = {
            "count": cnt,
            "n_atoms_p50":   _percentile(atoms_hist[t], 0.50),
            "n_atoms_p95":   _percentile(atoms_hist[t], 0.95),
            "n_atoms_p99":   _percentile(atoms_hist[t], 0.99),
            "n_slots_p50":   _percentile(slots_hist[t], 0.50),
            "n_slots_p95":   _percentile(slots_hist[t], 0.95),
            "n_slots_p99":   _percentile(slots_hist[t], 0.99),
            "char_len_p50":  _percentile(char_hist[t], 0.50) * 128,
            "char_len_p95":  _percentile(char_hist[t], 0.95) * 128,
            "char_len_p99":  _percentile(char_hist[t], 0.99) * 128,
        }

    # Merge reservoirs into one offset array (only the filled portion
    # of each — unfilled tiers contribute nothing).
    filled = [reservoirs[t][:res_filled[t]] for t in _TIERS]
    offsets = np.concatenate(filled) if any(a.size for a in filled) else np.zeros(0, dtype=np.int64)
    return summary, offsets
