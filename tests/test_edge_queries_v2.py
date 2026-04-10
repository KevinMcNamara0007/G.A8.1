#!/usr/bin/env python3
"""
G.A8.1 — Edge Service Query Benchmark V2 (50 NEW queries)

Different query patterns to test generalization and learning transfer.
"""

import json
import sys
import time
from pathlib import Path

_a81_decode = str(Path(__file__).parent / "decode")
sys.path.insert(0, _a81_decode)
sys.path.insert(0, str(Path(__file__).parent / "encode"))
_edge = "/Users/stark/Quantum_Computing_Lab/MjolnirPhotonics/product.edge.analyst.bsc"
sys.path.insert(0, f"{_edge}/edge_service/src")

from hooks import load_hooks
from query_service import QueryService

QUERIES_V2 = [
    # A. Cross-border operations (10)
    ("A", "IRGC operations in Syria and Lebanon"),
    ("A", "Iranian weapons shipments to Yemen"),
    ("A", "Russian military advisors in Syria"),
    ("A", "Turkish incursion Kurdish territory"),
    ("A", "Chinese investment in Iranian ports"),
    ("A", "Israeli strikes on Iranian targets in Syria"),
    ("A", "Hezbollah tunnel network Lebanon border"),
    ("A", "Afghan refugees crossing into Iran"),
    ("A", "Iraqi militia cross-border raids"),
    ("A", "Pakistani ISI Taliban cooperation"),

    # B. Cyber & Information warfare (10)
    ("B", "Iranian cyber espionage campaigns"),
    ("B", "social media bot networks propaganda"),
    ("B", "disinformation targeting elections"),
    ("B", "hacking critical infrastructure power grid"),
    ("B", "deepfake videos political leaders"),
    ("B", "Telegram channels spreading misinformation"),
    ("B", "state sponsored cyber attacks"),
    ("B", "online recruitment extremist groups"),
    ("B", "surveillance technology export authoritarian"),
    ("B", "cryptocurrency funding terrorist organizations"),

    # C. Nuclear & WMD (10)
    ("C", "uranium enrichment beyond JCPOA limits"),
    ("C", "Fordow underground nuclear facility"),
    ("C", "IAEA inspector access denied"),
    ("C", "heavy water reactor Arak"),
    ("C", "centrifuge cascade installation Natanz"),
    ("C", "North Korea Iran missile technology transfer"),
    ("C", "chemical weapons stockpile Syria"),
    ("C", "biological weapons research programs"),
    ("C", "nuclear warhead miniaturization"),
    ("C", "dirty bomb radiological dispersal threat"),

    # D. Financial networks (10)
    ("D", "SWIFT sanctions circumvention Iran"),
    ("D", "hawala money transfer networks"),
    ("D", "oil smuggling sanctions evasion"),
    ("D", "cryptocurrency laundering Hezbollah"),
    ("D", "FATF blacklist compliance"),
    ("D", "front companies sanctions busting"),
    ("D", "gold smuggling Turkey Iran"),
    ("D", "narcotics revenue funding militia"),
    ("D", "real estate money laundering Dubai"),
    ("D", "charitable organizations terror financing"),

    # E. Human intelligence (10)
    ("E", "defector reveals nuclear program details"),
    ("E", "double agent compromised intelligence network"),
    ("E", "journalist arrested espionage charges Iran"),
    ("E", "diplomat expelled spying allegations"),
    ("E", "prisoner exchange negotiations hostages"),
    ("E", "whistleblower corruption military contracts"),
    ("E", "assassinated scientist nuclear program"),
    ("E", "protest leader detained incommunicado"),
    ("E", "opposition figure poisoned exile"),
    ("E", "informant network dismantled counterintelligence"),
]

CATEGORY_NAMES = {
    "A": "Cross-border Ops",
    "B": "Cyber & InfoWar",
    "C": "Nuclear & WMD",
    "D": "Financial Networks",
    "E": "Human Intelligence",
}


def evaluate_result(query_text, result):
    results = result.get("results", [])
    audit = result.get("audit", {})
    q_tokens = [w.lower() for w in query_text.split()
                if len(w) > 2 and w.lower() not in {
                    "find", "all", "links", "between", "and", "the",
                    "connections", "relationship", "show", "search", "beyond"}]
    n_results = len(results)
    latency = audit.get("duration_ms", 0)
    if n_results == 0:
        return {"relevant": False, "precise": False, "has_media": False,
                "n_results": 0, "latency_ms": latency,
                "avg_keyword_overlap": 0, "top_keyword_overlap": 0}
    overlaps = []
    for r in results:
        meta = r.get("metadata", {})
        text = (meta.get("message_text_translated") or meta.get("text") or "").lower()
        tags = meta.get("tags", [])
        tags_str = " ".join(t.lower() for t in tags) if isinstance(tags, list) else str(tags).lower()
        searchable = f"{text} {tags_str}"
        matches = sum(1 for t in q_tokens if t in searchable)
        overlaps.append(matches / max(len(q_tokens), 1))
    top_overlap = overlaps[0] if overlaps else 0
    avg_overlap = sum(overlaps) / max(len(overlaps), 1)
    has_media = any(r.get("metadata", {}).get("media_url") for r in results)
    return {
        "relevant": avg_overlap >= 0.3,
        "precise": top_overlap >= 0.5,
        "has_media": has_media,
        "n_results": n_results,
        "latency_ms": latency,
        "avg_keyword_overlap": round(avg_overlap * 100, 1),
        "top_keyword_overlap": round(top_overlap * 100, 1),
    }


def main():
    product_dir = _edge
    index_dir = "/Users/stark/Quantum_Computing_Lab/OUT"
    hooks = load_hooks(product_dir=product_dir, index_dir=index_dir)
    svc = QueryService(index_dir, hooks=hooks)

    print("=" * 70)
    print("  G.A8.1 — Edge Benchmark V2 (50 NEW Queries)")
    print("=" * 70)

    all_evals = []
    category_evals = {cat: [] for cat in CATEGORY_NAMES}

    for i, (cat, query) in enumerate(QUERIES_V2):
        result = svc.query(query, k=10)
        ev = evaluate_result(query, result)
        ev["category"] = cat
        ev["query"] = query
        ev["actual_latency"] = round(result["audit"]["duration_ms"], 1)
        all_evals.append(ev)
        category_evals[cat].append(ev)

        status = "✓" if ev["relevant"] else "✗"
        print(f"  [{i+1:2d}/50] {status} [{cat}] {query[:50]:50s} "
              f"kw={ev['avg_keyword_overlap']:4.0f}% "
              f"media={'Y' if ev['has_media'] else 'N'} "
              f"{ev['actual_latency']:5.0f}ms")

    n_total = len(all_evals)
    total_rel = sum(1 for e in all_evals if e["relevant"])
    total_prec = sum(1 for e in all_evals if e["precise"])
    total_media = sum(1 for e in all_evals if e["has_media"])
    avg_kw = sum(e["avg_keyword_overlap"] for e in all_evals) / n_total
    latencies = sorted(e["actual_latency"] for e in all_evals)

    print(f"\n  {'═' * 68}")
    print(f"  SCORECARD (V2)")
    print(f"  {'═' * 68}")
    print(f"  Relevance Rate:    {total_rel}/{n_total} ({total_rel/n_total*100:.0f}%)")
    print(f"  Precision Rate:    {total_prec}/{n_total} ({total_prec/n_total*100:.0f}%)")
    print(f"  Media Surfaced:    {total_media}/{n_total} ({total_media/n_total*100:.0f}%)")
    print(f"  Avg Keyword Overlap: {avg_kw:.1f}%")
    print(f"  Latency p50:       {latencies[len(latencies)//2]:.0f}ms")
    print(f"  Latency mean:      {sum(latencies)/n_total:.0f}ms")

    print(f"\n  Per-category:")
    for cat, name in CATEGORY_NAMES.items():
        evs = category_evals[cat]
        n = len(evs)
        rel = sum(1 for e in evs if e["relevant"])
        prec = sum(1 for e in evs if e["precise"])
        media = sum(1 for e in evs if e["has_media"])
        print(f"    {name:<22s} Rel={rel}/{n} Prec={prec}/{n} Media={media}/{n}")

    print(f"  {'═' * 68}")

    # Save adaptive gazetteer stats
    if svc.adaptive_gaz:
        stats = svc.adaptive_gaz.stats
        print(f"\n  Adaptive Gazetteer: {stats['alive_entries']} alive associations")
        if stats['top_associations']:
            print(f"  Top learned:")
            for a in stats['top_associations'][:5]:
                print(f"    {a['root']:15s} → {a['term']:20s} "
                      f"({a['reinforcements']}x, S={a['stability_days']}d)")


if __name__ == "__main__":
    main()
