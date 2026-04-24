"""metrics.py — pure metric helpers.

Functions are stateless and import-only-numpy/stdlib. Safe to use from
production observability paths, not just benchmark scripts.
"""

from __future__ import annotations

import math
import statistics
from typing import Iterable, List, Sequence


def hit_at_k(rank: int, k: int) -> int:
    """1 if gold appeared at rank ≤ k (1-indexed), else 0. rank=0 means absent."""
    return 1 if 1 <= rank <= k else 0


def reciprocal_rank(rank: int) -> float:
    """1/rank if gold present (rank ≥ 1), else 0."""
    return (1.0 / rank) if rank >= 1 else 0.0


def ndcg_at_k(retrieved: Sequence, gold: Iterable, k: int = 10) -> float:
    """Normalized discounted cumulative gain. Binary relevance."""
    gold_set = set(gold)
    if not gold_set:
        return 0.0
    dcg = sum(1.0 / math.log2(i + 1)
              for i, doc_id in enumerate(retrieved[:k], start=1)
              if doc_id in gold_set)
    ideal_n = min(len(gold_set), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_n + 1))
    return dcg / idcg if idcg > 0 else 0.0


def percentile(values: Sequence[float], p: int) -> float:
    """Inclusive percentile, 0–100. Returns max() for tiny samples."""
    if not values:
        return 0.0
    if len(values) < 100:
        if p >= 95:
            return max(values)
        if p == 50:
            return statistics.median(values)
        return sorted(values)[int(len(values) * p / 100)]
    return statistics.quantiles(values, n=100)[p - 1]


def aggregate(per_query_ranks: Sequence[int],
               per_query_latencies_ms: Sequence[float]) -> dict:
    """Standard aggregate metrics across a query batch.

    `per_query_ranks` are 1-indexed ranks of the first gold hit per query
    (0 if no gold in top-k). `per_query_latencies_ms` are wall-clock per
    query in milliseconds.
    """
    n = len(per_query_ranks)
    if n == 0:
        return {"n": 0}
    hit1 = sum(hit_at_k(r, 1) for r in per_query_ranks)
    hit5 = sum(hit_at_k(r, 5) for r in per_query_ranks)
    hit10 = sum(hit_at_k(r, 10) for r in per_query_ranks)
    mrr = sum(reciprocal_rank(r) for r in per_query_ranks) / n
    return {
        "n":          n,
        "Hit@1":      round(100.0 * hit1 / n, 2),
        "Hit@5":      round(100.0 * hit5 / n, 2),
        "Hit@10":     round(100.0 * hit10 / n, 2),
        "MRR":        round(mrr, 4),
        "p50_ms":     round(percentile(per_query_latencies_ms, 50), 2),
        "p95_ms":     round(percentile(per_query_latencies_ms, 95), 2),
        "max_ms":     round(max(per_query_latencies_ms), 2)
                       if per_query_latencies_ms else 0.0,
        "mean_ms":    round(statistics.mean(per_query_latencies_ms), 2)
                       if per_query_latencies_ms else 0.0,
    }
