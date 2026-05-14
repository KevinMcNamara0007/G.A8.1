#!/usr/bin/env python3
"""build_gazetteer_clusters.py — build clusters.json from a relation gazetteer.

For sharded encode (`encode.py`) of narrative corpora, the cluster file is
normally produced by `encode/discover_clusters.py` which scans the source's
`relation` field and k-means-clusters it. Narrative source has no
`relation` field — extraction (Tier-2) is what manufactures the relations
at encode time. So we can't run discover_clusters; we need a different
recipe.

This tool produces an equivalent `clusters.json` by treating the
gazetteer's canonical-relation list as the cluster table directly. For
each canonical relation, the centroid is the EHC-codebook-encoded
SparseVector of that relation token. Two-tier routing then maps records
deterministically to shards according to their extracted relation.

USAGE
=====
    python -m tools.build_gazetteer_clusters \\
        --gazetteer /path/to/relation_gazetteer.json \\
        --output    /path/to/encoded/clusters.json \\
        --dim 4096 --k 64 --seed 42

The (dim, k, seed) must match the encode you'll later run; the codebook
seed determines the SparseVector geometry of each cluster centroid and
therefore the shard-routing partition.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# EHC import probe (same pattern as encode_unstructured.py).
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
for _d in (1, 2, 3):
    _p = _HERE.parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(
        prog="build_gazetteer_clusters",
        description="Generate clusters.json from a relation gazetteer "
                    "for sharded narrative encoding.")
    p.add_argument("--gazetteer", required=True,
                   help="Path to gazetteer JSON (see edge_relation_gazetteer.json).")
    p.add_argument("--output",    required=True,
                   help="Where to write clusters.json.")
    p.add_argument("--dim",       type=int, default=4096,
                   help="BSC dim — must match the planned encode.")
    p.add_argument("--k",         type=int, default=64,
                   help="BSC k — must match the planned encode.")
    p.add_argument("--seed",      type=int, default=42,
                   help="Codebook seed — must match the planned encode.")
    return p.parse_args()


def main():
    args = parse_args()
    with open(args.gazetteer) as f:
        gaz = json.load(f)
    relations = gaz.get("relations", {})
    fallback  = gaz.get("fallback", "mentions")
    canonical_list = list(relations.keys())
    # Include the fallback so records that emit it route somewhere.
    if fallback and fallback not in canonical_list:
        canonical_list.append(fallback)

    print(f"[clusters] gazetteer = {args.gazetteer}", flush=True)
    print(f"[clusters]   canonical relations: {len(canonical_list)}", flush=True)
    print(f"[clusters]   fallback           : {fallback!r}", flush=True)
    print(f"[clusters] codebook D={args.dim} k={args.k} seed={args.seed}",
          flush=True)

    # Build codebook
    cfg = ehc.CodebookConfig()
    cfg.dim   = int(args.dim)
    cfg.k     = int(args.k)
    cfg.seed  = int(args.seed)
    cb = ehc.TokenCodebook(cfg)
    cb.build_from_vocabulary([])

    # Per canonical relation: encode it, extract centroid indices + signs.
    cluster_data = []
    for cluster_id, rel in enumerate(canonical_list):
        sv = cb.encode_token(rel)
        idx_list  = list(sv.indices)
        sign_list = list(sv.signs)
        examples = relations.get(rel, [])[:5] if rel in relations else []
        cluster_data.append({
            "cluster_id":        cluster_id,
            "label":             rel,
            "size":              len(examples) + 1,  # +1 for canonical itself
            "examples":          [rel] + examples,
            "centroid_indices":  [int(i) for i in idx_list],
            "centroid_signs":    [int(s) for s in sign_list],
        })

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(cluster_data, f, indent=2)
    print(f"[clusters] wrote {len(cluster_data)} clusters → {out}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
