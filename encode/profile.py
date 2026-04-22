"""v13.1 Corpus Profiler CLI — `python -m encode.profile --source …`.

Orchestrates Stage 1 (scan) → Stage 2 (calibrate) → elbow (recommend)
→ write `corpus_profile.json`. Respects `A81_CPU_FRACTION` via the
shared `resolve_workers` helper. Streams the source; never holds more
than one EHC pipeline in memory at a time.

Honest scope:
  - The power-of-2 default grid produces real recommendations but
    most mixed corpora still round back up to D=16384. The extended
    grid (gated behind `A81_DIMENSIONS_GRID_EXTENDED`) is the path
    to meaningful memory wins. See PlanC_cpp_engineer_memo.md.
  - Stage-2 recall@10 is correct for atomic/superposition capacity
    regimes. Retrieval-at-scale regime is NOT measured; the 1.2x
    headroom is operator judgment covering that gap.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

# Make the G.A8.1 root importable so `from config import cfg` works
# whether this is run as `python -m encode.profile` or directly.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import cfg, resolve_workers  # noqa: E402

from decode13.profile import (  # noqa: E402
    CorpusProfile,
    PROFILE_VERSION,
    compute_source_hash,
    load_profile,
    resolve_sample_size,
    save_profile,
)
from decode13.profile.calibration import build_queries, sweep  # noqa: E402
from decode13.profile.elbow import grid, recommend  # noqa: E402
from decode13.profile.structural_scanner import scan  # noqa: E402
from decode13.tier_router import TierRouter  # noqa: E402


def _count_records(source_path: Path) -> int:
    """Count JSONL lines without materializing them. Single pass."""
    n = 0
    with open(source_path, "rb") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def _build_tier_index(source_path: Path, offsets) -> dict:
    """Map doc_id → tier value. Used by the calibration sweep to
    bucket recall by tier. Keyed by the record's `doc_id` field when
    present (matches calibration_queries.jsonl gold_ids), else by
    offset-iteration order.
    """
    router = TierRouter()
    out: dict = {}
    with open(source_path, "rb") as f:
        for i, off in enumerate(offsets):
            f.seek(int(off))
            line = f.readline()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            did = int(r.get("doc_id", i)) if "doc_id" in r else i
            out[did] = router.from_record(r).value
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="encode.profile",
        description="v13.1 pre-encode corpus profiler (PlanC).")
    ap.add_argument("--source", required=True,
                    help="Path to corpus JSONL.")
    ap.add_argument("--output", required=True,
                    help="Directory to write corpus_profile.json into.")
    ap.add_argument("--sample", type=int, default=0,
                    help="Stage-2 sample size. Default scales with corpus.")
    ap.add_argument("--queries", type=int, default=0,
                    help="Number of calibration queries. Default scales with "
                         "sample: max(200, sample//17). 25 queries gives ~10pp "
                         "noise on a recall@10 estimate; scale up for meaningful "
                         "elbow discrimination. Operator-supplied files keep "
                         "whatever count the file has; we warn if < 100.")
    ap.add_argument("--calibration-queries", default=None,
                    help="Operator-supplied held-out query JSONL (PROD).")
    ap.add_argument("--queries-from-logs", default=None,
                    help="Corpus-derived query log JSONL.")
    ap.add_argument("--synthetic-queries", action="store_true",
                    help="DEV/TEST ONLY: mask-one-field synthetic queries. "
                         "Recall@10 from synthetic is a CEILING measurement.")
    ap.add_argument("--extended-grid", action="store_true",
                    help="Include 6144/12288 in the sweep. Requires "
                         "A81_DIMENSIONS_GRID_EXTENDED=true (C++ engineer "
                         "must clear BSC kernel compatibility first).")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing profile.")
    ap.add_argument("--threads", type=int, default=0,
                    help="Resolved via A81_CPU_FRACTION if 0.")
    ap.add_argument("--policy", default="worst_case_mixed",
                    choices=["worst_case_mixed", "per_tier"],
                    help="per_tier is schema-reserved; raises NotImplementedError.")
    args = ap.parse_args(argv)

    if args.policy == "per_tier":
        raise NotImplementedError(
            "policy=per_tier is schema-reserved for v13.2; not wired in v13.1.")

    source = Path(args.source).resolve()
    outdir = Path(args.output).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    out_path = outdir / "corpus_profile.json"

    if out_path.exists() and not args.force:
        print(f"profile already exists at {out_path}. Use --force to overwrite.",
              file=sys.stderr)
        return 2

    extended = bool(args.extended_grid or cfg.DIMENSIONS_GRID_EXTENDED)
    if args.extended_grid and not cfg.DIMENSIONS_GRID_EXTENDED:
        print(
            "WARNING: --extended-grid passed but A81_DIMENSIONS_GRID_EXTENDED "
            "is false. The extended grid is pending EHC C++ review; proceeding "
            "anyway per explicit CLI opt-in.",
            file=sys.stderr)

    threads = resolve_workers(args.threads)
    print(f"profile: source={source} threads={threads} extended_grid={extended}",
          file=sys.stderr)

    # Count once so we can scale sample size honestly and stamp it.
    total_records = _count_records(source)
    print(f"profile: {total_records} records in source", file=sys.stderr)

    sample = args.sample or resolve_sample_size(total_records)
    # Scale query count with sample size for noise discrimination. One
    # query per ~17 sample records matches the PlanC production-readiness
    # review recommendation. Operator-supplied files override; synthetic
    # generation uses the scaled count.
    n_queries = args.queries if args.queries > 0 else max(200, sample // 17)
    print(f"profile: sample_size={sample} n_queries_target={n_queries}",
          file=sys.stderr)

    # Stage 1 — scan.
    print("profile: stage 1 scan…", file=sys.stderr)
    summary, offsets = scan(source, sample_size=sample)
    print(f"profile: stage 1 done. offsets={len(offsets)}", file=sys.stderr)

    # Build tier-by-id map once so the calibration sweep doesn't re-tokenize.
    tier_by_id = _build_tier_index(source, offsets)

    # Stage 2 — sweep over the grid.
    grid_dims = grid(extended)
    print(f"profile: stage 2 sweep over D={grid_dims}", file=sys.stderr)

    queries, query_source = build_queries(
        source, offsets,
        operator_queries=Path(args.calibration_queries) if args.calibration_queries else None,
        log_queries=Path(args.queries_from_logs) if args.queries_from_logs else None,
        synthetic=args.synthetic_queries,
        n_queries=n_queries,
    )
    actual_q = len(queries)
    if actual_q < 100:
        print(f"profile: WARNING {actual_q} queries (< 100 recommended). "
              f"Noise bound will likely force low-confidence fallback.",
              file=sys.stderr)
    print(f"profile: {actual_q} queries from source={query_source}",
          file=sys.stderr)

    rows = sweep(source, offsets,
                 grid_dims=grid_dims,
                 queries=queries,
                 tier_by_sample_id=tier_by_id,
                 n_threads=threads,
                 progress=True)
    print(f"profile: stage 2 done. {len(rows)} rows", file=sys.stderr)

    # Elbow + recommend.
    row_dicts = [
        {"dim": r.dim, "k": r.k, "recall_by_tier": r.recall_by_tier,
         "p50_latency_ms": r.p50_latency_ms, "p95_latency_ms": r.p95_latency_ms,
         "encode_time_s": r.encode_time_s}
        for r in rows
    ]
    result = recommend(row_dicts,
                       num_queries=actual_q,
                       extended_grid=extended,
                       headroom=cfg.DIMENSIONS_HEADROOM,
                       cfg_default_dim=cfg.DIM,
                       cfg_default_k=cfg.K)

    profile = CorpusProfile(
        profile_version=PROFILE_VERSION,
        source_hash=compute_source_hash(str(source), total_records),
        recommended_dim=result.recommended_dim or cfg.DIM,
        recommended_k=result.recommended_k or cfg.K,
        policy=args.policy,
        structural_scan=summary,
        calibration_sweep=row_dicts,
        elbow_analysis={
            "per_tier_elbow_diagnostic": result.per_tier_elbow,
            "worst_case_elbow": result.worst_case_elbow,
            "headroom_multiplier": result.headroom_multiplier,
            "grid_used": result.grid_used,
            "pareto_front_len": len(result.pareto_front),
            "pareto_front": result.pareto_front,
            "zone": result.zone,
            "confidence": result.confidence,
            "noise_bound": result.noise_bound,
            "recall_spread": result.recall_spread,
            "best_recall": result.best_recall,
            "plateau_dims": result.plateau_dims,
            "selection_reason": result.selection_reason,
            "notes": result.notes,
        },
        generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        tooling={
            "profiler_version": "v13.1-1",
            "cpu_fraction": cfg.CPU_FRACTION,
            "threads": threads,
            "total_records": total_records,
            "sample_size": int(len(offsets)),
        },
        calibration_query_source=query_source,
        grid_extended=extended,
        confidence=result.confidence,
        selection_reason=result.selection_reason,
        num_calibration_queries=actual_q,
        zone=result.zone,
    )

    save_profile(profile, out_path)
    print(f"profile written to {out_path}", file=sys.stderr)
    print(f"recommended D={profile.recommended_dim} k={profile.recommended_k} "
          f"(policy={profile.policy}, grid={result.grid_used})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
