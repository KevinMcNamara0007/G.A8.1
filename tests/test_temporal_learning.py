#!/usr/bin/env python3
"""
G.A8.1 — Temporal Learning Simulation

Simulates realistic analyst usage over 5 days:
  Day 1: 20 diverse queries (initial learning)
  Day 2: 15 queries (some repeat patterns, some new)
  Day 3: 15 queries (Ebbinghaus prunes noise from Day 1)
  Day 4: 20 queries (V2 harder queries, benefits from Day 1-3 learning)
  Day 5: Original 50 benchmark (measures convergence)

Between each "day", we advance the clock by 24 hours so
the Ebbinghaus curve has time to prune weak associations.
"""

import json
import sys
import time
import logging
from pathlib import Path

logging.basicConfig(level=logging.WARNING)

_a81_decode = str(Path(__file__).parent / "decode")
sys.path.insert(0, _a81_decode)
sys.path.insert(0, str(Path(__file__).parent / "encode"))
_edge = "/Users/stark/Quantum_Computing_Lab/MjolnirPhotonics/product.edge.analyst.bsc"
sys.path.insert(0, f"{_edge}/edge_service/src")

from hooks import load_hooks
from query_service import QueryService
from adaptive_gazetteer import AdaptiveGazetteer

# ── Query sets ───────────────────────────────────────────────

DAY1_QUERIES = [
    "iran nuclear program",
    "hezbollah military operations",
    "cyber attacks infrastructure",
    "missile test ballistic",
    "sanctions evasion oil",
    "terrorism financing hawala",
    "proxy wars syria",
    "drone strikes yemen",
    "assassination military commander",
    "protest civil unrest iran",
    "hamas rocket attacks gaza",
    "isis remnants iraq",
    "espionage intelligence operations",
    "chemical weapons syria",
    "money laundering dubai",
    "humanitarian crisis refugees",
    "nuclear enrichment natanz",
    "taliban afghanistan",
    "russian military syria",
    "propaganda disinformation telegram",
]

DAY2_QUERIES = [
    "iran missile test",           # repeat pattern from Day 1
    "hezbollah weapons smuggling",  # builds on Day 1 hezbollah
    "cyber espionage iran",         # combines Day 1 themes
    "nuclear facility fordow",      # builds on Day 1 nuclear
    "sanctions circumvention swift", # builds on Day 1 sanctions
    "humanitarian aid displaced",   # builds on Day 1 humanitarian
    "isis recruitment online",      # builds on Day 1 isis
    "proxy militia iraq",           # builds on Day 1 proxy
    "assassination scientist iran", # builds on Day 1 assassination
    "drone attack saudi",           # builds on Day 1 drone
    "propaganda social media bots",
    "arms embargo violations",
    "refugee camps conditions",
    "protest crackdown tehran",
    "IRGC quds force operations",
]

DAY3_QUERIES = [
    "iran nuclear deal violations",  # reinforces nuclear associations
    "hezbollah tunnel border",       # reinforces hezbollah
    "cyber attack power grid",       # reinforces cyber
    "ballistic missile launch",      # reinforces missile
    "oil smuggling sanctions",       # reinforces sanctions
    "terror financing network",      # reinforces terror
    "syria proxy conflict",          # reinforces proxy
    "yemen houthi drone",            # reinforces drone+yemen
    "espionage mossad operation",    # reinforces espionage
    "humanitarian crisis gaza",      # reinforces humanitarian
    "chemical attack civilians",
    "money laundering cryptocurrency",
    "taliban government kabul",
    "propaganda election interference",
    "arms trafficking smuggling",
]

DAY4_QUERIES = [
    "IRGC operations in Syria and Lebanon",
    "Iranian weapons shipments to Yemen",
    "uranium enrichment beyond JCPOA limits",
    "SWIFT sanctions circumvention Iran",
    "hawala money transfer networks",
    "Fordow underground nuclear facility",
    "Hezbollah tunnel network Lebanon border",
    "cryptocurrency funding terrorist organizations",
    "defector reveals nuclear program details",
    "journalist arrested espionage charges Iran",
    "front companies sanctions busting",
    "centrifuge cascade installation Natanz",
    "state sponsored cyber attacks",
    "online recruitment extremist groups",
    "assassinated scientist nuclear program",
    "diplomatic negotiations peace talks",
    "oil smuggling sanctions evasion",
    "gold smuggling Turkey Iran",
    "prisoner exchange negotiations hostages",
    "opposition figure poisoned exile",
]

# Benchmark queries (same as original 50)
BENCHMARK_QUERIES = [
    ("A", "find all links between Iran and Terror"),
    ("A", "connections between Venezuela and cartels"),
    ("A", "links between Russia and Syria"),
    ("A", "Iran and Israel conflict"),
    ("A", "relationship between Hezbollah and Iran"),
    ("A", "Turkey and Kurdish forces"),
    ("A", "China and North Korea alliance"),
    ("A", "Saudi Arabia and Yemen war"),
    ("A", "Pakistan and Taliban connections"),
    ("A", "Qatar and Muslim Brotherhood"),
    ("B", "cyber attacks on infrastructure"),
    ("B", "missile launches and ballistic tests"),
    ("B", "nuclear enrichment programs"),
    ("B", "drone strikes in the middle east"),
    ("B", "chemical weapons use in Syria"),
    ("B", "money laundering and sanctions evasion"),
    ("B", "ransomware attacks on government"),
    ("B", "assassination of military commanders"),
    ("B", "suicide bombings and civilian casualties"),
    ("B", "espionage and intelligence operations"),
    ("C", "IRGC Quds Force operations"),
    ("C", "Hezbollah military activities"),
    ("C", "Hamas rocket attacks"),
    ("C", "Houthi rebel actions"),
    ("C", "ISIS remnants and resurgence"),
    ("C", "Mossad intelligence operations"),
    ("C", "Taliban government policies"),
    ("C", "Al Qaeda network activities"),
    ("C", "Popular Mobilization Forces Iraq"),
    ("C", "Kataib Hezbollah militia"),
    ("D", "protests and civil unrest"),
    ("D", "election interference and propaganda"),
    ("D", "humanitarian crisis and refugees"),
    ("D", "oil and energy geopolitics"),
    ("D", "religious extremism and radicalization"),
    ("D", "arms trafficking and smuggling"),
    ("D", "diplomatic negotiations and peace talks"),
    ("D", "proxy wars in the region"),
    ("D", "social media disinformation campaigns"),
    ("D", "economic sanctions impact"),
    ("E", "Iran missile strike on Israel"),
    ("E", "Natanz nuclear facility sabotage"),
    ("E", "Beirut port explosion"),
    ("E", "Gaza ceasefire negotiations"),
    ("E", "Khamenei statements on nuclear policy"),
    ("E", "IAEA inspections and violations"),
    ("E", "Strait of Hormuz shipping threats"),
    ("E", "Afghanistan withdrawal aftermath"),
    ("E", "Iraq parliament protests"),
    ("E", "Syrian refugee camps conditions"),
]


def evaluate_queries(svc, queries, label=""):
    """Run queries and return scorecard."""
    n = len(queries)
    relevant = precise = media = 0
    kw_sum = 0
    latencies = []

    for cat, query in queries:
        result = svc.query(query, k=10)
        results = result.get("results", [])
        latencies.append(result["audit"]["duration_ms"])

        q_tokens = [w.lower() for w in query.split()
                    if len(w) > 2 and w.lower() not in {
                        "find", "all", "links", "between", "and", "the",
                        "connections", "relationship", "show", "search"}]

        if not results:
            continue

        overlaps = []
        for r in results:
            meta = r.get("metadata", {})
            text = (meta.get("message_text_translated") or meta.get("text", "")).lower()
            tags = meta.get("tags", [])
            tags_str = " ".join(t.lower() for t in tags) if isinstance(tags, list) else str(tags).lower()
            searchable = f"{text} {tags_str}"
            matches = sum(1 for t in q_tokens if t in searchable)
            overlaps.append(matches / max(len(q_tokens), 1))

        avg_ov = sum(overlaps) / max(len(overlaps), 1)
        top_ov = overlaps[0]
        kw_sum += avg_ov * 100

        if avg_ov >= 0.3:
            relevant += 1
        if top_ov >= 0.5:
            precise += 1
        if any(r.get("metadata", {}).get("media_url") for r in results):
            media += 1

    latencies_sorted = sorted(latencies)
    return {
        "relevance": relevant,
        "precision": precise,
        "media": media,
        "n": n,
        "avg_kw": round(kw_sum / max(n, 1), 1),
        "p50": round(latencies_sorted[len(latencies_sorted)//2], 0),
    }


def advance_time(gaz, hours):
    """Simulate time passing by shifting all timestamps backward."""
    shift = hours * 3600
    for root, entries in gaz.memories.items():
        for entry in entries.values():
            entry.last_reinforced -= shift
            entry.created_at -= shift


def main():
    # Clean start
    import os
    gaz_path = "/Users/stark/Quantum_Computing_Lab/OUT/_adaptive_gazetteer.json"
    if os.path.exists(gaz_path):
        os.remove(gaz_path)

    product_dir = _edge
    index_dir = "/Users/stark/Quantum_Computing_Lab/OUT"
    hooks = load_hooks(product_dir=product_dir, index_dir=index_dir)
    svc = QueryService(index_dir, hooks=hooks)

    print("=" * 70)
    print("  G.A8.1 — Temporal Learning Simulation (5 Days)")
    print("=" * 70)

    # ── BASELINE (no learning) ───────────────────────────────
    print("\n  BASELINE (no learning yet):")
    baseline = evaluate_queries(svc, BENCHMARK_QUERIES, "baseline")
    print(f"    Relevance: {baseline['relevance']}/{baseline['n']} ({baseline['relevance']*100//baseline['n']}%)")
    print(f"    Precision: {baseline['precision']}/{baseline['n']} ({baseline['precision']*100//baseline['n']}%)")
    print(f"    Media:     {baseline['media']}/{baseline['n']}")
    print(f"    KW:        {baseline['avg_kw']}%  p50: {baseline['p50']}ms")

    # ── DAY 1 ────────────────────────────────────────────────
    print("\n  DAY 1: 20 diverse queries (initial learning)...")
    for q in DAY1_QUERIES:
        svc.query(q, k=5)
    alive = svc.adaptive_gaz.stats["alive_entries"]
    print(f"    → {alive} associations learned")

    advance_time(svc.adaptive_gaz, 24)
    svc.adaptive_gaz._prune()
    alive_after = svc.adaptive_gaz.stats["alive_entries"]
    print(f"    → 24h later: {alive_after} alive (pruned {alive - alive_after})")

    # ── DAY 2 ────────────────────────────────────────────────
    print("\n  DAY 2: 15 queries (reinforcing patterns)...")
    for q in DAY2_QUERIES:
        svc.query(q, k=5)
    alive = svc.adaptive_gaz.stats["alive_entries"]
    print(f"    → {alive} associations")

    advance_time(svc.adaptive_gaz, 24)
    svc.adaptive_gaz._prune()
    alive_after = svc.adaptive_gaz.stats["alive_entries"]
    print(f"    → 24h later: {alive_after} alive (pruned {alive - alive_after})")

    # ── DAY 3 ────────────────────────────────────────────────
    print("\n  DAY 3: 15 queries (further reinforcement)...")
    for q in DAY3_QUERIES:
        svc.query(q, k=5)
    alive = svc.adaptive_gaz.stats["alive_entries"]
    print(f"    → {alive} associations")

    advance_time(svc.adaptive_gaz, 24)
    svc.adaptive_gaz._prune()
    alive_after = svc.adaptive_gaz.stats["alive_entries"]
    print(f"    → 24h later: {alive_after} alive (pruned {alive - alive_after})")

    # ── DAY 4 ────────────────────────────────────────────────
    print("\n  DAY 4: 20 harder queries (transfer test)...")
    for q in DAY4_QUERIES:
        svc.query(q, k=5)
    alive = svc.adaptive_gaz.stats["alive_entries"]
    print(f"    → {alive} associations")

    advance_time(svc.adaptive_gaz, 24)
    svc.adaptive_gaz._prune()
    alive_after = svc.adaptive_gaz.stats["alive_entries"]
    print(f"    → 24h later: {alive_after} alive (pruned {alive - alive_after})")

    # ── DAY 5: BENCHMARK ─────────────────────────────────────
    print("\n  DAY 5: BENCHMARK (same 50 queries as original)...")
    final = evaluate_queries(svc, BENCHMARK_QUERIES, "day5")

    # ── COMPARISON ───────────────────────────────────────────
    print(f"\n  {'═' * 66}")
    print(f"  TEMPORAL LEARNING RESULTS")
    print(f"  {'═' * 66}")
    print(f"")
    print(f"  {'Metric':<25s} {'Baseline':>10s} {'After 5 Days':>12s} {'Delta':>8s}")
    print(f"  {'─' * 25} {'─' * 10} {'─' * 12} {'─' * 8}")

    for metric, b, f_ in [
        ("Relevance", baseline["relevance"], final["relevance"]),
        ("Precision", baseline["precision"], final["precision"]),
        ("Media", baseline["media"], final["media"]),
    ]:
        delta = f_ - b
        sign = "+" if delta > 0 else ""
        print(f"  {metric:<25s} {b:>5d}/50    {f_:>5d}/50     {sign}{delta}")

    print(f"  {'Avg KW Overlap':<25s} {baseline['avg_kw']:>8.1f}%  {final['avg_kw']:>10.1f}%  "
          f"  {'+' if final['avg_kw'] > baseline['avg_kw'] else ''}"
          f"{final['avg_kw'] - baseline['avg_kw']:.1f}")
    print(f"  {'Latency p50':<25s} {baseline['p50']:>7.0f}ms  {final['p50']:>9.0f}ms")

    print(f"\n  Adaptive Gazetteer Final State:")
    stats = svc.adaptive_gaz.stats
    print(f"    Alive associations: {stats['alive_entries']}")
    print(f"    Total observations: {stats['observations']}")
    if stats['top_associations']:
        print(f"    Strongest learned:")
        for a in stats['top_associations'][:8]:
            print(f"      {a['root']:15s} → {a['term']:20s} "
                  f"({a['reinforcements']}x, S={a['stability_days']}d)")

    print(f"  {'═' * 66}")

    svc.adaptive_gaz.stop()


if __name__ == "__main__":
    main()
