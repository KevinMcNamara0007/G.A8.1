"""
G.A8.1 — Encode Orchestrator (Two-Tier Emergent Routing, Multimodal)
=====================================================================

Core encoding engine for G.A8.1. Takes any data source and produces a
sharded holographic matrix with searchable content vectors and hidden
sidecar metadata.

PIPELINE:
  Step 0: Auto-detect source format (JSON triples or JSONL messages)
  Step 1: Build global IDF across full corpus (one pass)
  Step 2: Parallel partition into two-tier shards:
          shard_id = hash(subject) × nearest_cluster(relation)
  Step 3: Encode shards in parallel waves (multiprocessing)
          Each worker: tokenize → select top-12 salient → superpose → BSC vector
  Step 4: Collect centroids, preserve gazetteer + IDF, cleanup

INPUT FORMATS (auto-detected):
  - JSON array of triples:  [{"subject": "X", "relation": "Y", "object": "Z"}, ...]
  - JSONL messages:         {"message_text": "...", "author": {...}, "tags": [...]} per line
  - Media references:       resolved from "media_filenames" field or --media-dir

OUTPUT (per shard):
  shard_NNNN/
    index/chunk_index.npz    ← BSCCompactIndex (searchable content vectors)
    index/lsh_index.npz      ← BSCLSHIndex (candidate narrowing, 8 tables)
    index/media_index.npz    ← separate media CompactIndex (if media present)
    meta/texts.json          ← message_text_translated (sidecar)
    meta/authors.json        ← author usernames (sidecar)
    meta/channels.json       ← source channels (sidecar)
    meta/tags.json           ← tag arrays as JSON strings (sidecar)
    meta/timestamps.json     ← posted_at timestamps (sidecar)
    meta/media_paths.json    ← absolute paths to media files (sidecar)
    meta/urls.json           ← source URLs (sidecar)
    centroid.npz             ← shard centroid for routing

ENCODING STRATEGY:
  1. Tokenize ALL fields (subject + relation + object)
  2. Select top √k = 12 tokens by global IDF, with gazetteer guaranteed slots
  3. superpose(salient_tokens) → SparseVector(dim=16384, k=128)
  4. Media encoded separately via C++ VisionEncoder/VideoEncoder into parallel index
  5. Original record fields preserved in sidecar (never transformed)

CONFIGURATION (via config.env or environment variables):
  A81_DIM=16384              Vector dimensionality
  A81_K=128                  Sparsity
  A81_SEED=42                Codebook seed (deterministic)
  A81_ENTITY_BUCKETS=4       Level 1 shard routing (hash of subject)
  A81_ACTION_CLUSTERS=20     Level 2 shard routing (nearest cluster of relation)
  A81_WAVES=4                Parallel encoding waves
  A81_LSH_TABLES=8           LSH hash tables
  A81_LSH_HASH_SIZE=16       Bits per LSH hash
  A81_MAX_SALIENT_TOKENS=12  Token budget per vector

EXAMPLES:
  # Encode WikiData triples
  python3 encode.py --source triples.json --output /encoded
      --clusters clusters.json --entity-buckets 36 --waves 9

  # Encode JSONL messages with media
  python3 encode.py --source msgs.jsonl --output /encoded
      --clusters clusters.json --media-dir /path/to/media

  # Override via environment
  A81_DIM=8192 A81_K=64 python3 encode.py --source data.json
      --output /encoded --clusters clusters.json

PREREQUISITES:
  - EHC C++ library compiled (run install.sh first)
  - clusters.json from discover_clusters.py
  - Python: numpy, (optional: Pillow, opencv-python for media)
"""

import argparse
import gc
import hashlib
import json
import math
import multiprocessing as mp
import os
import pickle
import sys
import time
import numpy as np
from pathlib import Path

for _d in (2, 3, 4):
    _p = Path(__file__).resolve().parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc

STOP_WORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "is", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "may", "might",
    "can", "shall", "must", "and", "but", "or", "not", "no", "so",
    "if", "then", "than", "that", "this", "it", "its", "with", "from",
    "by", "about", "as", "into", "through", "during",
})

IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".gif"})
VIDEO_EXTS = frozenset({".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv"})


def _detect_source_type(source: str) -> str:
    """Detect whether source is JSON triples or JSONL messages."""
    if source.endswith(".jsonl"):
        return "jsonl"
    with open(source, "r") as f:
        first = f.read(1).strip()
        if first == "[":
            return "json_triples"
        if first == "{":
            return "jsonl"
    return "json_triples"


def _extract_author(author_field) -> str:
    if not author_field:
        return "unknown"
    if isinstance(author_field, str):
        return author_field.strip() or "unknown"
    for key in ("username", "name", "entity_id"):
        val = author_field.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return "unknown"


def _resolve_media(msg: dict, media_dir: str) -> tuple:
    """Resolve first valid media file. Returns (path, type) or (None, None).

    Handles both:
      - Relative filenames resolved against media_dir
      - Absolute paths (pre-resolved during JSONL combine step)
    """
    media_files = msg.get("media_filenames") or []
    if not media_files:
        return None, None
    for mf in media_files:
        if not isinstance(mf, str):
            continue
        # Check if already an absolute path
        if os.path.isabs(mf) and os.path.isfile(mf):
            ext = os.path.splitext(mf)[1].lower()
            if ext in IMAGE_EXTS:
                return mf, "image"
            if ext in VIDEO_EXTS:
                return mf, "video"
            continue
        # Relative — resolve against media_dir
        if not media_dir:
            continue
        fname = mf[6:] if mf.startswith("media/") else mf
        fpath = os.path.join(media_dir, fname)
        if os.path.isfile(fpath):
            ext = os.path.splitext(fname)[1].lower()
            if ext in IMAGE_EXTS:
                return fpath, "image"
            if ext in VIDEO_EXTS:
                return fpath, "video"
    return None, None


def _hash_entity(entity: str, n_buckets: int) -> int:
    h = hashlib.blake2b(entity.encode(), digest_size=8).digest()
    return int.from_bytes(h, "little") % n_buckets


def _nearest_cluster(action_vec, centroids_list, dim):
    """Find nearest action cluster by BSC cosine."""
    if not centroids_list or action_vec is None:
        return 0
    best_c, best_sim = 0, -1.0
    for ci, cent in enumerate(centroids_list):
        if cent is None:
            continue
        sim = ehc.sparse_cosine(action_vec, cent)
        if sim > best_sim:
            best_sim, best_c = sim, ci
    return best_c


def _partition_worker(args):
    """Partition a slice of triples into two-tier shards. Spawn-safe."""
    worker_id, slice_path, n_entity_buckets, cluster_data_raw, out_dir, dim, k = args

    t0 = time.perf_counter()

    # Build codebook (hash mode — identical across all workers)
    cfg = ehc.CodebookConfig()
    try:
        import sys as _s; _s.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from config import cfg as _c; _seed = _c.SEED
    except ImportError:
        _seed = 42
    cfg.dim = dim; cfg.k = k; cfg.seed = _seed
    cb = ehc.TokenCodebook(cfg)
    cb.build_from_vocabulary([])

    # Build centroid vectors
    centroids = []
    for cd in cluster_data_raw:
        ci = cd.get("centroid_indices", [])
        cs = cd.get("centroid_signs", [])
        if ci:
            centroids.append(ehc.SparseVector(dim,
                np.array(ci, dtype=np.int32),
                np.array(cs, dtype=np.int8)))
        else:
            centroids.append(None)

    n_clusters = max(1, len(centroids))

    # Load this worker's slice
    with open(slice_path, "rb") as f:
        triples = pickle.load(f)

    # Assign each triple to a shard
    shard_buffers = {}
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    phrase_cache = {}

    for i, t in enumerate(triples):
        s = t.get("subject", "").strip()
        r = t.get("relation", "").strip()
        o = t.get("object", "").strip()
        if not s or not o:
            continue

        entity_bucket = _hash_entity(s, n_entity_buckets)

        action_cluster = 0
        if centroids and r:
            # Use phrase cache for repeated relations
            if r in phrase_cache:
                action_cluster = phrase_cache[r]
            else:
                words = [w for w in r.replace("_", " ").lower().split()
                         if w not in STOP_WORDS and len(w) > 1]
                if words:
                    vecs = []
                    for w in words:
                        try:
                            vecs.append(cb.encode_token(w))
                        except Exception:
                            pass
                    if vecs:
                        r_vec = ehc.superpose(vecs) if len(vecs) > 1 else vecs[0]
                        action_cluster = _nearest_cluster(r_vec, centroids, dim)
                phrase_cache[r] = action_cluster

        shard_id = entity_bucket * n_clusters + action_cluster
        raw = f"{s} {r} {o}" if r else f"{s} {o}"

        if shard_id not in shard_buffers:
            shard_buffers[shard_id] = []

        chunk = {
            "text": raw, "subject": s, "relation": r,
            "object": o, "timestamp": ts,
        }
        # Pass through media metadata
        if t.get("media_path"):
            chunk["media_path"] = t["media_path"]
            chunk["media_type"] = t.get("media_type", "image")
        # Pass through original record sidecar (never transform)
        if t.get("_sidecar"):
            chunk["_sidecar"] = t["_sidecar"]
        shard_buffers[shard_id].append(chunk)

        if (i + 1) % 500000 == 0:
            ehc.clear_perm_cache()

    del triples, phrase_cache
    gc.collect()

    # Write per-shard chunk files (this worker's contribution)
    out_dir = Path(out_dir)
    counts = {}
    for shard_id, buf in shard_buffers.items():
        chunk_path = out_dir / f"chunk_{shard_id}_w{worker_id}.pkl"
        with open(chunk_path, "wb") as f:
            pickle.dump(buf, f, protocol=pickle.HIGHEST_PROTOCOL)
        counts[shard_id] = len(buf)
    del shard_buffers
    gc.collect()

    elapsed = time.perf_counter() - t0
    total = sum(counts.values())
    print(f"  [partition {worker_id}] {total:,} triples → "
          f"{len(counts)} shards in {elapsed:.1f}s")
    return counts


def _load_source_data(source: str, media_dir: str = None):
    """Load source data as list of triple dicts. Handles JSON and JSONL.

    For JSONL messages, maps:
      subject  = author username
      relation = tags/site context
      object   = message_text_translated
      media_path / media_type = resolved media file

    Returns: (data_list, n_media)
    """
    source_type = _detect_source_type(source)
    n_media = 0

    if source_type == "json_triples":
        print(f"  Source type: JSON triples")
        with open(source) as f:
            data = json.load(f)
        return data, 0

    # ── JSONL messages ─────────────────────────────────────
    print(f"  Source type: JSONL messages")

    # Auto-detect media dir
    if media_dir is None:
        parent = Path(source).parent
        for candidate in [parent / "media", parent / "data2" / "media"]:
            if candidate.is_dir():
                media_dir = str(candidate)
                print(f"  Auto-detected media dir: {media_dir}")
                break
    if media_dir:
        print(f"  Media dir: {media_dir}")

    data = []
    ts_default = time.strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(source, "r", encoding="utf-8", errors="replace") as f:
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

            author = _extract_author(msg.get("author"))
            site = msg.get("site") or msg.get("type") or ""
            tags = msg.get("filtered_tags") or msg.get("tags") or []
            ts = msg.get("posted_at") or ts_default

            # Build relation from context
            rel_parts = [site] if site else []
            if isinstance(tags, list):
                rel_parts.extend(str(t) for t in tags[:6])
            relation = " ".join(rel_parts)

            triple = {
                "subject": author,
                "relation": relation,
                "object": text[:1000],
                "timestamp": ts,
            }

            # Resolve media
            media_path, media_type = _resolve_media(msg, media_dir)
            if media_path:
                triple["media_path"] = media_path
                triple["media_type"] = media_type
                n_media += 1

            # ── SIDECAR: preserve original record fields (never transform) ─
            triple["_sidecar"] = {
                "message_text": msg.get("message_text", ""),
                "message_text_translated": text,
                "posted_at": ts,
                "author": author,
                "channel": "",
                "tags": tags if isinstance(tags, list) else [],
                "site": site,
                "url": msg.get("url", ""),
                "language": msg.get("language", ""),
                "media_path": media_path or "",
                "media_type": media_type or "",
            }
            # Extract channel from chat or author dict
            chat = msg.get("chat")
            if isinstance(chat, dict):
                triple["_sidecar"]["channel"] = (chat.get("username") or
                                                  chat.get("title") or
                                                  chat.get("entity_id") or "")
            elif site:
                triple["_sidecar"]["channel"] = site

            data.append(triple)

            if len(data) % 100000 == 0:
                print(f"    {len(data):,} messages loaded ({n_media:,} with media)...")

    print(f"  {len(data):,} messages, {n_media:,} with media")
    return data, n_media


def stream_and_partition(
    source: str,
    n_entity_buckets: int,
    cluster_data: list,
    chunks_dir: str,
    dim: int = 16384,
    k: int = 128,
    n_partition_workers: int = 9,
    media_dir: str = None,
):
    """Parallel partition: split data into N slices, assign shards in parallel,
    merge chunk files per shard.

    Each worker gets the same codebook (seed=42) and centroids.
    No coordination needed — deterministic assignment.

    Returns: (chunk_info, n_media)
    """
    chunks_dir = Path(chunks_dir)
    chunks_dir.mkdir(parents=True, exist_ok=True)

    n_clusters = max(1, len(cluster_data))
    n_shards = n_entity_buckets * n_clusters

    print(f"[A8.1] Parallel partition: {n_partition_workers} workers, "
          f"{n_entity_buckets}×{n_clusters} = {n_shards} shards")
    t0 = time.perf_counter()

    # Step 1: Load source data (JSON triples or JSONL messages)
    print(f"  Loading source...")
    data, n_media = _load_source_data(source, media_dir)
    total = len(data)

    # Step 1b: Build GLOBAL IDF across full corpus (one pass)
    print(f"  Building global IDF ({total:,} docs)...")
    from worker_encode import _tokenize
    from collections import Counter
    _doc_freq = Counter()
    for _d in data:
        _all = set(_tokenize(_d.get("subject", "")) +
                    _tokenize(_d.get("relation", "")) +
                    _tokenize(_d.get("object", "")))
        for _t in _all:
            _doc_freq[_t] += 1
    import math as _math
    global_idf = {tok: _math.log(max(total, 1) / max(df, 1))
                  for tok, df in _doc_freq.items()}
    del _doc_freq

    # Save global IDF for workers
    idf_path = chunks_dir / "_global_idf.json"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    with open(idf_path, "w") as f:
        json.dump(global_idf, f)
    print(f"  Global IDF: {len(global_idf):,} tokens")
    del global_idf
    gc.collect()

    print(f"  {total:,} records → splitting into {n_partition_workers} slices...")

    slice_size = math.ceil(total / n_partition_workers)
    slice_paths = []
    for wi in range(n_partition_workers):
        start = wi * slice_size
        end = min(start + slice_size, total)
        if start >= total:
            break
        slice_path = chunks_dir / f"_slice_{wi}.pkl"
        with open(slice_path, "wb") as f:
            pickle.dump(data[start:end], f, protocol=pickle.HIGHEST_PROTOCOL)
        slice_paths.append((wi, str(slice_path)))

    del data
    gc.collect()
    print(f"  {len(slice_paths)} slices written")

    # Step 2: Parallel partition assignment
    print(f"  Assigning shards ({n_partition_workers} workers)...")
    worker_args = [
        (wi, sp, n_entity_buckets, cluster_data, str(chunks_dir), dim, k)
        for wi, sp in slice_paths
    ]

    with mp.Pool(processes=len(worker_args)) as pool:
        all_counts = pool.map(_partition_worker, worker_args)
    gc.collect()

    # Step 3: Merge chunk files per shard (concatenate worker contributions)
    print(f"  Merging worker chunks...")
    shard_counts = {}
    for shard_id in range(n_shards):
        parts = sorted(chunks_dir.glob(f"chunk_{shard_id}_w*.pkl"))
        if not parts:
            continue
        merged = []
        for p in parts:
            with open(p, "rb") as f:
                merged.extend(pickle.load(f))
            p.unlink()  # delete worker fragment
        if merged:
            final_path = chunks_dir / f"chunk_{shard_id}.pkl"
            with open(final_path, "wb") as f:
                pickle.dump(merged, f, protocol=pickle.HIGHEST_PROTOCOL)
            shard_counts[shard_id] = len(merged)
        del merged
    gc.collect()

    # Cleanup slice files
    for wi, sp in slice_paths:
        Path(sp).unlink(missing_ok=True)

    # Build chunk_info
    chunk_info = []
    for shard_id, count in sorted(shard_counts.items()):
        path = chunks_dir / f"chunk_{shard_id}.pkl"
        if path.exists():
            chunk_info.append((shard_id, str(path), count))

    non_empty = len(chunk_info)
    elapsed = time.perf_counter() - t0
    media_tag = f" ({n_media:,} with media)" if n_media > 0 else ""
    print(f"[A8.1] {total:,} records{media_tag} → {non_empty} non-empty shards "
          f"(of {n_shards} total) in {elapsed:.1f}s")

    # Distribution stats
    sizes = [c for c in shard_counts if c > 0]
    if sizes:
        print(f"  Shard sizes: min={min(sizes):,} max={max(sizes):,} "
              f"mean={sum(sizes)//len(sizes):,} median={sorted(sizes)[len(sizes)//2]:,}")

    return chunk_info, n_media


def _flush_shard(path, buffer):
    """Append buffer to pickle file — O(buffer), not O(total)."""
    with open(Path(path), "ab") as f:
        for item in buffer:
            pickle.dump(item, f, protocol=pickle.HIGHEST_PROTOCOL)


def run_encode(
    source: str,
    output_dir: str,
    clusters_path: str,
    n_entity_buckets: int = 36,
    waves: int = 9,
    dim: int = 16384,
    k: int = 128,
    media_dir: str = None,
):
    t0 = time.perf_counter()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    chunks_dir = out / "_chunks"

    # Load clusters
    with open(clusters_path) as f:
        cluster_data = json.load(f)
    n_clusters = len(cluster_data)

    print("=" * 60)
    print("  G.A8.1 — Two-Tier Emergent Routing Encode (Multimodal)")
    print("=" * 60)
    print(f"  Source:    {source}")
    print(f"  Output:    {output_dir}")
    print(f"  Media:     {media_dir or '(auto-detect)'}")
    print(f"  Entity:    {n_entity_buckets} buckets")
    print(f"  Action:    {n_clusters} clusters")
    print(f"  Shards:    {n_entity_buckets * n_clusters} (two-tier)")
    print(f"  Waves:     {waves}")
    print(f"  D={dim}, k={k}")
    print("=" * 60)

    # Step 1: Partition
    print("\n[Step 1] Stream + two-tier partition...")
    chunk_info, n_media = stream_and_partition(
        source, n_entity_buckets, cluster_data, str(chunks_dir), dim, k,
        media_dir=media_dir)

    # Step 2: Encode in waves
    concurrency = max(1, math.ceil(len(chunk_info) / waves))
    print(f"\n[Step 2] Encoding {len(chunk_info)} shards in {waves} waves "
          f"({concurrency} concurrent)...")

    from worker_encode import worker_encode
    manifests = []

    for wave in range(waves):
        wave_start = wave * concurrency
        wave_end = min(wave_start + concurrency, len(chunk_info))
        wave_items = chunk_info[wave_start:wave_end]

        if not wave_items:
            continue

        wave_args = [
            (shard_id, chunk_path, dim, k, output_dir, cluster_data)
            for shard_id, chunk_path, n_chunks in wave_items
        ]

        print(f"\n  Wave {wave + 1}/{waves}: {len(wave_args)} shards")

        with mp.Pool(processes=min(len(wave_args), concurrency)) as pool:
            wave_manifests = pool.map(worker_encode, wave_args)
        manifests.extend(wave_manifests)
        gc.collect()

    # Step 3: Collect centroids
    print("\n[Step 3] Collecting centroids...")
    centroid_data = []
    for sd in sorted(out.glob("shard_*")):
        sid = int(sd.name.split("_")[1])
        cp = sd / "centroid.npz"
        if cp.exists():
            cd = np.load(str(cp))
            centroid_data.append({
                "shard_id": sid,
                "indices": cd["indices"].tolist(),
                "signs": cd["signs"].tolist(),
            })
    with open(out / "centroids.json", "w") as f:
        json.dump(centroid_data, f)

    # Save cluster data for query-time routing
    with open(out / "action_clusters.json", "w") as f:
        json.dump(cluster_data, f)

    # Step 4: Cleanup (preserve gazetteer + global IDF for query-time use)
    print("\n[Step 4] Cleanup...")
    import shutil
    # Move gazetteer and IDF to output root before deleting chunks
    for keep_file in ["_gazetteer.json", "_global_idf.json"]:
        src = chunks_dir / keep_file
        if Path(src).exists():
            dst = out / keep_file
            shutil.copy2(str(src), str(dst))
            print(f"  Preserved: {keep_file}")
    shutil.rmtree(str(chunks_dir), ignore_errors=True)

    # Manifest
    total_encoded = sum(m["n_encoded"] for m in manifests if m)
    total_media = sum(m.get("n_media_encoded", 0) for m in manifests if m)
    elapsed = time.perf_counter() - t0
    manifest = {
        "version": "A8.1",
        "source": source,
        "total_encoded": total_encoded,
        "total_media_encoded": total_media,
        "n_media_in_source": n_media,
        "n_entity_buckets": n_entity_buckets,
        "n_action_clusters": n_clusters,
        "n_shards_total": n_entity_buckets * n_clusters,
        "n_shards_non_empty": len(chunk_info),
        "dim": dim,
        "k": k,
        "elapsed_s": round(elapsed, 1),
        "throughput": round(total_encoded / elapsed, 1) if elapsed > 0 else 0,
        "shards": manifests,
    }
    with open(out / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print("\n" + "=" * 60)
    print(f"  DONE: {total_encoded:,} vectors in {len(chunk_info)} shards")
    if total_media > 0:
        print(f"  Media: {total_media:,} images/videos fused into vectors")
    print(f"  Time: {elapsed:.1f}s ({manifest['throughput']:,.0f}/sec)")
    print(f"  Output: {output_dir}")
    print("=" * 60)

    return manifest


def main():
    p = argparse.ArgumentParser(description="G.A8.1 Two-Tier Encode")
    p.add_argument("--source", required=True)
    p.add_argument("--output", required=True)
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from config import cfg as _c, resolve_workers as _rw
        _dim, _k = _c.DIM, _c.K
        _eb = _c.ENTITY_BUCKETS
        # 0 or unset → cap at CPU_FRACTION * cores. Explicit WAVES wins.
        _waves = _c.WAVES if _c.WAVES and _c.WAVES > 0 else _rw(0)
        _cfg = _c
    except ImportError:
        _dim, _k, _eb, _waves = 16384, 128, 36, 9
        _cfg = None
    p.add_argument("--clusters", required=True, help="Path to clusters.json")
    p.add_argument("--entity-buckets", type=int, default=_eb)
    p.add_argument("--waves", type=int, default=_waves)
    # --dim / --k are optional sentinels. None means "resolve from profile
    # or cfg". Explicit values stamp override=cli on the manifest.
    p.add_argument("--dim", type=int, default=None,
                   help="Override profile dim. Explicit value stamps override=cli.")
    p.add_argument("--k", type=int, default=None,
                   help="Override profile k. Explicit value stamps override=cli.")
    p.add_argument("--no-profile", action="store_true",
                   help="Skip profile loading — use cfg defaults. Not for prod.")
    p.add_argument("--force-profile", action="store_true",
                   help="Proceed even if profile source_hash mismatches source.")
    p.add_argument("--media-dir", type=str, default=None,
                   help="Media directory for image/video files (auto-detected if omitted)")
    args = p.parse_args()

    # ── v13.1 profile resolution ─────────────────────────────────
    #
    # State matrix from PlanC §6.2 + CLI override semantics from the
    # review. The resolved (dim, k) and a provenance string are both
    # handed to run_encode; the provenance is also exported as
    # A81_DIMENSIONS_AXIS so worker_encode.py stamps it into the
    # TierManifest without a second plumbing round-trip.
    eff_dim, eff_k, axis_value, provenance = _resolve_dk(args, _cfg)
    os.environ["A81_DIMENSIONS_AXIS"] = axis_value
    os.environ["A81_DIMENSIONS_PROVENANCE"] = provenance
    print(f"  [encode] dim={eff_dim} k={eff_k} axis={axis_value} "
          f"provenance={provenance}")

    run_encode(
        source=args.source,
        output_dir=args.output,
        clusters_path=args.clusters,
        n_entity_buckets=args.entity_buckets,
        waves=args.waves,
        dim=eff_dim,
        k=eff_k,
        media_dir=args.media_dir,
    )


def _resolve_dk(args, _cfg):
    """Apply the PlanC §6.2 state matrix.

    Returns `(dim, k, axis_value, provenance)`:
      - `axis_value`: stamped into TierManifest.components.dimensions.
      - `provenance`: one of "profile", "cli", "legacy_default".

    Aborts the process with a remediation message on mismatch cases.
    """
    profile_required = bool(_cfg.DIMENSIONS_PROFILE_REQUIRED) if _cfg else True
    legacy_sentinel = (_cfg.DIMENSIONS_LEGACY_SENTINEL
                       if _cfg else "v13.0-default")
    trivial = int(_cfg.DIMENSIONS_TRIVIAL_THRESHOLD) if _cfg else 10_000
    cfg_dim = int(_cfg.DIM) if _cfg else 16384
    cfg_k = int(_cfg.K) if _cfg else 128

    # Locate profile path. Convention: sits next to the output dir.
    profile_path = Path(args.output) / "corpus_profile.json"

    # Try to import the profile loader. Missing is fatal for prod
    # (profile_required) when corpus is large; otherwise we proceed
    # with cfg defaults and stamp the legacy sentinel.
    try:
        from decode13.profile import load_profile, compute_source_hash
    except Exception as e:
        print(f"  [encode] profile loader unavailable ({e}) — "
              f"falling back to cfg defaults", file=sys.stderr)
        load_profile = None  # type: ignore

    profile = None
    if load_profile is not None and profile_path.exists() and not args.no_profile:
        try:
            profile = load_profile(profile_path)
        except Exception as e:
            print(f"  [encode] profile at {profile_path} failed to load: {e}",
                  file=sys.stderr)
            sys.exit(3)

    # CLI overrides (partial is allowed; missing half fills from
    # profile if available, else cfg).
    cli_dim = args.dim
    cli_k = args.k
    if cli_dim is not None or cli_k is not None:
        base_dim = (profile.recommended_dim if profile else cfg_dim)
        base_k = (profile.recommended_k if profile else cfg_k)
        d = int(cli_dim) if cli_dim is not None else int(base_dim)
        k = int(cli_k) if cli_k is not None else int(base_k)
        return d, k, f"D{d}:k{k}", "cli"

    # No CLI override. Handle profile/absent cases.
    if profile is not None:
        # Check source_hash. If absent or mismatch without --force-profile, abort.
        try:
            # Not calling matches_source because we want to print the
            # mismatch detail for operators.
            from decode13.profile import compute_source_hash
            observed = compute_source_hash(str(Path(args.source).resolve()),
                                           _count_lines(args.source))
        except Exception:
            observed = None
        if observed and profile.source_hash and observed != profile.source_hash:
            if not args.force_profile:
                print(f"  [encode] profile source_hash mismatch "
                      f"(profile={profile.source_hash[:16]}… "
                      f"observed={observed[:16]}…). "
                      f"Re-run `python -m encode.profile` or pass "
                      f"--force-profile to override.", file=sys.stderr)
                sys.exit(4)
            print("  [encode] --force-profile set; ignoring source_hash mismatch.",
                  file=sys.stderr)
        d, k = int(profile.recommended_dim), int(profile.recommended_k)
        return d, k, f"D{d}:k{k}", "profile"

    # No profile, no CLI override.
    if profile_required and not args.no_profile:
        # Need to know corpus size to decide trivial vs abort.
        count = _count_lines(args.source)
        if count > trivial:
            print(f"  [encode] {count} records > trivial threshold "
                  f"({trivial}) and no profile at {profile_path}. "
                  f"Run `python -m encode.profile --source {args.source} "
                  f"--output {args.output}` first, or pass --no-profile "
                  f"to use cfg defaults (stamps legacy sentinel).",
                  file=sys.stderr)
            sys.exit(5)
    # Trivial corpus, or --no-profile: cfg defaults, legacy sentinel.
    return cfg_dim, cfg_k, legacy_sentinel, "legacy_default"


def _count_lines(source: str) -> int:
    """Fast JSONL line count. Streams bytes; no record parsing."""
    n = 0
    try:
        with open(source, "rb") as f:
            for line in f:
                if line.strip():
                    n += 1
    except Exception:
        return 0
    return n


if __name__ == "__main__":
    main()
