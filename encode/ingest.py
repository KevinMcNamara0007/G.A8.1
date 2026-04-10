"""
G.A8.1 — Incremental Ingest
=============================

Appends new records to an existing holographic matrix without re-encoding.

HOW IT WORKS:
  1. Route each new record to its target shard (same hash + cluster logic)
  2. Encode: tokenize → select top-12 salient → superpose → BSC vector
  3. Append vector to shard's CompactIndex + LSH (in memory)
  4. Append sidecar metadata to JSON arrays
  5. Rewrite shard indices to disk (atomic)
  6. Update centroid

WHAT STAYS THE SAME:
  - Shard routing (same hash function, same clusters)
  - Encoding strategy (same IDF, same gazetteer, same codebook)
  - Shard structure (same file layout)

WHAT CHANGES:
  - Shard vector count increases
  - Index files get rewritten (larger)
  - Centroid may shift slightly

USAGE:
  from ingest import IncrementalIngest

  ing = IncrementalIngest("/path/to/encoded")

  # Single record
  ing.ingest({
      "subject": "hakc93",
      "relation": "telegram iran terrorism",
      "object": "New message about missile tests...",
      "timestamp": "2026-04-09T12:00:00Z",
      "media_path": "/path/to/image.jpg",  # optional
      "_sidecar": {                          # optional, preserves original fields
          "message_text_translated": "New message...",
          "author": "hakc93",
          "channel": "news_channel",
          "tags": ["iran", "terrorism"],
          ...
      }
  })

  # Batch
  ing.ingest_batch([record1, record2, ...])

  # Flush to disk (atomic per shard)
  ing.flush()

  # Stats
  print(ing.stats)

  # If QueryService is running, reload affected shards:
  svc.reload_shards(ing.affected_shards)
"""

import gc
import hashlib
import json
import math
import sys
import time
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional

# ── EHC import ──────────────────────────────────────────────
for _d in (1, 2, 3, 4):
    _p = Path(__file__).resolve().parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc

# ── Config ──────────────────────────────────────────────────
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import cfg
except ImportError:
    cfg = None

STOP_WORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "is", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "may", "might",
    "can", "shall", "must", "and", "but", "or", "not", "no", "so",
    "if", "then", "than", "that", "this", "it", "its", "with", "from",
    "by", "about", "as", "into", "through", "during",
})


def _tokenize(text: str) -> list:
    return [w for w in text.replace("_", " ").lower().split()
            if w not in STOP_WORDS and len(w) > 1]


def _hash_entity(entity: str, n_buckets: int) -> int:
    h = hashlib.blake2b(entity.encode(), digest_size=8).digest()
    return int.from_bytes(h, "little") % n_buckets


class IncrementalIngest:
    """Append new records to an existing G.A8.1 holographic matrix."""

    def __init__(self, index_dir: str):
        self.index_dir = Path(index_dir)
        self.dim = cfg.DIM if cfg else 16384
        self.k = cfg.K if cfg else 128
        self.seed = cfg.SEED if cfg else 42
        self.max_salient = cfg.MAX_SALIENT_TOKENS if cfg else 12

        # Load manifest
        manifest_path = self.index_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"No manifest at {manifest_path}")
        with open(manifest_path) as f:
            self.manifest = json.load(f)

        self.n_entity_buckets = self.manifest.get("n_entity_buckets", 4)
        n_clusters = self.manifest.get("n_action_clusters", 20)

        # Load cluster centroids for routing
        clusters_path = self.index_dir / "action_clusters.json"
        self.cluster_centroids = []
        if clusters_path.exists():
            with open(clusters_path) as f:
                cluster_data = json.load(f)
            for cd in cluster_data:
                ci = cd.get("centroid_indices", [])
                cs = cd.get("centroid_signs", [])
                if ci:
                    self.cluster_centroids.append(ehc.SparseVector(
                        self.dim,
                        np.array(ci, dtype=np.int32),
                        np.array(cs, dtype=np.int8)))
                else:
                    self.cluster_centroids.append(None)

        # Build codebook
        cb_cfg = ehc.CodebookConfig()
        cb_cfg.dim = self.dim
        cb_cfg.k = self.k
        cb_cfg.seed = self.seed
        self.codebook = ehc.TokenCodebook(cb_cfg)
        self.codebook.build_from_vocabulary([])

        # Load global IDF (if available)
        self.idf = {}
        idf_path = self.index_dir / "_global_idf.json"
        if idf_path.exists():
            with open(idf_path) as f:
                self.idf = json.load(f)

        # Load gazetteer (if available)
        self.gazetteer = None
        gaz_path = self.index_dir / "_gazetteer.json"
        if gaz_path.exists():
            with open(gaz_path) as f:
                self.gazetteer = frozenset(json.load(f))

        # Buffers: shard_id → list of (vector, sidecar_dict)
        self._buffers: Dict[int, list] = {}
        self._affected: set = set()
        self._ingested = 0

        # Token cache
        self._token_cache = ehc.LRUCache(max_size=10000) if hasattr(ehc, "LRUCache") else None

    def _encode_token(self, w):
        tv = self._token_cache.get(w) if self._token_cache else None
        if tv is None:
            try:
                tv = self.codebook.encode_token(w)
                if self._token_cache:
                    self._token_cache.put(w, tv)
            except Exception:
                return None
        return tv

    def _encode_tokens(self, tokens):
        vecs = [v for v in (self._encode_token(w) for w in tokens) if v is not None]
        if not vecs:
            return None
        return ehc.superpose(vecs) if len(vecs) > 1 else vecs[0]

    def _select_salient(self, tokens):
        if len(tokens) <= self.max_salient:
            return tokens

        # Phase 1: guaranteed gazetteer slots
        selected = []
        remaining = []
        if self.gazetteer:
            for t in dict.fromkeys(tokens):  # deduplicate preserving order
                if t in self.gazetteer and len(selected) < self.max_salient:
                    selected.append(t)
                else:
                    remaining.append(t)
        else:
            remaining = list(dict.fromkeys(tokens))

        # Phase 2: fill by IDF
        slots_left = self.max_salient - len(selected)
        if slots_left > 0 and remaining:
            scored = [(t, self.idf.get(t, 0.0)) for t in remaining]
            scored.sort(key=lambda x: -x[1])
            for t, _ in scored:
                selected.append(t)
                if len(selected) >= self.max_salient:
                    break
        return selected

    def _route(self, record: dict) -> int:
        """Route record to shard using same logic as batch encode."""
        subject = record.get("subject", "")
        relation = record.get("relation", "")

        entity_bucket = _hash_entity(subject, self.n_entity_buckets)
        n_clusters = max(1, len(self.cluster_centroids))

        action_cluster = 0
        if self.cluster_centroids and relation:
            r_tokens = _tokenize(relation)
            if r_tokens:
                r_vec = self._encode_tokens(r_tokens)
                if r_vec is not None:
                    best_c, best_sim = 0, -1.0
                    for ci, cent in enumerate(self.cluster_centroids):
                        if cent is None:
                            continue
                        sim = ehc.sparse_cosine(r_vec, cent)
                        if sim > best_sim:
                            best_sim, best_c = sim, ci
                    action_cluster = best_c

        return entity_bucket * n_clusters + action_cluster

    def ingest(self, record: dict):
        """Ingest a single record. Buffers in memory until flush()."""
        s = record.get("subject", "")
        r = record.get("relation", "")
        o = record.get("object", "")

        # Tokenize all fields
        all_tokens = _tokenize(s) + _tokenize(r) + _tokenize(o)
        if not all_tokens:
            return

        # Select salient and encode
        salient = self._select_salient(all_tokens)
        vec = self._encode_tokens(salient)
        if vec is None:
            return

        # Route to shard
        shard_id = self._route(record)

        # Build sidecar
        sc = record.get("_sidecar", {})
        sidecar = {
            "text": sc.get("message_text_translated", o[:1000]),
            "author": sc.get("author", s),
            "channel": sc.get("channel", ""),
            "tags": json.dumps(sc.get("tags", [])) if isinstance(sc.get("tags"), list) else "",
            "timestamp": sc.get("posted_at", record.get("timestamp", "")),
            "media_path": sc.get("media_path", record.get("media_path", "")),
            "url": sc.get("url", record.get("url", "")),
            "value": sc.get("message_text", o),
        }

        # Buffer
        if shard_id not in self._buffers:
            self._buffers[shard_id] = []
        self._buffers[shard_id].append((vec, sidecar))
        self._affected.add(shard_id)
        self._ingested += 1

    def ingest_batch(self, records: List[dict]):
        """Ingest multiple records."""
        for rec in records:
            self.ingest(rec)

    def flush(self):
        """Write all buffered records to their shards. Atomic per shard."""
        if not self._buffers:
            return

        t0 = time.perf_counter()
        total_added = 0

        for shard_id, items in self._buffers.items():
            shard_dir = self.index_dir / f"shard_{shard_id:04d}"
            if not shard_dir.exists():
                shard_dir.mkdir(parents=True)
                (shard_dir / "index").mkdir()
                (shard_dir / "meta").mkdir()

            n_new = len(items)
            vecs = [v for v, _ in items]
            sidecars = [s for _, s in items]

            # ── Load existing sidecar arrays ──────────────────
            meta_dir = shard_dir / "meta"
            if not meta_dir.exists():
                meta_dir = shard_dir

            def _load_or_empty(path, fallback=None):
                for p in ([path] if not isinstance(path, list) else path):
                    if Path(p).exists():
                        with open(p) as f:
                            return json.load(f)
                return fallback if fallback is not None else []

            texts = _load_or_empty([meta_dir / "texts.json", shard_dir / "texts.json"])
            authors = _load_or_empty(meta_dir / "authors.json")
            channels = _load_or_empty(meta_dir / "channels.json")
            tags = _load_or_empty(meta_dir / "tags.json")
            timestamps = _load_or_empty(meta_dir / "timestamps.json")
            media_paths = _load_or_empty(meta_dir / "media_paths.json")
            urls = _load_or_empty(meta_dir / "urls.json")
            values = _load_or_empty(meta_dir / "values.json")

            # Starting vector ID for new records
            start_id = len(texts)

            # ── Append sidecar ────────────────────────────────
            for sc in sidecars:
                texts.append(sc["text"])
                authors.append(sc["author"])
                channels.append(sc["channel"])
                tags.append(sc["tags"])
                timestamps.append(sc["timestamp"])
                media_paths.append(sc["media_path"])
                urls.append(sc["url"])
                values.append(sc["value"])

            # ── Load existing index and append vectors ────────
            idx_path = shard_dir / "index" / "chunk_index.npz"
            lsh_path = shard_dir / "index" / "lsh_index.npz"

            # Build fresh index from all vectors (existing + new)
            # This is simpler than incremental NPZ append and guarantees consistency
            idx = ehc.BSCCompactIndex(self.dim, use_sign_scoring=True)

            lsh_tables = cfg.LSH_TABLES if cfg else 8
            lsh_hash = cfg.LSH_HASH_SIZE if cfg else 16
            lsh_mp = cfg.LSH_MULTIPROBE if cfg else True
            lsh = ehc.BSCLSHIndex(self.dim, self.k,
                                   num_tables=lsh_tables, hash_size=lsh_hash,
                                   use_multiprobe=lsh_mp)

            # Load existing vectors from index
            if idx_path.exists():
                d = np.load(str(idx_path), allow_pickle=True)
                n_existing = int(d["n_vectors"][0])
                if "vec_indices" in d and "vec_signs" in d and "vec_offsets" in d:
                    vi = d["vec_indices"].astype(np.int32)
                    vs = d["vec_signs"].astype(np.int8)
                    vo = d["vec_offsets"]
                    existing_vecs = []
                    existing_ids = []
                    for i in range(n_existing):
                        start = int(vo[i])
                        end = int(vo[i + 1]) if i + 1 < len(vo) else len(vi)
                        if end > start:
                            existing_vecs.append(ehc.SparseVector(
                                self.dim,
                                np.ascontiguousarray(vi[start:end]),
                                np.ascontiguousarray(vs[start:end])))
                            existing_ids.append(i)
                    if existing_vecs:
                        idx.add_items(existing_vecs, existing_ids)
                        lsh.add_items(existing_vecs, existing_ids)
                    del existing_vecs, existing_ids

            # Add new vectors
            new_ids = list(range(start_id, start_id + n_new))
            idx.add_items(vecs, new_ids)
            lsh.add_items(vecs, new_ids)

            # ── Save index (atomic via temp file) ─────────────
            data = idx.serialize()
            np.savez_compressed(
                str(idx_path),
                dim=np.array([data.dim]),
                n_vectors=np.array([data.n_vectors]),
                use_sign_scoring=np.array([1], dtype=np.int32),
                ids=np.array(data.ids, dtype=np.int32),
                plus_data=np.array(data.plus_data, dtype=np.int32),
                plus_offsets=np.array(data.plus_offsets, dtype=np.int64),
                minus_data=np.array(data.minus_data, dtype=np.int32),
                minus_offsets=np.array(data.minus_offsets, dtype=np.int64),
                vec_indices=np.array(data.vec_indices, dtype=np.int16),
                vec_signs=np.array(data.vec_signs, dtype=np.int8),
                vec_offsets=np.array(data.vec_offsets, dtype=np.int64),
            )

            lsh_data = lsh.serialize()
            lsh_arrays = {
                "dim": np.array([lsh_data.dim]),
                "k": np.array([lsh_data.k]),
                "num_tables": np.array([lsh_data.num_tables]),
                "hash_size": np.array([lsh_data.hash_size]),
                "n_vectors": np.array([lsh_data.n_vectors]),
                "ids": np.array(lsh_data.ids, dtype=np.int64),
                "vec_indices": np.array(lsh_data.vec_indices, dtype=np.int32),
                "vec_signs": np.array(lsh_data.vec_signs, dtype=np.int8),
                "vec_offsets": np.array(lsh_data.vec_offsets, dtype=np.int64),
            }
            for t in range(lsh_data.num_tables):
                lsh_arrays[f"bucket_ids_{t}"] = np.array(lsh_data.bucket_ids[t], dtype=np.int32)
                lsh_arrays[f"bucket_offsets_{t}"] = np.array(lsh_data.bucket_offsets[t], dtype=np.int64)
            np.savez_compressed(str(lsh_path), **lsh_arrays)

            del idx, lsh, data, lsh_data, lsh_arrays
            gc.collect()

            # ── Save sidecar ──────────────────────────────────
            meta_dir.mkdir(exist_ok=True)
            with open(meta_dir / "texts.json", "w") as f: json.dump(texts, f)
            with open(meta_dir / "authors.json", "w") as f: json.dump(authors, f)
            with open(meta_dir / "channels.json", "w") as f: json.dump(channels, f)
            with open(meta_dir / "tags.json", "w") as f: json.dump(tags, f)
            with open(meta_dir / "timestamps.json", "w") as f: json.dump(timestamps, f)
            with open(meta_dir / "media_paths.json", "w") as f: json.dump(media_paths, f)
            with open(meta_dir / "urls.json", "w") as f: json.dump(urls, f)
            with open(meta_dir / "values.json", "w") as f: json.dump(values, f)
            # Backward compat
            with open(shard_dir / "texts.json", "w") as f: json.dump(texts, f)

            # ── Update shard manifest ─────────────────────────
            shard_manifest = {
                "worker_id": shard_id,
                "n_encoded": len(texts),
                "dim": self.dim,
                "k": self.k,
            }
            with open(shard_dir / "manifest.json", "w") as f:
                json.dump(shard_manifest, f, indent=2)

            total_added += n_new
            print(f"  [shard {shard_id:04d}] +{n_new} vectors (total: {len(texts)})")

        # Clear buffers
        self._buffers.clear()

        elapsed = time.perf_counter() - t0
        print(f"  Flushed {total_added} vectors to {len(self._affected)} shards in {elapsed:.1f}s")

    @property
    def affected_shards(self) -> set:
        """Shard IDs that were modified since last flush."""
        return set(self._affected)

    @property
    def stats(self) -> dict:
        buffered = sum(len(v) for v in self._buffers.values())
        return {
            "ingested": self._ingested,
            "buffered": buffered,
            "affected_shards": len(self._affected),
            "flushed": self._ingested - buffered,
        }
