#!/usr/bin/env python3
"""
G.A8.1 — Edge Analyst Full Pipeline
=====================================

End-to-end encoding pipeline for the MjolnirPhotonics Edge Analyst product.
This is the reference implementation showing how to wire G.A8.1 for a
specific data source.

WHAT IT DOES:
  1. Combines multiple JSONL sources into one stream (deduplicates, resolves media paths)
  2. Discovers action clusters from the corpus (unsupervised BSC k-means)
  3. Encodes all records into a two-tier sharded holographic matrix
  4. Runs the benchmark suite

INPUT:
  - JSONL message files from edge_service/staged/ (social media, Telegram, Eitaa)
  - Media files (images/videos) referenced by the JSONL records

OUTPUT:
  - Encoded holographic matrix at OUTPUT directory:
    - 80 shards (4 entity buckets × 20 action clusters)
    - Per-shard: content index + LSH + media index + sidecar metadata
    - Global: centroids, clusters, gazetteer, IDF

ARCHITECTURE:
  Source JSONL → combine → discover clusters → two-tier partition
    → parallel encode (4 waves × 20 workers) → holographic matrix

  Each record produces:
    SEARCHABLE: superpose(top 12 salient tokens from ALL fields)
    HIDDEN:     original record fields stored in sidecar JSON arrays
    MEDIA:      separate per-shard media index (C++ VisionEncoder/VideoEncoder)

CONFIGURATION:
  All tunables read from config.env / environment variables:
    A81_DIM=16384          Vector dimensionality
    A81_K=128              Sparsity (active indices per vector)
    A81_ENTITY_BUCKETS=4   Level 1 shard routing
    A81_ACTION_CLUSTERS=20 Level 2 shard routing
    A81_WAVES=4            Parallel encoding waves

ADAPTING FOR YOUR DATA:
  To encode a different data source, copy this file and modify:
    1. STAGED — path to your source data
    2. combine_jsonl() — how to read your format and resolve media
    3. make_triples_for_clustering() — how to extract subject/relation/object
    4. save_gazetteer() — domain-specific term lists (optional)

  Everything else (cluster discovery, partition, encode, benchmark) is generic.

EXAMPLES:
  # Default: encode edge analyst staged data
  python3 encode_edge.py

  # Override output directory
  OUTPUT=/data/encoded python3 encode_edge.py

  # Override config
  A81_ENTITY_BUCKETS=8 A81_ACTION_CLUSTERS=10 python3 encode_edge.py

  # After encoding, query from Python:
  from query_service import QueryService
  svc = QueryService("/data/encoded")
  results = svc.query("iran missile test", k=10)

  # Or start the edge web interface:
  A81_INDEX_PATH=/data/encoded ./start.sh
"""

import gc
import json
import os
import shutil
import sys
import time
from pathlib import Path

# ── Load config (reads from config.env / environment) ─────────
G_A81 = str(Path(__file__).resolve().parent)
sys.path.insert(0, G_A81)
try:
    from config import cfg
    STAGED = cfg.SOURCE_PATH or "/Users/stark/Quantum_Computing_Lab/MjolnirPhotonics/product.edge.analyst.bsc/edge_service/staged"
    OUTPUT = cfg.INDEX_PATH or "/Users/stark/Quantum_Computing_Lab/OUT"
    ENTITY_BUCKETS = cfg.ENTITY_BUCKETS
    N_CLUSTERS = cfg.ACTION_CLUSTERS
    WAVES = cfg.WAVES
    DIM = cfg.DIM
    K = cfg.K
    CLUSTER_SAMPLE = cfg.CLUSTER_SAMPLE
except ImportError:
    # Fallback defaults if config.py not importable
    STAGED = "/Users/stark/Quantum_Computing_Lab/MjolnirPhotonics/product.edge.analyst.bsc/edge_service/staged"
    OUTPUT = "/Users/stark/Quantum_Computing_Lab/OUT"
    ENTITY_BUCKETS = 4
    N_CLUSTERS = 20
    WAVES = 4
    DIM = 16384
    K = 128
    CLUSTER_SAMPLE = 100000


def combine_jsonl():
    """Combine all staged JSONL files into one, resolving media paths to absolute."""
    staged = Path(STAGED)
    sources = [
        (staged / "msgs.jsonl", staged / "data2" / "media"),
        (staged / "data3" / "msgs.jsonl", staged / "data3" / "media"),
    ]

    combined_path = Path(OUTPUT) / "_combined.jsonl"
    Path(OUTPUT).mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  Step 0: Combine JSONL sources")
    print("=" * 60)

    t0 = time.perf_counter()
    n_total = 0
    n_media = 0
    seen_ids = set()

    with open(combined_path, "w", encoding="utf-8") as out:
        for jsonl_path, media_dir in sources:
            if not jsonl_path.exists():
                print(f"  SKIP: {jsonl_path}")
                continue
            count = 0
            media_dir_str = str(media_dir) if media_dir.is_dir() else None
            print(f"  Reading: {jsonl_path.name} (media: {media_dir_str or 'none'})")

            with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Dedup
                    msg_id = msg.get("id") or msg.get("native_id")
                    if msg_id in seen_ids:
                        continue
                    seen_ids.add(msg_id)

                    # Resolve media paths to absolute
                    media_files = msg.get("media_filenames") or []
                    if media_dir_str and media_files:
                        resolved = []
                        for mf in media_files:
                            if isinstance(mf, str):
                                fname = mf[6:] if mf.startswith("media/") else mf
                                fpath = os.path.join(media_dir_str, fname)
                                if os.path.isfile(fpath):
                                    resolved.append(fpath)
                                    n_media += 1
                        if resolved:
                            # Overwrite with absolute paths
                            msg["media_filenames"] = resolved

                    out.write(json.dumps(msg, ensure_ascii=False) + "\n")
                    count += 1
            print(f"    {count:,} messages")
            n_total += count

    elapsed = time.perf_counter() - t0
    print(f"  Combined: {n_total:,} messages, {n_media:,} media refs, {elapsed:.1f}s")
    return str(combined_path), n_total, n_media


def make_triples_for_clustering(combined_path):
    """Convert JSONL to JSON triples for cluster discovery (samples only relations)."""
    print("\n  Converting to triples for cluster discovery...")
    triples = []
    with open(combined_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            text = (msg.get("message_text_translated") or
                    msg.get("message_text") or "").strip()
            if not text or len(text) < 10:
                continue

            author = msg.get("author")
            if isinstance(author, dict):
                author = (author.get("username") or author.get("name")
                          or author.get("entity_id") or "unknown")
            author = str(author or "unknown").strip()

            site = msg.get("site") or msg.get("type") or ""
            tags = msg.get("filtered_tags") or msg.get("tags") or []
            rel_parts = [site] if site else []
            if isinstance(tags, list):
                rel_parts.extend(str(t) for t in tags[:6])
            relation = " ".join(rel_parts)

            triples.append({
                "subject": author,
                "relation": relation,
                "object": text[:500],
            })

    triples_path = Path(OUTPUT) / "_triples_for_clusters.json"
    with open(triples_path, "w") as f:
        json.dump(triples, f)
    print(f"  {len(triples):,} triples written")
    del triples
    gc.collect()
    return str(triples_path)


def run_discover_clusters(triples_path):
    """Run cluster discovery on the triples."""
    clusters_path = os.path.join(OUTPUT, "clusters.json")

    sys.path.insert(0, os.path.join(G_A81, "encode"))
    from discover_clusters import extract_actions, encode_actions, cluster_actions
    import math

    print("\n" + "=" * 60)
    print("  Step 1: Discover Action Clusters")
    print("=" * 60)
    t0 = time.perf_counter()

    k = int(math.sqrt(DIM))
    actions = extract_actions(triples_path, CLUSTER_SAMPLE, seed=42)
    print(f"  Raw actions: {len(actions):,}")

    unique = list(dict.fromkeys(actions))
    print(f"  Unique: {len(unique):,}")

    print(f"  Encoding as BSC vectors...")
    idx_mat, sgn_mat = encode_actions(unique, DIM, k)

    print(f"  Clustering into {N_CLUSTERS} groups...")
    clusters = cluster_actions(unique, idx_mat, sgn_mat,
                               n_clusters=N_CLUSTERS, dim=DIM, k=k)

    with open(clusters_path, "w") as f:
        json.dump(clusters, f, indent=2)

    elapsed = time.perf_counter() - t0
    print(f"  {len(clusters)} clusters in {elapsed:.1f}s")
    for c in clusters[:10]:
        print(f"    [{c['cluster_id']:3d}] {c['label']:35s} ({c['size']:,})")

    del idx_mat, sgn_mat, actions, unique
    gc.collect()
    return clusters_path


def save_gazetteer():
    """Save edge domain gazetteer for workers to load during encoding."""
    sys.path.insert(0, os.path.join(G_A81, "encode"))
    from resolvers.edge_gazetteer import load_edge_gazetteer

    gaz = load_edge_gazetteer()
    # Workers look for _gazetteer.json in _chunks dir
    chunks_dir = os.path.join(OUTPUT, "_chunks")
    os.makedirs(chunks_dir, exist_ok=True)
    gaz_path = os.path.join(chunks_dir, "_gazetteer.json")
    with open(gaz_path, "w") as f:
        json.dump(list(gaz), f)
    print(f"  Gazetteer: {len(gaz)} domain terms saved")


def run_encode(combined_path):
    """Run the G.A8.1 two-tier encode."""
    sys.path.insert(0, os.path.join(G_A81, "encode"))

    from encode import run_encode as a81_encode

    clusters_path = os.path.join(OUTPUT, "clusters.json")

    print("\n" + "=" * 60)
    print("  Step 2: Two-Tier Encode (Multimodal)")
    print("=" * 60)

    manifest = a81_encode(
        source=combined_path,
        output_dir=OUTPUT,
        clusters_path=clusters_path,
        n_entity_buckets=ENTITY_BUCKETS,
        waves=WAVES,
        dim=DIM,
        k=K,
        media_dir=None,  # Already resolved to absolute paths in combine step
    )
    return manifest


def run_benchmark():
    """Run benchmark against encoded output."""
    sys.path.insert(0, os.path.join(G_A81, "decode"))

    from benchmark import sample_queries, run_benchmark as a81_benchmark
    from benchmark import load_index, _load_lsh_from_npz
    import math

    print("\n" + "=" * 60)
    print("  Step 3: Benchmark")
    print("=" * 60)

    import ehc

    run_dir = Path(OUTPUT)
    dim = DIM

    # Load centroids
    with open(run_dir / "centroids.json") as f:
        centroids_raw = json.load(f)
    centroids = []
    for cd in centroids_raw:
        cd["_vec"] = ehc.SparseVector(
            dim,
            [int(x) for x in cd["indices"]],
            [int(x) for x in cd["signs"]],
        )
        centroids.append(cd)
    print(f"  Centroids: {len(centroids)}")

    # Shared codebook
    cfg = ehc.CodebookConfig()
    cfg.dim = dim
    cfg.k = int(math.sqrt(dim))
    cfg.seed = 42
    shared_cb = ehc.TokenCodebook(cfg)
    shared_cb.build_from_vocabulary([])

    # Sample and run
    queries = sample_queries(str(run_dir), 500, seed=42)
    scorecard = a81_benchmark(
        queries, str(run_dir), centroids, shared_cb,
        top_k=10, final_k=5, dim=dim,
        n_entity_buckets=ENTITY_BUCKETS, n_action_clusters=N_CLUSTERS,
    )

    out_path = run_dir / "edge_scorecard.json"
    with open(out_path, "w") as f:
        json.dump(scorecard, f, indent=2)
    print(f"  Scorecard: {out_path}")
    return scorecard


def main():
    t0_global = time.perf_counter()

    # Clean previous output (preserve clusters if re-running)
    if os.path.isdir(OUTPUT):
        print(f"  Cleaning previous output: {OUTPUT}")
        shutil.rmtree(OUTPUT, ignore_errors=True)

    # Step 0: Combine JSONL sources
    combined_path, n_total, n_media_refs = combine_jsonl()

    # Step 1: Discover clusters
    triples_path = make_triples_for_clustering(combined_path)
    clusters_path = run_discover_clusters(triples_path)

    # Cleanup temp triples (keep combined JSONL for encode)
    os.remove(triples_path)

    # Step 1b: Save gazetteer for workers
    save_gazetteer()

    # Step 2: Encode
    manifest = run_encode(combined_path)

    # Cleanup combined JSONL
    os.remove(combined_path)

    # Step 3: Benchmark
    scorecard = run_benchmark()

    # ── Final Report ───────────────────────────────────────────
    elapsed_total = time.perf_counter() - t0_global
    total_media_encoded = manifest.get("total_media_encoded", 0)

    print("\n" + "=" * 60)
    print("  EDGE ANALYST ENCODE — FINAL METRICS")
    print("=" * 60)
    print(f"  Items Encoded:     {manifest['total_encoded']:,}")
    print(f"  Media Fused:       {total_media_encoded:,} images/videos")
    print(f"  Cardinality:       {n_total:,} unique messages")
    print(f"  Shards:            {manifest['n_shards_non_empty']} "
          f"(of {manifest['n_shards_total']} two-tier slots)")
    print(f"  Encode Speed:      {manifest['throughput']:,.0f} vectors/sec")
    print(f"  Encode Time:       {manifest['elapsed_s']:.1f}s")
    print(f"  Recall (Hit@1):    {scorecard['hit_at_1_pct']:.1f}%")
    print(f"  Recall (Hit@5):    {scorecard['hit_at_5_pct']:.1f}%")
    print(f"  Latency p50:       {scorecard['latency_p50_ms']:.2f} ms")
    print(f"  Latency p95:       {scorecard['latency_p95_ms']:.2f} ms")
    print(f"  Total Pipeline:    {elapsed_total:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
