#!/usr/bin/env python3
"""
G.A8.1 — Edge Service Query Benchmark (50 Analyst Queries)

Tests the full C++ pipeline with realistic analyst queries across
5 categories. Produces a confusion matrix and quality scorecard.

Categories:
  A. Geopolitical Links    (entity × entity connections)
  B. Threat & Security     (terrorism, cyber, military)
  C. Actor Profiles        (organizations, people)
  D. Topic Discovery       (broad topic search)
  E. Specific Events       (narrow, time-bound incidents)

Evaluation:
  For each query, we check:
    1. RELEVANT: Do results contain query-relevant content? (keyword overlap ≥ 50%)
    2. PRECISE:  Is the top result strongly relevant? (keyword overlap ≥ 75%)
    3. EXPLAINED: Does "Why this matched" contain meaningful factors?
    4. GAPPED:   Does "Why it might not" identify real gaps?
    5. MEDIA:    Do results include media when available?

Output: confusion matrix + per-category scorecard + test_edge_service.md
"""

import json
import sys
import time
from pathlib import Path

# ── Setup ────────────────────────────────────────────────────
# G.A8.1 decode MUST be first so hooks.py resolves to G.A8.1's, not edge's
_a81_decode = str(Path(__file__).parent / "decode")
sys.path.insert(0, _a81_decode)
sys.path.insert(0, str(Path(__file__).parent / "encode"))
_edge = "/Users/stark/Quantum_Computing_Lab/MjolnirPhotonics/product.edge.analyst.bsc"
sys.path.insert(0, f"{_edge}/edge_service/src")

from hooks import load_hooks
from query_service import QueryService

# ── 50 Analyst Queries ───────────────────────────────────────

QUERIES = [
    # A. Geopolitical Links (10)
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

    # B. Threat & Security (10)
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

    # C. Actor Profiles (10)
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

    # D. Topic Discovery (10)
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

    # E. Specific Events (10)
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

CATEGORY_NAMES = {
    "A": "Geopolitical Links",
    "B": "Threat & Security",
    "C": "Actor Profiles",
    "D": "Topic Discovery",
    "E": "Specific Events",
}


def evaluate_result(query_text: str, result: dict) -> dict:
    """Evaluate a single query result for relevance and explanation quality."""
    results = result.get("results", [])
    audit = result.get("audit", {})

    # Query tokens (simple split for evaluation)
    q_tokens = [w.lower() for w in query_text.split()
                if len(w) > 2 and w.lower() not in {
                    "find", "all", "links", "between", "and", "the",
                    "connections", "relationship", "show", "search"}]

    n_results = len(results)
    latency = audit.get("duration_ms", 0)

    if n_results == 0:
        return {
            "relevant": False, "precise": False, "explained": False,
            "gapped": False, "has_media": False, "n_results": 0,
            "latency_ms": latency, "top_score": 0,
            "avg_keyword_overlap": 0, "top_keyword_overlap": 0,
        }

    # Keyword overlap per result
    overlaps = []
    for r in results:
        meta = r.get("metadata", {})
        text = (meta.get("message_text_translated") or meta.get("text") or "").lower()
        tags = meta.get("tags", [])
        if isinstance(tags, list):
            tags_str = " ".join(t.lower() for t in tags)
        else:
            tags_str = str(tags).lower()
        searchable = f"{text} {tags_str}"

        matches = sum(1 for t in q_tokens if t in searchable)
        overlap = matches / max(len(q_tokens), 1)
        overlaps.append(overlap)

    top_overlap = overlaps[0] if overlaps else 0
    avg_overlap = sum(overlaps) / max(len(overlaps), 1)

    # Check explanation quality
    top_meta = results[0].get("metadata", {})
    why_matched = top_meta.get("why_matched", "")
    why_not = top_meta.get("why_not", "")
    explained = bool(why_matched and "Contains:" in why_matched or "Message contains:" in why_matched)
    gapped = bool(why_not and ("not found" in why_not or "Gap:" in why_not or "unaccounted" in why_not))

    # Media check
    has_media = any(r.get("metadata", {}).get("media_url") for r in results)

    return {
        "relevant": avg_overlap >= 0.3,       # ≥30% average keyword overlap
        "precise": top_overlap >= 0.5,         # top result ≥50% overlap
        "explained": explained,
        "gapped": gapped,
        "has_media": has_media,
        "n_results": n_results,
        "latency_ms": latency,
        "top_score": results[0].get("similarity", 0),
        "avg_keyword_overlap": round(avg_overlap * 100, 1),
        "top_keyword_overlap": round(top_overlap * 100, 1),
    }


def main():
    # Initialize
    product_dir = _edge
    index_dir = "/Users/stark/Quantum_Computing_Lab/OUT"
    hooks = load_hooks(product_dir=product_dir, index_dir=index_dir)
    svc = QueryService(index_dir, hooks=hooks)

    print("=" * 70)
    print("  G.A8.1 — Edge Service Query Benchmark (50 Queries)")
    print("=" * 70)

    # Run all queries
    all_evals = []
    category_evals = {cat: [] for cat in CATEGORY_NAMES}

    for i, (cat, query) in enumerate(QUERIES):
        t0 = time.perf_counter()
        result = svc.query(query, k=10)
        elapsed = (time.perf_counter() - t0) * 1000

        ev = evaluate_result(query, result)
        ev["category"] = cat
        ev["query"] = query
        ev["actual_latency"] = round(elapsed, 1)
        all_evals.append(ev)
        category_evals[cat].append(ev)

        status = "✓" if ev["relevant"] else "✗"
        print(f"  [{i+1:2d}/50] {status} [{cat}] {query[:50]:50s} "
              f"kw={ev['avg_keyword_overlap']:4.0f}% "
              f"top={ev['top_keyword_overlap']:4.0f}% "
              f"media={'Y' if ev['has_media'] else 'N'} "
              f"{ev['actual_latency']:5.0f}ms")

    # ── Confusion Matrix ─────────────────────────────────────
    print("\n" + "=" * 70)
    print("  CONFUSION MATRIX")
    print("=" * 70)

    # Relevant vs Not Relevant per category
    print(f"\n  {'Category':<25s} {'Relevant':>8s} {'Precise':>8s} {'Explained':>10s} {'Gapped':>8s} {'Media':>6s}")
    print(f"  {'─' * 25} {'─' * 8} {'─' * 8} {'─' * 10} {'─' * 8} {'─' * 6}")

    for cat, name in CATEGORY_NAMES.items():
        evs = category_evals[cat]
        n = len(evs)
        rel = sum(1 for e in evs if e["relevant"])
        prec = sum(1 for e in evs if e["precise"])
        expl = sum(1 for e in evs if e["explained"])
        gap = sum(1 for e in evs if e["gapped"])
        media = sum(1 for e in evs if e["has_media"])
        print(f"  {name:<25s} {rel:>3d}/{n:<3d}  {prec:>3d}/{n:<3d}  {expl:>4d}/{n:<4d}  {gap:>3d}/{n:<3d}  {media:>2d}/{n}")

    # Totals
    n_total = len(all_evals)
    total_rel = sum(1 for e in all_evals if e["relevant"])
    total_prec = sum(1 for e in all_evals if e["precise"])
    total_expl = sum(1 for e in all_evals if e["explained"])
    total_gap = sum(1 for e in all_evals if e["gapped"])
    total_media = sum(1 for e in all_evals if e["has_media"])

    print(f"  {'─' * 25} {'─' * 8} {'─' * 8} {'─' * 10} {'─' * 8} {'─' * 6}")
    print(f"  {'TOTAL':<25s} {total_rel:>3d}/{n_total:<3d}  {total_prec:>3d}/{n_total:<3d}  "
          f"{total_expl:>4d}/{n_total:<4d}  {total_gap:>3d}/{n_total:<3d}  {total_media:>2d}/{n_total}")

    # ── Scorecard ────────────────────────────────────────────
    latencies = [e["actual_latency"] for e in all_evals]
    latencies_sorted = sorted(latencies)
    avg_kw = sum(e["avg_keyword_overlap"] for e in all_evals) / n_total

    print(f"\n  {'═' * 68}")
    print(f"  SCORECARD")
    print(f"  {'═' * 68}")
    print(f"  Relevance Rate:    {total_rel}/{n_total} ({total_rel/n_total*100:.0f}%)")
    print(f"  Precision Rate:    {total_prec}/{n_total} ({total_prec/n_total*100:.0f}%)")
    print(f"  Explanation Rate:  {total_expl}/{n_total} ({total_expl/n_total*100:.0f}%)")
    print(f"  Gap Analysis Rate: {total_gap}/{n_total} ({total_gap/n_total*100:.0f}%)")
    print(f"  Media Surfaced:    {total_media}/{n_total} ({total_media/n_total*100:.0f}%)")
    print(f"  Avg Keyword Overlap: {avg_kw:.1f}%")
    print(f"  Latency p50:       {latencies_sorted[len(latencies_sorted)//2]:.0f}ms")
    print(f"  Latency p95:       {latencies_sorted[int(len(latencies_sorted)*0.95)]:.0f}ms")
    print(f"  Latency mean:      {sum(latencies)/n_total:.0f}ms")
    print(f"  {'═' * 68}")

    # ── Write results to markdown ────────────────────────────
    md_path = Path(__file__).parent / "test_edge_service.md"
    with open(md_path, "w") as f:
        f.write("# G.A8.1 Edge Service — Query Benchmark Results\n\n")
        f.write(f"**Date:** {time.strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"**Engine:** G.A8.1 C++ (EHC) with edge analyst hooks\n")
        f.write(f"**Vectors:** {svc.stats['total_vectors']:,}\n")
        f.write(f"**Shards:** {svc.stats['n_shards']}\n")
        f.write(f"**Media:** {svc.stats['total_media_vectors']:,}\n\n")

        f.write("## Scorecard\n\n")
        f.write(f"| Metric | Value |\n|---|---|\n")
        f.write(f"| Relevance Rate | {total_rel}/{n_total} ({total_rel/n_total*100:.0f}%) |\n")
        f.write(f"| Precision Rate | {total_prec}/{n_total} ({total_prec/n_total*100:.0f}%) |\n")
        f.write(f"| Explanation Rate | {total_expl}/{n_total} ({total_expl/n_total*100:.0f}%) |\n")
        f.write(f"| Gap Analysis Rate | {total_gap}/{n_total} ({total_gap/n_total*100:.0f}%) |\n")
        f.write(f"| Media Surfaced | {total_media}/{n_total} ({total_media/n_total*100:.0f}%) |\n")
        f.write(f"| Avg Keyword Overlap | {avg_kw:.1f}% |\n")
        f.write(f"| Latency p50 | {latencies_sorted[len(latencies_sorted)//2]:.0f}ms |\n")
        f.write(f"| Latency p95 | {latencies_sorted[int(len(latencies_sorted)*0.95)]:.0f}ms |\n\n")

        f.write("## Confusion Matrix by Category\n\n")
        f.write("| Category | Relevant | Precise | Explained | Gapped | Media |\n")
        f.write("|---|---|---|---|---|---|\n")
        for cat, name in CATEGORY_NAMES.items():
            evs = category_evals[cat]
            n = len(evs)
            rel = sum(1 for e in evs if e["relevant"])
            prec = sum(1 for e in evs if e["precise"])
            expl = sum(1 for e in evs if e["explained"])
            gap = sum(1 for e in evs if e["gapped"])
            media = sum(1 for e in evs if e["has_media"])
            f.write(f"| {name} | {rel}/{n} | {prec}/{n} | {expl}/{n} | {gap}/{n} | {media}/{n} |\n")
        f.write(f"| **TOTAL** | **{total_rel}/{n_total}** | **{total_prec}/{n_total}** | "
                f"**{total_expl}/{n_total}** | **{total_gap}/{n_total}** | **{total_media}/{n_total}** |\n\n")

        f.write("## Per-Query Results\n\n")
        f.write("| # | Cat | Query | KW% | Top% | Relevant | Precise | Media | Latency |\n")
        f.write("|---|---|---|---|---|---|---|---|---|\n")
        for i, ev in enumerate(all_evals):
            rel = "✓" if ev["relevant"] else "✗"
            prec = "✓" if ev["precise"] else "✗"
            media = "✓" if ev["has_media"] else "—"
            f.write(f"| {i+1} | {ev['category']} | {ev['query'][:45]} | "
                    f"{ev['avg_keyword_overlap']:.0f}% | {ev['top_keyword_overlap']:.0f}% | "
                    f"{rel} | {prec} | {media} | {ev['actual_latency']:.0f}ms |\n")

    print(f"\n  Results saved: {md_path}")

    # Save JSON for programmatic analysis
    json_path = Path(__file__).parent / "test_edge_results.json"
    with open(json_path, "w") as f:
        json.dump({
            "scorecard": {
                "relevance_rate": round(total_rel / n_total * 100, 1),
                "precision_rate": round(total_prec / n_total * 100, 1),
                "explanation_rate": round(total_expl / n_total * 100, 1),
                "gap_analysis_rate": round(total_gap / n_total * 100, 1),
                "media_rate": round(total_media / n_total * 100, 1),
                "avg_keyword_overlap": round(avg_kw, 1),
                "latency_p50": round(latencies_sorted[len(latencies_sorted)//2], 1),
                "latency_p95": round(latencies_sorted[int(len(latencies_sorted)*0.95)], 1),
            },
            "queries": all_evals,
        }, f, indent=2, default=str)
    print(f"  JSON saved: {json_path}")


if __name__ == "__main__":
    main()
