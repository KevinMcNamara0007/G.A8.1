"""
G.A8.1 — Query Instrumentation (§4 of the plan)

Per-query telemetry that makes the convergence hypothesis observable
during runs, not only at final benchmark aggregation. Tracks:
    - Hit@1, Hit@5, rank-of-correct
    - Variants generated + the winning variant
    - Encode-side manifest (shard that produced the top hit)
    - Decode-side manifest (current pipeline)
    - Canonicalization latency vs. retrieval latency

The primary watchable metric is the rolling count of
"Hit@5-but-not-Hit@1" cases — falsifiable predictor from §4 of the plan.
As canonicalization axes tighten, this count should trend toward zero.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Deque, Dict, List, Optional


@dataclass
class QueryTrace:
    """One query's convergence trace. Written to the instrumentation log
    and used by rolling counters for the live convergence signature."""
    query: str = ""
    hit_at_1: Optional[bool] = None
    hit_at_5: Optional[bool] = None
    rank_of_correct: Optional[int] = None
    variants_generated: List[str] = field(default_factory=list)
    winning_variant: Optional[str] = None
    decode_manifest_version: Optional[str] = None
    encode_manifest_version: Optional[str] = None
    manifest_compatible: Optional[bool] = None
    canonicalization_ms: float = 0.0
    retrieval_ms: float = 0.0
    total_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def is_hit5_not_hit1(self) -> bool:
        return bool(self.hit_at_5) and not bool(self.hit_at_1)

    def to_dict(self) -> Dict:
        return asdict(self)


class QueryInstrumentation:
    """Thread-safe rolling-window instrumentation.

    The primary diagnostic is `hit5_not_hit1_count` over a rolling window
    — the curve that §4 predicts should trend toward zero as the loop
    closes, spike when an axis is mis-configured, and stay flat when
    axes don't cover the right asymmetries.
    """

    def __init__(self, log_path: Optional[str] = None,
                 rolling_window: int = 100):
        self.log_path = Path(log_path) if log_path else None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.rolling_window = rolling_window
        self._recent: Deque[QueryTrace] = deque(maxlen=rolling_window)
        # RLock because summary() acquires the lock and then calls
        # rolling_p85_p95_gap, which re-acquires on the same thread.
        self._lock = threading.RLock()
        self._totals = {
            "queries": 0,
            "hit_at_1": 0,
            "hit_at_5": 0,
            "hit5_not_hit1": 0,
            "canonical_winner": 0,
            "variant_winner": 0,
            "manifest_incompatible": 0,
        }
        # Per-variant winner counter. Rising "canonical" share is the
        # convergence signature predicted in §3.
        self._winner_by_variant: Dict[str, int] = {}

    def record(self, trace: QueryTrace) -> None:
        with self._lock:
            self._recent.append(trace)
            self._totals["queries"] += 1
            if trace.hit_at_1:
                self._totals["hit_at_1"] += 1
            if trace.hit_at_5:
                self._totals["hit_at_5"] += 1
            if trace.is_hit5_not_hit1():
                self._totals["hit5_not_hit1"] += 1
            if trace.manifest_compatible is False:
                self._totals["manifest_incompatible"] += 1
            if trace.winning_variant:
                self._winner_by_variant[trace.winning_variant] = (
                    self._winner_by_variant.get(trace.winning_variant, 0) + 1
                )
                if trace.winning_variant == "canonical":
                    self._totals["canonical_winner"] += 1
                else:
                    self._totals["variant_winner"] += 1

        if self.log_path:
            self._append(trace)

    def _append(self, trace: QueryTrace) -> None:
        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(trace.to_dict()) + "\n")
        except Exception:
            # Instrumentation must never break the query path
            pass

    @property
    def rolling_hit5_not_hit1(self) -> int:
        with self._lock:
            return sum(1 for t in self._recent if t.is_hit5_not_hit1())

    @property
    def rolling_p85_p95_gap(self) -> Optional[float]:
        """Point-estimate of the P85/P95 gap over the rolling window,
        computed on hit_at_1 scores. Used as the real-time signal for
        §3.2 convergence watching."""
        with self._lock:
            scores = [1.0 if t.hit_at_1 else 0.0 for t in self._recent
                      if t.hit_at_1 is not None]
        if len(scores) < 20:
            return None
        scores.sort()
        n = len(scores)
        p85 = scores[int(0.85 * n)]
        p95 = scores[int(0.95 * n)]
        return p95 - p85

    def summary(self) -> dict:
        with self._lock:
            return {
                **self._totals,
                "winner_by_variant": dict(self._winner_by_variant),
                "rolling_hit5_not_hit1": self.rolling_hit5_not_hit1,
                "rolling_window_size": len(self._recent),
                "rolling_p85_p95_gap": self.rolling_p85_p95_gap,
            }
