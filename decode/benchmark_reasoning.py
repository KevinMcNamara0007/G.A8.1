#!/usr/bin/env python3
"""
G.A8.1 — Reasoning Mode Benchmark

Three reasoning modes tested against the A8.1 two-tier index:

1. DIRECT — single fan-out query (baseline)
2. COT (Chain-of-Thought) — two-hop: query → intermediate → follow-up query
3. ABDUCTIVE — independent verification: query via different routing path

Also tests COMPLEX queries: multi-entity comparisons that require
combining facts from multiple subjects.

Usage:
    python3 benchmark_reasoning.py /path/to/a81_encoded --queries 500
"""

import argparse
import gc
import hashlib
import json
import math
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

for _d in (2, 3, 4):
    _p = Path(__file__).resolve().parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc

sys.path.insert(0, str(Path(__file__).resolve().parent))
from knowledge_a81 import KnowledgeManager, _tokenize, _hash_entity, STOP_WORDS


def progress_bar(current, total, width=40, extras=""):
    pct = current / max(total, 1)
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    line = f"\r  [{bar}] {current:>{len(str(total))}}/{total} ({pct*100:5.1f}%)"
    if extras:
        line += f"  {extras}"
    sys.stderr.write(line)
    sys.stderr.flush()
    if current >= total:
        sys.stderr.write("\n")


def sample_queries(run_dir, n, seed=42):
    """Sample ground-truth queries with full triple info."""
    rng = random.Random(seed)
    reservoir = []
    count = 0

    for sd in sorted(Path(run_dir).glob("shard_*")):
        tp = sd / "texts.json"
        if not tp.exists():
            continue
        with open(tp) as f:
            texts = json.load(f)
        for ti, text in enumerate(texts):
            parts = text.strip().split()
            if len(parts) < 3:
                continue
            item = {
                "shard_id": int(sd.name.split("_")[1]),
                "full_text": text,
                "subject": parts[0],
                "relation": " ".join(parts[1:-1]),
                "gold": parts[-1],
            }
            count += 1
            if len(reservoir) < n:
                reservoir.append(item)
            else:
                j = rng.randint(0, count - 1)
                if j < n:
                    reservoir[j] = item
        del texts
        gc.collect()

    return reservoir


def sample_complex_queries(run_dir, n, seed=42):
    """Sample complex multi-entity comparison queries.

    Each complex query combines two entities sharing a relation.
    E.g., "Compare X and Y on occupation" — requires facts from both.
    """
    rng = random.Random(seed)

    # Build relation → [(subject, object)] index from a sample of shards
    rel_index = defaultdict(list)
    shards = sorted(Path(run_dir).glob("shard_*"))
    sample_shards = rng.sample(shards, min(100, len(shards)))

    for sd in sample_shards:
        tp = sd / "texts.json"
        if not tp.exists():
            continue
        with open(tp) as f:
            texts = json.load(f)
        for text in texts:
            parts = text.strip().split()
            if len(parts) >= 3:
                subj = parts[0]
                rel = " ".join(parts[1:-1])
                obj = parts[-1]
                rel_index[rel].append((subj, obj))
        del texts

    # Find relations with multiple distinct subjects
    complex_queries = []
    for rel, pairs in rel_index.items():
        subjects = list(set(p[0] for p in pairs))
        if len(subjects) >= 2:
            for _ in range(min(3, len(subjects) // 2)):
                s1, s2 = rng.sample(subjects, 2)
                golds_1 = [p[1] for p in pairs if p[0] == s1]
                golds_2 = [p[1] for p in pairs if p[0] == s2]
                if golds_1 and golds_2:
                    complex_queries.append({
                        "entity_1": s1,
                        "entity_2": s2,
                        "relation": rel,
                        "gold_1": golds_1[0],
                        "gold_2": golds_2[0],
                    })

    rng.shuffle(complex_queries)
    return complex_queries[:n]


def run_direct(km, queries):
    """Baseline: single fan-out query."""
    hit1 = hit5 = 0
    latencies = []

    for i, q in enumerate(queries):
        t0 = time.perf_counter()
        results = km.query(subject=q["subject"], relation=q["relation"], top_k=5)
        elapsed = (time.perf_counter() - t0) * 1000
        latencies.append(elapsed)

        answers = [r.get("object", "") for r in results]
        gold = q["gold"]
        hit1 += 1 if answers and answers[0] == gold else 0
        hit5 += 1 if gold in answers[:5] else 0

        if (i + 1) % 50 == 0:
            progress_bar(i + 1, len(queries),
                        extras=f"Hit@1={hit1/(i+1)*100:.1f}%")

    progress_bar(len(queries), len(queries),
                extras=f"Hit@1={hit1/len(queries)*100:.1f}%")

    return {
        "mode": "direct",
        "n": len(queries),
        "hit1": hit1,
        "hit5": hit5,
        "hit1_pct": round(hit1 / len(queries) * 100, 2),
        "hit5_pct": round(hit5 / len(queries) * 100, 2),
        "p50_ms": round(sorted(latencies)[len(latencies) // 2], 2),
        "mean_ms": round(sum(latencies) / len(latencies), 2),
    }


def run_cot(km, queries):
    """Chain-of-Thought: two-hop queries.

    Hop 1: query(S, R) → get objects
    Hop 2: for each object, query(object, any_relation) → expand graph

    The gold answer may be found in hop 1 (direct) or hop 2 (chain).
    CoT value = hop2_recoveries / total_hop1_misses.
    """
    direct_hit1 = direct_hit5 = 0
    cot_hit1 = cot_hit5 = 0
    cot_recovered = 0
    latencies = []

    for i, q in enumerate(queries):
        t0 = time.perf_counter()
        gold = q["gold"]

        # Hop 1: direct query
        hop1 = km.query(subject=q["subject"], relation=q["relation"], top_k=5)
        hop1_answers = [r.get("object", "") for r in hop1]

        d_hit1 = bool(hop1_answers) and hop1_answers[0] == gold
        d_hit5 = gold in hop1_answers[:5]
        direct_hit1 += d_hit1
        direct_hit5 += d_hit5

        # Hop 2: follow each hop1 result as a new subject
        all_answers = list(hop1_answers)
        if not d_hit5 and hop1_answers:
            for intermediate in hop1_answers[:3]:
                hop2 = km.query(subject=intermediate, top_k=5)
                for r in hop2:
                    obj = r.get("object", "")
                    if obj and obj not in all_answers:
                        all_answers.append(obj)

        c_hit1 = bool(all_answers) and all_answers[0] == gold
        c_hit5 = gold in all_answers[:10]
        cot_hit1 += c_hit1
        cot_hit5 += c_hit5

        if c_hit5 and not d_hit5:
            cot_recovered += 1

        elapsed = (time.perf_counter() - t0) * 1000
        latencies.append(elapsed)

        if (i + 1) % 50 == 0:
            progress_bar(i + 1, len(queries),
                        extras=f"D={direct_hit1/(i+1)*100:.0f}% CoT={cot_hit1/(i+1)*100:.0f}% +{cot_recovered}")

    progress_bar(len(queries), len(queries),
                extras=f"D={direct_hit1/len(queries)*100:.0f}% CoT={cot_hit1/len(queries)*100:.0f}%")

    n = len(queries)
    return {
        "mode": "cot",
        "n": n,
        "direct_hit1": direct_hit1,
        "direct_hit5": direct_hit5,
        "direct_hit1_pct": round(direct_hit1 / n * 100, 2),
        "cot_hit1": cot_hit1,
        "cot_hit5": cot_hit5,
        "cot_hit1_pct": round(cot_hit1 / n * 100, 2),
        "cot_hit5_pct": round(cot_hit5 / n * 100, 2),
        "cot_recovered": cot_recovered,
        "cot_uplift_pct": round((cot_hit5 - direct_hit5) / max(n, 1) * 100, 2),
        "p50_ms": round(sorted(latencies)[len(latencies) // 2], 2),
        "mean_ms": round(sum(latencies) / len(latencies), 2),
    }


def run_abductive(km, queries):
    """Abductive verification: query via alternative routing path.

    For each query:
    1. Primary: query(S, R) → results_A (normal routing)
    2. Verification: query(gold_object, reverse) → results_B (independent path)
    3. If gold appears in BOTH paths → high confidence (verified)

    Measures: how often does cross-path verification confirm direct results?
    """
    direct_hit1 = direct_hit5 = 0
    verified = 0
    verification_attempts = 0
    latencies = []

    for i, q in enumerate(queries):
        t0 = time.perf_counter()
        gold = q["gold"]

        # Path A: normal direct query
        path_a = km.query(subject=q["subject"], relation=q["relation"], top_k=5)
        a_answers = [r.get("object", "") for r in path_a]

        d_hit1 = bool(a_answers) and a_answers[0] == gold
        d_hit5 = gold in a_answers[:5]
        direct_hit1 += d_hit1
        direct_hit5 += d_hit5

        # Path B: reverse — query gold object, look for subject
        if d_hit5:
            verification_attempts += 1
            path_b = km.query(subject=gold, top_k=10)
            b_objects = [r.get("object", "") for r in path_b]
            b_subjects = [r.get("subject", "") for r in path_b]

            # Verification: does path B contain the original subject?
            if q["subject"] in b_objects or q["subject"] in b_subjects:
                verified += 1

        elapsed = (time.perf_counter() - t0) * 1000
        latencies.append(elapsed)

        if (i + 1) % 50 == 0:
            v_rate = verified / max(verification_attempts, 1) * 100
            progress_bar(i + 1, len(queries),
                        extras=f"Hit@5={direct_hit5/(i+1)*100:.0f}% Verified={v_rate:.0f}%")

    progress_bar(len(queries), len(queries))

    n = len(queries)
    return {
        "mode": "abductive",
        "n": n,
        "direct_hit1": direct_hit1,
        "direct_hit5": direct_hit5,
        "direct_hit1_pct": round(direct_hit1 / n * 100, 2),
        "direct_hit5_pct": round(direct_hit5 / n * 100, 2),
        "verification_attempts": verification_attempts,
        "verified": verified,
        "verification_rate_pct": round(verified / max(verification_attempts, 1) * 100, 2),
        "p50_ms": round(sorted(latencies)[len(latencies) // 2], 2),
        "mean_ms": round(sum(latencies) / len(latencies), 2),
    }


def run_complex(km, queries):
    """Complex multi-entity queries: compare two entities on a shared relation.

    Success = both entity's facts retrieved correctly.
    """
    both_hit = one_hit = neither = 0
    latencies = []

    for i, q in enumerate(queries):
        t0 = time.perf_counter()

        # Query entity 1
        r1 = km.query(subject=q["entity_1"], relation=q["relation"], top_k=5)
        a1 = [r.get("object", "") for r in r1]
        hit1 = q["gold_1"] in a1

        # Query entity 2
        r2 = km.query(subject=q["entity_2"], relation=q["relation"], top_k=5)
        a2 = [r.get("object", "") for r in r2]
        hit2 = q["gold_2"] in a2

        if hit1 and hit2:
            both_hit += 1
        elif hit1 or hit2:
            one_hit += 1
        else:
            neither += 1

        elapsed = (time.perf_counter() - t0) * 1000
        latencies.append(elapsed)

        if (i + 1) % 50 == 0:
            progress_bar(i + 1, len(queries),
                        extras=f"Both={both_hit/(i+1)*100:.0f}%")

    progress_bar(len(queries), len(queries))

    n = len(queries)
    return {
        "mode": "complex_comparison",
        "n": n,
        "both_hit": both_hit,
        "one_hit": one_hit,
        "neither": neither,
        "both_hit_pct": round(both_hit / n * 100, 2),
        "one_hit_pct": round(one_hit / n * 100, 2),
        "p50_ms": round(sorted(latencies)[len(latencies) // 2], 2),
        "mean_ms": round(sum(latencies) / len(latencies), 2),
    }


def main():
    p = argparse.ArgumentParser(description="A8.1 Reasoning Benchmark")
    p.add_argument("run_dir", help="Path to A8.1 encoded output")
    p.add_argument("--queries", type=int, default=500)
    p.add_argument("--complex-queries", type=int, default=200)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--dim", type=int, default=16384)
    args = p.parse_args()

    run_dir = Path(args.run_dir)

    print("=" * 65)
    print("  G.A8.1 — Reasoning Mode Benchmark")
    print("=" * 65)

    # Load knowledge manager
    print("\n  Loading A8.1 knowledge manager...")
    km = KnowledgeManager(dim=args.dim, goldc_path=str(run_dir))

    # Sample queries
    print(f"\n  Sampling {args.queries} direct queries (seed={args.seed})...")
    queries = sample_queries(run_dir, args.queries, seed=args.seed)
    print(f"  {len(queries)} queries sampled")

    # ── 1. DIRECT ────────────────────────────────────────────
    print(f"\n  {'─' * 60}")
    print(f"  MODE 1: DIRECT (baseline)")
    print(f"  {'─' * 60}")
    direct = run_direct(km, queries)

    # ── 2. COT ───────────────────────────────────────────────
    print(f"\n  {'─' * 60}")
    print(f"  MODE 2: CHAIN-OF-THOUGHT (two-hop)")
    print(f"  {'─' * 60}")
    cot = run_cot(km, queries)

    # ── 3. ABDUCTIVE ─────────────────────────────────────────
    print(f"\n  {'─' * 60}")
    print(f"  MODE 3: ABDUCTIVE VERIFICATION")
    print(f"  {'─' * 60}")
    abductive = run_abductive(km, queries)

    # ── 4. COMPLEX ───────────────────────────────────────────
    print(f"\n  Sampling {args.complex_queries} complex comparison queries...")
    complex_qs = sample_complex_queries(run_dir, args.complex_queries, seed=args.seed)
    print(f"  {len(complex_qs)} complex queries sampled")

    print(f"\n  {'─' * 60}")
    print(f"  MODE 4: COMPLEX MULTI-ENTITY COMPARISON")
    print(f"  {'─' * 60}")
    complex_r = run_complex(km, complex_qs)

    # ── RESULTS ──────────────────────────────────────────────
    print(f"\n  {'═' * 65}")
    print(f"  RESULTS — A8.1 REASONING BENCHMARK")
    print(f"  {'═' * 65}")

    print(f"\n  DIRECT (baseline):")
    print(f"    Hit@1:  {direct['hit1_pct']:6.2f}%  ({direct['hit1']}/{direct['n']})")
    print(f"    Hit@5:  {direct['hit5_pct']:6.2f}%  ({direct['hit5']}/{direct['n']})")
    print(f"    p50:    {direct['p50_ms']:6.2f}ms")

    print(f"\n  CHAIN-OF-THOUGHT (two-hop):")
    print(f"    Direct Hit@5:  {cot['direct_hit5']}/{cot['n']}")
    print(f"    CoT Hit@5:     {cot['cot_hit5']}/{cot['n']}")
    print(f"    CoT recovered: {cot['cot_recovered']} (misses saved by hop 2)")
    print(f"    CoT uplift:    {cot['cot_uplift_pct']:+.2f}%")
    print(f"    p50:           {cot['p50_ms']:6.2f}ms")

    print(f"\n  ABDUCTIVE VERIFICATION:")
    print(f"    Direct Hit@5:      {abductive['direct_hit5']}/{abductive['n']}")
    print(f"    Verified (cross):  {abductive['verified']}/{abductive['verification_attempts']}")
    print(f"    Verification rate: {abductive['verification_rate_pct']:.1f}%")
    print(f"    p50:               {abductive['p50_ms']:6.2f}ms")

    print(f"\n  COMPLEX COMPARISON:")
    print(f"    Both entities found:  {complex_r['both_hit_pct']:6.2f}%  ({complex_r['both_hit']}/{complex_r['n']})")
    print(f"    One entity found:     {complex_r['one_hit_pct']:6.2f}%  ({complex_r['one_hit']}/{complex_r['n']})")
    print(f"    Neither found:        {complex_r['neither']}/{complex_r['n']}")
    print(f"    p50:                  {complex_r['p50_ms']:6.2f}ms")

    print(f"\n  {'═' * 65}")

    # Save
    scorecard = {
        "type": "a81_reasoning",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seed": args.seed,
        "direct": direct,
        "cot": cot,
        "abductive": abductive,
        "complex": complex_r,
    }
    out_path = run_dir / "a81_reasoning_scorecard.json"
    with open(out_path, "w") as f:
        json.dump(scorecard, f, indent=2)
    print(f"\n  Scorecard: {out_path}")


if __name__ == "__main__":
    main()
