"""
G.A8.1 -- Encode Orchestrator (Two-Tier Emergent Routing, Multimodal)
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
from urllib.parse import unquote as _url_unquote
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

# Author values that are platform/site names rather than unique entities.
# When a record's author matches one of these, the subject is derived from
# the URL instead -- see BUG-007 fix in _iter_source_data.
_GENERIC_AUTHOR_NAMES = frozenset({
    "wikipedia", "wikimedia", "wikidata",
    "reddit", "twitter", "x", "facebook", "instagram", "youtube",
    "medium", "substack", "quora", "stackoverflow",
    "unknown",
})


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
        # Relative -- resolve against media_dir
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

    # Build codebook (hash mode -- identical across all workers)
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


def _iter_source_data(source: str, media_dir: str = None):
    """Generator: yield one triple dict at a time from JSON or JSONL source.
    Never builds the full list in memory -- safe for multi-million-record corpora.
    """
    source_type = _detect_source_type(source)

    if source_type == "json_triples":
        with open(source) as f:
            for triple in json.load(f):
                yield triple, False
        return

    if media_dir is None:
        parent = Path(source).parent
        for candidate in [parent / "media", parent / "data2" / "media"]:
            if candidate.is_dir():
                media_dir = str(candidate)
                break

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
            site   = msg.get("site") or msg.get("type") or ""
            tags   = msg.get("filtered_tags") or msg.get("tags") or []
            ts     = msg.get("posted_at") or ts_default

            # ── BUG-007 FIX: Wikipedia (and similar platform sources) set
            # author to a single constant string for ALL records (e.g. "Wikipedia").
            # hash("Wikipedia") % 32 = 30, so 100% of records land in entity_bucket 30
            # (shards 1200--1239), leaving 1240/1280 shards empty and defeating the
            # two-tier routing entirely.
            # Fix: when the author field is a known content-platform name, derive the
            # subject from the URL instead (e.g. URL title for Wikipedia articles).
            # This restores uniform distribution across all 32 entity buckets.
            # PR: YES -- submit to KevinMcNamara0007/G.A8.1
            url = msg.get("url", "")
            if url and author.lower() in _GENERIC_AUTHOR_NAMES:
                try:
                    # Extract path after the last meaningful segment (/wiki/, /p/, etc.)
                    for _seg in ("/wiki/", "/article/", "/entry/", "/p/", "/post/"):
                        if _seg in url:
                            _title = _url_unquote(url.split(_seg, 1)[-1]
                                                  .split("?")[0]
                                                  .split("#")[0]
                                                  .replace("_", " ")).strip()
                            if _title:
                                author = _title
                                break
                    else:
                        # Fallback: last URL path component
                        _last = _url_unquote(url.rstrip("/").rsplit("/", 1)[-1]
                                             .split("?")[0]
                                             .replace("_", " ")).strip()
                        if _last and len(_last) > 2:
                            author = _last
                except Exception:
                    pass

            rel_parts = [site] if site else []
            if isinstance(tags, list):
                rel_parts.extend(str(t) for t in tags[:6])
            relation = " ".join(rel_parts)

            triple = {
                "subject":   author,
                "relation":  relation,
                "object":    text[:1000],
                "timestamp": ts,
            }

            media_path, media_type = _resolve_media(msg, media_dir)
            has_media = bool(media_path)
            if has_media:
                triple["media_path"] = media_path
                triple["media_type"] = media_type

            triple["_sidecar"] = {
                "message_text":             msg.get("message_text", ""),
                "message_text_translated":  text,
                "posted_at":                ts,
                "author":                   author,
                "channel":                  "",
                "tags":   tags if isinstance(tags, list) else [],
                "site":   site,
                "url":    msg.get("url", ""),
                "language":   msg.get("language", ""),
                "media_path": media_path or "",
                "media_type": media_type or "",
            }
            chat = msg.get("chat")
            if isinstance(chat, dict):
                triple["_sidecar"]["channel"] = (chat.get("username") or
                                                  chat.get("title") or
                                                  chat.get("entity_id") or "")
            elif site:
                triple["_sidecar"]["channel"] = site

            yield triple, has_media


def _load_source_data(source: str, media_dir: str = None):
    """Load source data as list of triple dicts. Handles JSON and JSONL.
    NOTE: builds full list in memory -- use _iter_source_data for large corpora.

    ── BUG-001 NOTE ─────────────────────────────────────────────────────────
    This function is the ROOT CAUSE of BUG-001 (OOM on large datasets).
    The original stream_and_partition() called this function, loading ALL
    records into a single Python list before any partitioning occurred.

    Symptom:   OOM-kill when encoding 6.28M Wikipedia records (~20–30 GB RSS).
    Reproduce: Call stream_and_partition() on any source >2M records on a
               machine with <32 GB RAM. The process will be killed by the
               kernel OOM killer mid-run (no error, just disappears).
    Root cause: Python list of 6.28M dicts with string fields ≈ 5 KB each
               = ~30 GB allocated before a single shard is written.

    Fix: stream_and_partition() now uses _iter_source_data() (a generator)
    in two passes -- never holding more than one slice buffer in RAM.
    This function is retained for small datasets and backwards compatibility.
    DO NOT use it for corpora larger than ~500K records.
    ─────────────────────────────────────────────────────────────────────────

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
    n_partition_workers: int = None,   # None → auto from cpu_count
    media_dir: str = None,
):
    """Parallel partition: split data into N slices, assign shards in parallel,
    merge chunk files per shard.

    Each worker gets the same codebook (seed=42) and centroids.
    No coordination needed -- deterministic assignment.

    Returns: (chunk_info, n_media)
    """
    chunks_dir = Path(chunks_dir)
    chunks_dir.mkdir(parents=True, exist_ok=True)

    # ── BUG-002 FIX: auto-derive partition worker count ───────────────────────
    # Original code:  n_partition_workers was a required positional arg,
    #                 hardcoded to 9 in the caller (run_encode).
    # Symptom:        9 workers on a 4-core machine = 9 Python processes
    #                 competing for 4 cores. Partition phase took 3–4 hours
    #                 instead of ~30 min. High ctx-switch overhead, all workers
    #                 slower by 2–3×.
    # Reproduce:      Call stream_and_partition(..., n_partition_workers=9) on
    #                 a 4-core machine and observe htop -- all 9 processes fight
    #                 for 4 cores with near-100% each. Elapsed >>2h.
    # Root cause:     Hardcoded 9 workers inherited from a 9-core dev machine.
    #                 No guard against over-subscription on smaller hosts.
    # Fix:            Default is now None → auto-derive as cpu_count()-1.
    #                 If caller passes a value it is clamped to cpu_cap.
    # PR:             pending submission to KevinMcNamara0007/G.A8.1
    # ─────────────────────────────────────────────────────────────────────────
    _cpu_cap = max(1, (os.cpu_count() or 4) - 1)
    if n_partition_workers is None:
        n_partition_workers = _cpu_cap
    else:
        n_partition_workers = min(n_partition_workers, _cpu_cap)

    n_clusters = max(1, len(cluster_data))
    n_shards = n_entity_buckets * n_clusters

    print(f"[A8.1] Parallel partition: {n_partition_workers} workers (cpu_cap={_cpu_cap}), "
          f"{n_entity_buckets}×{n_clusters} = {n_shards} shards")
    t0 = time.perf_counter()

    # ── BUG-001 FIX: streaming two-pass partition (replaces _load_source_data) ─
    # Original code:  data, n_media = _load_source_data(source, media_dir)
    #                 followed by sequential partition of the full list.
    # Symptom:        6.28M Wikipedia records → ~30 GB RAM allocated in one shot
    #                 → OOM kill before any shard was written. No error output,
    #                 process simply vanished from ps.
    # Reproduce:      Replace the two-pass block below with:
    #                   data, n_media = _load_source_data(source, media_dir)
    #                 and run on any source >2M records on a machine with <32 GB RAM.
    # Root cause:     Python list of N dicts with full string fields. At N=6.28M
    #                 and ~5 KB/record average, peak = 6.28M × 5000 = ~30 GB.
    # Fix:            Two-pass streaming using _iter_source_data() generator:
    #                   Pass 1 -- count records + build global IDF (~200 MB peak,
    #                            just a Counter over tokens, not the full text)
    #                   Pass 2 -- re-stream and write MAX_SLICE_RECORDS-capped
    #                            slice pickle files incrementally
    #                 Peak RAM ≈ one slice buffer = 100K records × 5 KB = ~500 MB.
    # PR:             pending submission to KevinMcNamara0007/G.A8.1
    # ─────────────────────────────────────────────────────────────────────────

    # Pass 1: stream source to build global IDF + count total records.
    # Never loads the full corpus into memory.
    print(f"  Pass 1: counting records + building global IDF...")
    from worker_encode import _tokenize
    from collections import Counter
    import math as _math
    _doc_freq = Counter()
    total   = 0
    n_media = 0

    for triple, has_media in _iter_source_data(source, media_dir):
        total += 1
        if has_media:
            n_media += 1
        _all = set(_tokenize(triple.get("subject",   "")) +
                   _tokenize(triple.get("relation",  "")) +
                   _tokenize(triple.get("object",    "")))
        for _t in _all:
            _doc_freq[_t] += 1
        if total % 500_000 == 0:
            print(f"    {total:,} records scanned...")

    # ── BUG-006 FIX: filter singleton tokens from IDF ────────────────────────────
    # Issue:   Kevin's original code keeps ALL tokens regardless of document frequency.
    #          On 5M Wikipedia records this produces 13.8M unique tokens, 68% of which
    #          are singletons (df=1). Each worker independently JSON-parses the 472 MB
    #          IDF file into ~1.9 GB of Python dict objects. With 3 concurrent workers:
    #          3 x 1.9 GB = 5.7 GB just for IDF → OOM.
    # Symptom: RSS watchdog kills encode during Wave 1 on datasets >= 5M records.
    #          1M records succeeded; 5M OOM'd at 11.88 GB / 11.81 GB budget.
    # Root cause: Singleton tokens (df=1) have the maximum IDF score (log(N)) and are
    #          selected as "salient" for exactly one document. They contribute nothing
    #          to retrieval quality (no other document can match on them) while doubling
    #          or tripling the IDF table size.
    # Fix:     MIN_DF=2 filter before writing IDF. Reduces 13.8M → 4.4M tokens (-68%)
    #          on 5M records. Tokens with df>=2 retain full IDF discrimination.
    #          Singletons fall back to idf.get(t, 0.0) = 0.0 in _select_salient,
    #          meaning they are deprioritised (other tokens with df>=2 rank higher).
    # PR:      YES -- submit to KevinMcNamara0007/G.A8.1
    # ─────────────────────────────────────────────────────────────────────────────
    MIN_DF = 2
    global_idf = {tok: _math.log(max(total, 1) / max(df, 1))
                  for tok, df in _doc_freq.items()
                  if df >= MIN_DF}
    del _doc_freq

    idf_path = chunks_dir / "_global_idf.json"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    with open(idf_path, "w") as f:
        json.dump(global_idf, f)
    n_idf = len(global_idf)
    print(f"  Global IDF: {n_idf:,} tokens (min_df={MIN_DF}, {total:,} records total)")
    del global_idf
    gc.collect()

    # Pass 2: stream source again, writing records directly into slice pickle files.
    # Slice files are flushed incrementally -- peak RAM = one slice buffer at a time.

    # ── BUG-004 FIX: cap slice buffer size ───────────────────────────────────
    # Original code:  n_slices = n_partition_workers (e.g. 3 workers → 3 slices).
    #                 Each slice = ceil(6.28M / 3) = 2.1M records.
    # Symptom:        At ~5 KB/record each slice buffer consumed ~10 GB RAM
    #                 before being written to disk → OOM kill.
    # Reproduce:      Set n_partition_workers=3 and run on 6.28M records.
    #                 RSS will spike to ~30 GB (3 slices × 10 GB each).
    # Root cause:     Slice count was tied to worker count, not to record count.
    #                 A small worker count → very large slices.
    # Fix:            MAX_SLICE_RECORDS=100_000 hard cap. n_slices derived
    #                 independently: max(n_workers, ceil(total / 100K)).
    #                 Guarantees each slice buffer ≤ ~500 MB (100K × 5 KB).
    #                 n_slices grows with corpus size, not with worker count.
    # PR:             pending submission to KevinMcNamara0007/G.A8.1
    # ─────────────────────────────────────────────────────────────────────────
    MAX_SLICE_RECORDS = 100_000
    n_slices     = max(n_partition_workers, math.ceil(total / MAX_SLICE_RECORDS))
    slice_size   = math.ceil(total / n_slices)
    print(f"  Pass 2: writing {n_slices} slice files (~{slice_size:,} records each)...")
    slice_paths  = []
    wi           = 0
    buf          = []
    written      = 0
    slice_path   = chunks_dir / f"_slice_{wi}.pkl"

    for triple, _ in _iter_source_data(source, media_dir):
        buf.append(triple)
        written += 1
        if len(buf) >= slice_size:
            with open(slice_path, "wb") as f:
                pickle.dump(buf, f, protocol=pickle.HIGHEST_PROTOCOL)
            slice_paths.append((wi, str(slice_path)))
            wi        += 1
            buf        = []
            slice_path = chunks_dir / f"_slice_{wi}.pkl"

    if buf:  # flush final partial slice
        with open(slice_path, "wb") as f:
            pickle.dump(buf, f, protocol=pickle.HIGHEST_PROTOCOL)
        slice_paths.append((wi, str(slice_path)))
        buf = []

    gc.collect()
    print(f"  {len(slice_paths)} slices written ({written:,} records)")

    # Step 2: Parallel partition assignment
    print(f"  Assigning shards ({n_partition_workers} workers)...")
    worker_args = [
        (wi, sp, n_entity_buckets, cluster_data, str(chunks_dir), dim, k)
        for wi, sp in slice_paths
    ]

    # ── BUG-005 FIX: decouple pool size from slice count ─────────────────────
    # Original code:  mp.Pool(processes=len(worker_args))
    # Symptom:        After BUG-004 fix raised n_slices to 63 (for 6.28M recs),
    #                 Pool spawned 63 worker processes × ~600 MB each = ~38 GB
    #                 → immediate OOM kill.
    # Reproduce:      Apply BUG-004 fix without this fix. Run on 6.28M records.
    #                 len(worker_args) will be 63. Pool spawns 63 processes.
    # Root cause:     Pool size was `len(worker_args)`, which grew with n_slices
    #                 after the BUG-004 fix decoupled slice count from worker count.
    # Fix:            Pool size = n_partition_workers (cpu_cap), independent of
    #                 how many slices were written. Pool processes slices in
    #                 batches via map(), not all at once.
    # PR:             pending submission to KevinMcNamara0007/G.A8.1
    # ─────────────────────────────────────────────────────────────────────────
    with mp.Pool(processes=n_partition_workers) as pool:
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
    """Append buffer to pickle file -- O(buffer), not O(total)."""
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
    print("  G.A8.1 -- Two-Tier Emergent Routing Encode (Multimodal)")
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
    # ── BUG-003 FIX: auto-derive wave count after partitioning ────────────────
    # Original code:  `waves` was a required CLI argument passed into run_encode().
    #                 Correct value depends on actual non-empty shard count and
    #                 cpu_cap -- both only known *after* partitioning completes.
    # Symptom (over-parallelised): waves=1 on 6.28M run → 40 concurrent workers
    #                 × 600 MB = 24 GB → OOM. Or waves too low → too many
    #                 concurrent workers fighting for RAM.
    # Symptom (under-parallelised): waves=200 → 1 worker active at a time,
    #                 encode takes 3× longer than necessary.
    # Reproduce:      Pass --waves 1 to a run with 40 non-empty shards on a
    #                 4-core machine. All 40 shards start concurrently → OOM.
    # Root cause:     Caller cannot know the correct waves value before the
    #                 partition step reveals actual shard count. Circular dependency.
    # Fix:            waves is now computed here from len(chunk_info) / cpu_cap.
    #                 --waves CLI arg is kept for backwards-compat but silently
    #                 overridden. cpu_cap = cpu_count()-1 leaves one core for OS.
    # PR:             pending submission to KevinMcNamara0007/G.A8.1
    # ─────────────────────────────────────────────────────────────────────────
    _cpu_cap   = max(1, (os.cpu_count() or 4) - 1)
    concurrency = _cpu_cap
    waves       = max(1, math.ceil(len(chunk_info) / concurrency))
    print(f"\n[Step 2] Encoding {len(chunk_info)} shards in {waves} waves "
          f"({concurrency} concurrent, cpu_cap={_cpu_cap})...")

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
        from config import cfg as _c
        _dim, _k = _c.DIM, _c.K
        _eb, _waves = _c.ENTITY_BUCKETS, _c.WAVES
    except ImportError:
        _dim, _k, _eb, _waves = 16384, 128, 36, 9
    p.add_argument("--clusters", required=True, help="Path to clusters.json")
    p.add_argument("--entity-buckets", type=int, default=_eb)
    p.add_argument("--waves", type=int, default=_waves)
    p.add_argument("--dim", type=int, default=_dim)
    p.add_argument("--k", type=int, default=_k)
    p.add_argument("--media-dir", type=str, default=None,
                   help="Media directory for image/video files (auto-detected if omitted)")
    args = p.parse_args()

    run_encode(
        source=args.source,
        output_dir=args.output,
        clusters_path=args.clusters,
        n_entity_buckets=args.entity_buckets,
        waves=args.waves,
        dim=args.dim,
        k=args.k,
        media_dir=args.media_dir,
    )


if __name__ == "__main__":
    main()
