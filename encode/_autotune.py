"""Shared autotune helpers — atom-aware zone prediction + discovery log.

Both `encode_triples.py` and `encode_unstructured.py` import from here
so the prediction logic + audit trail stay consistent.

DESIGN
======
Brute-force sweeping all D values in {256, 512, 1024, 2048, 4096,
8192, 16384} costs 7 full encodes × the sample size. For most corpora
4–5 of those D values are wasted — we already have evidence from the
corpus itself about which D zone is even plausible.

ZONE PREDICTION
===============
Each record's "atoms" are the tokens that go into binding. The
worst-case-record's atom count drives the lower-bound D needed to
preserve binding capacity. We use the p99 (not max) to ignore
pathological outliers.

Heuristic mapping (built from edge + wikidata empirical results plus
BSC capacity theory). Conservative: always includes one D above the
predicted floor as a safety check. The atomic-SRO zone shifted down
after the 21.3M Wikidata empirical run found D=512 holding 100%
unique-key Hit@1 — Plate's k² formula is overconservative for
exact-match retrieval (no unbinding) so we no longer treat D≥2048
as a floor.

  p99_atoms  ⇒  predicted zone     rationale
  ─────────     ─────────────     ─────────────────────────────────
   ≤  8         {256, 512, 1024} pure SRO triples, atomic lookups
    9 – 24     {512,1024,2048}   short narratives, social posts
   25 – 200    {1024,...,8192}   long narratives, document chunks
   > 200       {2048,...,16384}  deep ontologies, large docs

DISCOVERY LOG
=============
After the autotune picks a winner, the full discovery (corpus name,
record count, p99 atoms, predicted zone, swept zone, winner, metrics)
is appended to `G.A8.1/universal_constants.md`. Every encode adds an
entry; the file grows over time as institutional memory.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple


_GRID = (256, 512, 1024, 2048, 4096, 8192, 16384)


def derive_k_constants(k: int,
                        p99_atoms: Optional[int] = None,
                        ceiling: int = 256,
                        lift_for_p99: bool = False) -> dict:
    """Compute the pipeline constants both encoders share.

    UNIVERSAL LAW (the default, as of 2026-05-12)
    =============================================
        D                →  k              = round(√D)
        max_slots         =  round(2·√k)     capped at `ceiling`
        salient_tokens    =  k // 2

    No corpus-dependent terms. The triple `(k, max_slots, salient_tokens)`
    is determined entirely by D.

    At canonical k values:
        k= 16 →  max_slots=  8  salient=  8
        k= 23 →  max_slots= 10  salient= 11
        k= 32 →  max_slots= 11  salient= 16
        k= 45 →  max_slots= 13  salient= 22
        k= 64 →  max_slots= 16  salient= 32
        k= 91 →  max_slots= 19  salient= 45
        k=128 →  max_slots= 23  salient= 64

    WHY NO P99 LIFT BY DEFAULT
    ==========================
    Earlier versions added a "p99 lift": when p99_atoms exceeded 2·√k,
    max_slots was raised to p99 on the theory that long-tail records
    needed extra binding-table headroom. The May 2026 EDGE D-sweep
    (`MOE/EDGE/_sweep/sweep_results.json`) refuted this empirically:
    across D ∈ {1024, 2048, 4096, 8192} on a narrative corpus with
    p99=65, the law value `2·√k ∈ {11, 13, 16, 19}` matched or beat
    the lifted value `max(2·√k, 65)` on Hit@1 at every D — and beat
    it by 4 pp at three of the four. The Plate-superposition-capacity
    intuition explains it: every extra slot binding adds active bits
    to the superposed final vector; at fixed D, more contributions =
    more support saturation = less discriminative cosines. Our
    retrieval is cosine-on-superposition (no unbinding), so the
    "headroom" theory wasn't load-bearing for the right capacity
    bound.

    OPT-IN ESCAPE HATCH
    ===================
    Pass `lift_for_p99=True` to restore the old behavior for a
    specific corpus. The `p99_atoms` arg is still accepted (and
    recorded in discovery logs) regardless — it just doesn't change
    `max_slots` unless the lift flag is set.

    CEILING
    =======
    `ceiling` (default 256) bounds encode-time on pathological inputs
    even when the lift is on. O(max_slots) work in two of the three
    binding loops, so we cap it here rather than let a rogue 10k-token
    record blow up ingest.

    All outputs have a floor of 1.
    """
    import math
    sqrt_k = max(1.0, math.sqrt(max(int(k), 1)))
    base = int(round(2.0 * sqrt_k))
    if lift_for_p99 and p99_atoms is not None:
        base = max(base, int(p99_atoms))
    return {
        "max_slots":      min(max(1, base), int(ceiling)),
        "salient_tokens": max(1, int(k) // 2),
    }


def predict_d_zone(p99_atoms: int,
                    has_operator_queries: bool = False) -> Tuple[List[int], str]:
    """Map p99 atoms-per-record to a 2–4 D candidate zone.

    Returns (zone, rationale). Always a subset of _GRID.

    Empirical calibration note: the textbook BSC capacity formula
    (k ≥ atoms², D ≥ k²) over-predicts the D required for
    StructuralPipelineV13's role+bigram+KV+Hebbian binding because it
    assumes role-bound HRR with unbinding-style recovery. We do
    exact-match retrieval on superposed atoms — no unbinding — so
    Plate's bound doesn't apply. On the edge corpus (p99 atoms = 65)
    the formula predicts D ≥ 17000 but real retrieval wins at D=4096;
    on Wikidata-21.3M (p99=2) it works perfectly at D=512.

    `has_operator_queries` shifts the *upper* end: with operator scoring
    we can trust dropping the largest D in the zone, where without
    operator queries we'd keep it as a safety candidate.
    """
    if p99_atoms <= 8:
        return [256, 512, 1024], "atomic SRO regime"
    if p99_atoms <= 24:
        if has_operator_queries:
            return [512, 1024, 2048], "short narrative regime (operator-scored)"
        return [512, 1024, 2048, 4096], "short narrative regime (synthetic-mode wide)"
    if p99_atoms <= 200:
        # Long narrative: empirical evidence (edge corpus, p99=65, D=4096
        # winner at 44% Hit@1) requires keeping D=4096 in the zone.
        return [1024, 2048, 4096, 8192], "long narrative regime (full sweep — formula over-predicts)"
    if has_operator_queries:
        return [4096, 8192, 16384], "deep regime (operator-scored)"
    return [2048, 4096, 8192, 16384], "deep regime (synthetic-mode wide)"


def load_operator_queries(path) -> List[dict]:
    """Read a JSONL of {query_text, gold_ids: [int]} entries.

    Used by encode_*.py autotune as the scoring oracle when supplied via
    --operator-queries. Each entry is the operator's real query plus the
    set of doc_ids in the source corpus that should match it. Hit@1 is
    computed against gold — much closer to real-task quality than
    synthetic mask-first queries.
    """
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "gold_ids" not in rec and "gold_id" in rec:
                rec["gold_ids"] = [int(rec["gold_id"])]
            if "query_text" not in rec or not rec.get("gold_ids"):
                continue
            out.append({
                "query_text": str(rec["query_text"]),
                "gold_ids":   [int(g) for g in rec["gold_ids"]],
            })
    return out


def stream_atom_counts_and_sample(source_path: Path,
                                   sample_path: Path,
                                   sample_n: int,
                                   atoms_fn) -> Tuple[int, int, int]:
    """One streaming pass over `source_path`:

      - Writes the first `sample_n` records to `sample_path` as JSONL
        (each line: {"i": original_index, "raw": payload-as-needed}).
      - Counts atoms per record via `atoms_fn(raw_record) -> int`.
      - Returns (n_total_records, n_sampled, p99_atoms).

    The atoms histogram is bounded (1024 buckets) so RAM is constant
    regardless of corpus size or value spread.
    """
    BUCKETS = 1024  # cap per-record atom count we track
    histogram = [0] * (BUCKETS + 1)
    n_total = 0
    n_sampled = 0
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    with open(sample_path, "w", encoding="utf-8") as sf:
        for i, raw in enumerate(_iter_jsonl(source_path)):
            if raw is None:
                continue
            n_total += 1
            atoms = atoms_fn(raw)
            histogram[min(atoms, BUCKETS)] += 1
            if i < sample_n:
                sf.write(json.dumps({"i": i, "raw": raw},
                                     ensure_ascii=False) + "\n")
                n_sampled = i + 1
    p99 = _hist_percentile(histogram, 0.99)
    return n_total, n_sampled, p99


def _iter_jsonl(source_path: Path):
    """Yield parsed dicts from a JSONL file, skipping bad lines silently."""
    with open(source_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                yield None


def _hist_percentile(histogram: List[int], pct: float) -> int:
    """Percentile from a bucket histogram (bucket index = atom count)."""
    total = sum(histogram)
    if total == 0:
        return 0
    target = pct * total
    cum = 0
    for i, c in enumerate(histogram):
        cum += c
        if cum >= target:
            return i
    return len(histogram) - 1


# ── Universal constants log ──────────────────────────────────

_UNIVERSAL_CONSTANTS_PATH = (Path(__file__).resolve().parents[1]
                              / "universal_constants.md")


def _ensure_constants_header():
    if _UNIVERSAL_CONSTANTS_PATH.exists():
        return
    _UNIVERSAL_CONSTANTS_PATH.write_text(
        "# Universal Constants — Discovered Per-Corpus Geometries\n\n"
        "Append-only audit log of autotune decisions. Each entry below is\n"
        "written by `encode_triples.py` or `encode_unstructured.py` after\n"
        "a successful sweep. Use as institutional memory — when a new\n"
        "corpus shape is encoded, the precedent here can guide initial\n"
        "configuration without re-running a full sweep.\n\n"
        "## Hints\n\n"
        "**For narrative corpora**, supply `--operator-queries` pointing at\n"
        "a JSONL of `{query_text, gold_ids: [doc_id]}` entries derived\n"
        "from your real query patterns. Without operator queries, autotune\n"
        "falls back to a synthetic mask-first heuristic that systematically\n"
        "under-scores narrative corpora and biases the winner toward\n"
        "larger D than the real task needs.\n\n"
        "For edge-shape social-media corpora, generate the canonical\n"
        "25-pattern operator query set with:\n"
        "```\n"
        "python -m decode13.benchmark.build_edge_queries \\\n"
        "    --source <corpus.jsonl> --output <edge_queries.jsonl>\n"
        "```\n\n"
        "**For SRO Tier-1 corpora**, autotune uses unique-(s,r) self-identity\n"
        "as the oracle — no operator queries needed.\n\n"
        "---\n\n"
    )


def _find_prior_entry(corpus_name: str) -> dict:
    """Scan universal_constants.md for the most recent entry matching
    `corpus_name`. Returns {"date": str, "winner_dim": int, "winner_k": int,
    "hit1": float, "p50": float} or {} if none found. Used to annotate
    new entries with delta-vs-prior breadcrumbs."""
    if not _UNIVERSAL_CONSTANTS_PATH.exists():
        return {}
    text = _UNIVERSAL_CONSTANTS_PATH.read_text()
    # Walk sections in order, keep the LAST match for this corpus_name.
    sections = text.split("\n## ")
    last = {}
    for sec in sections:
        if not sec.startswith(corpus_name):
            continue
        # Parse a few key lines from the section
        date = ""
        winner_line = ""
        for line in sec.splitlines():
            if line.startswith("- **Date**:"):
                date = line.split("**Date**:", 1)[1].strip()
            elif line.startswith("- **Winner**:"):
                winner_line = line.split("**Winner**:", 1)[1].strip()
        if winner_line:
            # Format: "D=8192, k=91, Hit@1=44.00%, p50=0.91 ms"
            try:
                parts = [p.strip() for p in winner_line.split(",")]
                d = int(parts[0].split("=")[1])
                k = int(parts[1].split("=")[1])
                h = float(parts[2].split("=")[1].rstrip("%"))
                p = float(parts[3].split("=")[1].split()[0])
                last = {"date": date, "winner_dim": d, "winner_k": k,
                         "hit1": h, "p50": p}
            except (IndexError, ValueError):
                pass
    return last


def append_discovery(*,
                      corpus_name: str,
                      encoder: str,
                      source: str,
                      n_records: int,
                      p99_atoms: int,
                      predicted_zone: List[int],
                      predicted_rationale: str,
                      swept_zone: List[int],
                      sweep_results: List[dict],
                      winner: dict,
                      derived: Optional[dict] = None,
                      note: str = "") -> Path:
    """Append a discovery entry to universal_constants.md.

    `sweep_results` is the per-(D,k) list of {dim, k, Hit@1, p50_ms}.
    `winner` is the chosen entry. `note` is an optional one-line
    annotation (what changed since the previous attempt — e.g. fix that
    motivated this run). Writes a markdown section.

    If a prior entry for the same `corpus_name` exists, the new entry
    annotates the delta vs that prior winner so the audit trail shows
    how decisions evolved over time.
    """
    _ensure_constants_header()
    prior = _find_prior_entry(corpus_name)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    section = []
    section.append(f"## {corpus_name}\n")
    section.append(f"- **Date**: {now}\n")
    if note:
        section.append(f"- **Note**: {note}\n")
    section.append(f"- **Encoder**: `{encoder}`\n")
    section.append(f"- **Source**: `{source}`\n")
    section.append(f"- **Records**: {n_records:,}\n")
    section.append(f"- **p99 atoms/record**: {p99_atoms}\n")
    section.append(f"- **Predicted zone**: {predicted_zone}  ({predicted_rationale})\n")
    section.append(f"- **Swept zone**: {swept_zone}\n")
    section.append(f"- **Sweep results**:\n")
    section.append("  | D | k | Hit@1 | p50 ms |\n")
    section.append("  |---:|---:|---:|---:|\n")
    for r in sweep_results:
        marker = " ← winner" if r["dim"] == winner["dim"] else ""
        section.append(
            f"  | {r['dim']} | {r['k']} | "
            f"{r['Hit@1']:.2f}% | {r['p50_ms']:.2f} |{marker}\n")
    section.append(
        f"- **Winner**: D={winner['dim']}, k={winner['k']}, "
        f"Hit@1={winner['Hit@1']:.2f}%, p50={winner['p50_ms']:.2f} ms\n")
    if derived:
        ms = derived.get("max_slots")
        st = derived.get("salient_tokens")
        import math
        base = max(1, int(round(2.0 * math.sqrt(max(int(winner["k"]), 1)))))
        reason = "=2·√k" if ms == base else f"=max(2·√k, p99) (p99={p99_atoms})"
        section.append(
            f"- **Derived constants** (k={winner['k']}, p99={p99_atoms}): "
            f"max_slots={ms}  ({reason})  •  "
            f"salient_tokens={st}  (=k/2)\n")

    # Breadcrumb: delta vs prior winner if we have one
    if prior:
        d_hit = winner["Hit@1"] - prior["hit1"]
        d_p50 = winner["p50_ms"] - prior["p50"]
        same_d = winner["dim"] == prior["winner_dim"]
        prior_d = prior["winner_dim"]
        new_d = winner["dim"]
        d_tag = ("(same geometry)" if same_d
                 else f"(D shifted {prior_d}→{new_d})")
        section.append(
            f"- **vs prior** ({prior['date']}): "
            f"prior winner D={prior['winner_dim']}/k={prior['winner_k']} "
            f"Hit@1={prior['hit1']:.2f}% p50={prior['p50']:.2f}ms  →  "
            f"this run: ΔHit@1={d_hit:+.2f}pp  Δp50={d_p50:+.2f}ms  "
            f"{d_tag}\n")

    section.append("\n---\n\n")
    with open(_UNIVERSAL_CONSTANTS_PATH, "a", encoding="utf-8") as f:
        f.writelines(section)
    return _UNIVERSAL_CONSTANTS_PATH


# ── Atoms-fn helpers (tier-specific) ─────────────────────────

def atoms_for_sro_tier1(rec: dict) -> int:
    """Token count of (subject + relation) — the encoded key."""
    s = rec.get("subject", "") or ""
    r = rec.get("relation", "") or ""
    return len(s.split()) + len(r.split())


def atoms_for_unstructured(rec: dict) -> int:
    """Token count of the 'text' field."""
    return len((rec.get("text", "") or "").split())
