"""
G.A8.1 — Worker Encoder (Searchable / Hidden Architecture)

Vector budget: √k ≈ 12 salient tokens per content vector.
Everything else is sidecar metadata — stored, never encoded.

  SEARCHABLE:  superpose(top_12_salient_tokens) → BSC vector → knn index
  HIDDEN:      text, author, tags, media_path, url, timestamp → parallel JSON arrays

Salience selection:
  - Tokens ≤ 12: use all (triples, short records)
  - Tokens > 12: select top-12 by inverse document frequency within shard

Media: encoded via ehc.VisionEncoder / ehc.VideoEncoder (C++) into a
separate per-shard media index. Not fused into the content vector.

Memory discipline: memmap matrices, phrase cache, gc, clear_perm_cache.
G17: numpy-accepting SparseVector constructor — no .tolist() in hot path.
"""

import gc
import hashlib
import json
import math
import os
import re
import sys
import time
import numpy as np
from collections import Counter
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

# Token budget: √k — reads from config, env, or default
try:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import cfg as _cfg
    MAX_SALIENT_TOKENS = _cfg.MAX_SALIENT_TOKENS
except ImportError:
    MAX_SALIENT_TOKENS = 12


def _hash_entity(entity: str, n_buckets: int) -> int:
    h = hashlib.blake2b(entity.encode(), digest_size=8).digest()
    return int.from_bytes(h, "little") % n_buckets


# ── Lightweight stemmer (no dependencies) ────────────────────
# Strips common English suffixes. Not perfect, but collapses
# missile/missiles, attack/attacked/attacking, sanction/sanctions.
_STEM_RULES = [
    (r'ies$', 'y'),     # countries → country
    (r'ves$', 'f'),     # lives → lif (close enough for hashing)
    (r'ing$', ''),      # attacking → attack
    (r'tion$', 't'),    # sanction → sanct (groups sanction/sanctions)
    (r'sion$', 's'),    # explosion → explos
    (r'ment$', ''),     # government → govern
    (r'ness$', ''),     # darkness → dark
    (r'able$', ''),     # searchable → search
    (r'ible$', ''),     # possible → poss
    (r'ated$', 'at'),   # translated → translat
    (r'ized$', 'iz'),   # organized → organiz
    (r'ised$', 'is'),   # recognised → recognis
    (r'ally$', ''),     # internationally → internation
    (r'ous$', ''),      # dangerous → danger
    (r'ful$', ''),      # powerful → power
    (r'ive$', ''),      # explosive → explos
    (r'ery$', ''),      # delivery → deliv
    (r'ed$', ''),       # attacked → attack
    (r'er$', ''),       # commander → command
    (r'ly$', ''),       # recently → recent
    (r'es$', ''),       # forces → forc
    (r's$', ''),        # missiles → missile
]
_STEM_COMPILED = [(re.compile(pat), rep) for pat, rep in _STEM_RULES]


def _stem(word: str) -> str:
    """Lightweight suffix stripping. Preserves short words."""
    if len(word) <= 4:
        return word
    for pat, rep in _STEM_COMPILED:
        result = pat.sub(rep, word)
        if result != word and len(result) >= 3:
            return result
    return word


def _tokenize(text: str) -> list:
    return [w for w in text.replace("_", " ").lower().split()
            if w not in STOP_WORDS and len(w) > 1]


# ═════════════════════════════════════════════════════════════
#  SALIENCE: select top-√k tokens by rarity within shard
# ═════════════════════════════════════════════════════════════

def _build_idf(chunks: list) -> dict:
    """Build inverse document frequency from shard's chunks.

    IDF(token) = log(N / df(token)) where df = docs containing token.
    Higher IDF = rarer = more salient.
    """
    n_docs = len(chunks)
    doc_freq = Counter()
    for c in chunks:
        # IDF across ALL fields — same pool as encoding
        s = c.get("subject", "")
        r = c.get("relation", "")
        o = c.get("object", c.get("text", ""))
        unique_tokens = set(_tokenize(s) + _tokenize(r) + _tokenize(o))
        for t in unique_tokens:
            doc_freq[t] += 1

    idf = {}
    for token, df in doc_freq.items():
        idf[token] = math.log(max(n_docs, 1) / max(df, 1))
    return idf


def _select_salient(tokens: list, idf: dict, max_tokens: int = MAX_SALIENT_TOKENS,
                     gazetteer: frozenset = None) -> list:
    """Select top-N tokens by IDF with gazetteer guarantee.

    Gazetteer terms get RESERVED SLOTS — they are always included
    if present in the token list, regardless of IDF. Remaining slots
    filled by highest IDF non-gazetteer tokens.

    This ensures domain-critical terms (terrorism, missile, hezbollah)
    are never pushed out by high-IDF but low-relevance rare words.
    """
    if len(tokens) <= max_tokens:
        return tokens

    # Deduplicate tokens preserving first occurrence
    seen = set()
    unique = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    if len(unique) <= max_tokens:
        return unique

    # Phase 1: Reserve slots for gazetteer terms (guaranteed inclusion)
    selected = []
    remaining = []
    if gazetteer:
        for t in unique:
            if t in gazetteer and len(selected) < max_tokens:
                selected.append(t)
            else:
                remaining.append(t)
    else:
        remaining = unique

    # Phase 2: Fill remaining slots by IDF (rarest first)
    slots_left = max_tokens - len(selected)
    if slots_left > 0 and remaining:
        scored = [(t, idf.get(t, 0.0)) for t in remaining]
        scored.sort(key=lambda x: -x[1])
        for t, _ in scored:
            selected.append(t)
            if len(selected) >= max_tokens:
                break

    return selected


# ═════════════════════════════════════════════════════════════
#  MEDIA: C++ Encoders (separate index, not fused)
# ═════════════════════════════════════════════════════════════

def _init_media_encoders(dim, k):
    """Initialize EHC C++ media encoders. Returns (vision_enc, video_enc)."""
    vision_enc = video_enc = None
    try:
        if hasattr(ehc, "VisionEncoder"):
            vcfg = ehc.VisionEncoderConfig()
            vcfg.dim = dim
            vcfg.k = k
            vcfg.seed = 2100
            vision_enc = ehc.VisionEncoder(vcfg)
        if hasattr(ehc, "VideoEncoder"):
            vidcfg = ehc.VideoEncoderConfig()
            vidcfg.dim = dim
            vidcfg.k = k
            vidcfg.num_frames = 8
            vidcfg.encode_motion = True
            vidcfg.seed = 2300
            video_enc = ehc.VideoEncoder(vidcfg)
    except Exception as e:
        print(f"  [media] Encoder init warning: {e}")
    return vision_enc, video_enc


def _load_image(path: str) -> np.ndarray:
    """Load image as uint8 RGB numpy array (224x224). Returns None on failure."""
    try:
        from PIL import Image
        img = Image.open(path).convert("RGB")
        img = img.resize((224, 224), Image.BILINEAR)
        return np.ascontiguousarray(np.array(img, dtype=np.uint8))
    except Exception:
        pass
    try:
        import cv2
        img = cv2.imread(path)
        if img is None:
            return None
        img = cv2.resize(img, (224, 224))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        return np.ascontiguousarray(img.astype(np.uint8))
    except Exception:
        return None


def _load_video_frames(path: str, n_frames: int = 8) -> np.ndarray:
    """Load video as grayscale uint8 frame array (N,H,W). Returns None on failure."""
    try:
        import cv2
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            return None
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total < 1:
            cap.release()
            return None
        indices = np.linspace(0, total - 1, min(n_frames, total), dtype=int)
        frames = []
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
            ret, frame = cap.read()
            if ret:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.resize(gray, (64, 64))
                frames.append(gray)
        cap.release()
        if not frames:
            return None
        return np.ascontiguousarray(np.stack(frames, axis=0).astype(np.uint8))
    except Exception:
        return None


def _encode_media(chunk, vision_enc, video_enc):
    """Encode media from chunk using C++ encoders. Returns SparseVector or None."""
    media_path = chunk.get("media_path")
    media_type = chunk.get("media_type")
    if not media_path or not media_type:
        return None
    if media_type == "image" and vision_enc is not None:
        img = _load_image(media_path)
        if img is not None:
            try:
                return vision_enc.encode_rgb(img)
            except Exception:
                return None
    if media_type == "video" and video_enc is not None:
        frames = _load_video_frames(media_path)
        if frames is not None:
            try:
                return video_enc.encode_frames(frames)
            except Exception:
                return None
    return None


# ═════════════════════════════════════════════════════════════
#  WORKER
# ═════════════════════════════════════════════════════════════

def worker_encode(args):
    """Encode a partition: searchable content + hidden sidecar.

    Args tuple: (worker_id, chunk_pkl_path, dim, k, output_dir,
                 cluster_centroids_list)
    """
    worker_id, chunk_pkl_path, dim, k, output_dir, cluster_centroids_raw = args

    import pickle
    t0 = time.perf_counter()
    out = Path(output_dir) / f"shard_{worker_id:04d}"
    out.mkdir(parents=True, exist_ok=True)

    # Load pickle
    chunks = []
    with open(chunk_pkl_path, "rb") as f:
        while True:
            try:
                obj = pickle.load(f)
                if isinstance(obj, list):
                    chunks.extend(obj)
                else:
                    chunks.append(obj)
            except EOFError:
                break

    n = len(chunks)
    print(f"  [shard {worker_id:04d}] {n:,} chunks...")

    # ── Codebook (hash mode) ─────────────────────────────────
    try:
        from config import cfg as a81_cfg
        _seed = a81_cfg.SEED
    except ImportError:
        _seed = 42
    cfg = ehc.CodebookConfig()
    cfg.dim = dim
    cfg.k = k
    cfg.seed = _seed
    cb = ehc.TokenCodebook(cfg)
    cb.build_from_vocabulary([])

    # ── Pre-build cluster centroids ──────────────────────────
    cluster_centroids = []
    if cluster_centroids_raw:
        for cd in cluster_centroids_raw:
            ci = cd.get("centroid_indices", [])
            cs = cd.get("centroid_signs", [])
            if ci:
                cluster_centroids.append(ehc.SparseVector(dim,
                    np.array(ci, dtype=np.int32),
                    np.array(cs, dtype=np.int8)))
            else:
                cluster_centroids.append(None)

    # ── Load global IDF (computed across full corpus by orchestrator) ─
    idf_path = Path(output_dir) / "_chunks" / "_global_idf.json"
    if idf_path.exists():
        with open(idf_path) as f:
            idf = json.load(f)
        print(f"  [shard {worker_id:04d}] Global IDF: {len(idf):,} tokens")
    else:
        # Fallback: per-shard IDF
        idf = _build_idf(chunks)

    # ── Load gazetteer (domain-specific salience booster) ─────
    gazetteer = None
    gaz_path = Path(output_dir) / "_chunks" / "_gazetteer.json"
    if gaz_path.exists():
        with open(gaz_path) as f:
            gazetteer = frozenset(json.load(f))
        print(f"  [shard {worker_id:04d}] Gazetteer: {len(gazetteer):,} terms")

    # ── Initialize media encoders ────────────────────────────
    has_media = any(c.get("media_path") for c in chunks)
    vision_enc, video_enc = (None, None)
    if has_media:
        vision_enc, video_enc = _init_media_encoders(dim, k)
        if vision_enc or video_enc:
            print(f"  [shard {worker_id:04d}] Media encoders: "
                  f"vision={'yes' if vision_enc else 'no'} "
                  f"video={'yes' if video_enc else 'no'}")

    # ── Memmap for content vectors ───────────────────────────
    mm_dir = out / "_mm"
    mm_dir.mkdir(exist_ok=True)
    idx_mat = np.memmap(str(mm_dir / "idx.dat"), dtype=np.int32,
                        mode="w+", shape=(n, k))
    sgn_mat = np.memmap(str(mm_dir / "sgn.dat"), dtype=np.int8,
                        mode="w+", shape=(n, k))

    # ── Token cache ──────────────────────────────────────────
    token_cache = ehc.LRUCache(max_size=50000) if hasattr(ehc, "LRUCache") else None

    def _encode_token(w):
        """Encode single token with C++ LRU cache."""
        tv = token_cache.get(w) if token_cache else None
        if tv is None:
            try:
                tv = cb.encode_token(w)
                if token_cache:
                    token_cache.put(w, tv)
            except Exception:
                tv = None
        return tv

    def _encode_tokens(tokens):
        """Encode token list as superpose. Returns SparseVector or None."""
        vecs = []
        for w in tokens:
            tv = _encode_token(w)
            if tv is not None:
                vecs.append(tv)
        if not vecs:
            return None
        return ehc.superpose(vecs) if len(vecs) > 1 else vecs[0]

    # ── SEARCHABLE: content vectors ──────────────────────────
    # ── HIDDEN: sidecar metadata arrays ──────────────────────
    sidecar_texts = []
    sidecar_authors = []
    sidecar_tags = []
    sidecar_channels = []
    sidecar_timestamps = []
    sidecar_media_paths = []
    sidecar_urls = []
    sidecar_values = []
    n_encoded = 0

    # ── Media: separate index ────────────────────────────────
    media_vecs = []      # (vec_id, SparseVector) for media index
    n_media_encoded = 0

    for i, c in enumerate(chunks):
        # Extract tokens from ALL fields — subject, relation, object
        # The salience selector picks the best √k from the full pool
        s = c.get("subject", "")
        r = c.get("relation", "")
        o = c.get("object", c.get("text", ""))
        all_tokens = _tokenize(s) + _tokenize(r) + _tokenize(o)
        if not all_tokens:
            continue

        # ── SALIENCE: select top-12 by IDF ────────────────────
        salient = _select_salient(all_tokens, idf, MAX_SALIENT_TOKENS, gazetteer)

        # ── ENCODE: superpose(salient_tokens) — no bind ──────
        vec = _encode_tokens(salient)
        if vec is None:
            continue

        # Write to memmap
        inds = np.asarray(vec.indices[:k], dtype=np.int32)
        sgns = np.asarray(vec.signs[:k], dtype=np.int8)
        idx_mat[n_encoded, :len(inds)] = inds
        sgn_mat[n_encoded, :len(sgns)] = sgns

        # ── HIDDEN: store sidecar from original record (never transform) ─
        sc = c.get("_sidecar", {})
        if sc:
            # Original record available — use it
            sidecar_texts.append(sc.get("message_text_translated", o[:1000]))
            sidecar_authors.append(sc.get("author", c.get("subject", "")))
            sidecar_values.append(sc.get("message_text", o))
            sidecar_timestamps.append(sc.get("posted_at", c.get("timestamp", "")))
            sidecar_media_paths.append(sc.get("media_path", c.get("media_path", "")))
            sidecar_urls.append(sc.get("url", ""))
            sidecar_tags.append(json.dumps(sc.get("tags", [])))
            sidecar_channels.append(sc.get("channel", ""))
        else:
            # Fallback for structured triples (WikiData, etc.)
            sidecar_texts.append(c.get("text", f"{s} {r} {o}"))
            sidecar_authors.append(c.get("subject", ""))
            sidecar_values.append(c.get("object", ""))
            sidecar_timestamps.append(c.get("timestamp", ""))
            sidecar_media_paths.append(c.get("media_path", ""))
            sidecar_urls.append(c.get("url", ""))
            sidecar_tags.append(json.dumps([]))
            sidecar_channels.append("")

        # ── MEDIA: encode into separate index ─────────────────
        media_vec = _encode_media(c, vision_enc, video_enc)
        if media_vec is not None:
            media_vecs.append((n_encoded, media_vec))
            n_media_encoded += 1

        n_encoded += 1

        # Memory discipline
        if (i + 1) % 2000 == 0:
            ehc.clear_perm_cache()
        if (i + 1) % 500000 == 0:
            idx_mat.flush()
            sgn_mat.flush()
            gc.collect()
            print(f"    [shard {worker_id:04d}] {i+1:,}/{n:,} ({time.perf_counter()-t0:.0f}s)")

    ehc.clear_perm_cache()
    idx_mat.flush()
    sgn_mat.flush()
    gc.collect()

    # ── Build content CompactIndex + LSH ─────────────────────
    print(f"  [shard {worker_id:04d}] Building content index ({n_encoded:,})...")
    idx = ehc.BSCCompactIndex(dim, use_sign_scoring=True)
    try:
        from config import cfg as a81_cfg
        _lsh_tables = a81_cfg.LSH_TABLES
        _lsh_hash = a81_cfg.LSH_HASH_SIZE
        _lsh_mp = a81_cfg.LSH_MULTIPROBE
    except ImportError:
        _lsh_tables, _lsh_hash, _lsh_mp = 8, 16, True
    lsh = ehc.BSCLSHIndex(dim, k, num_tables=_lsh_tables, hash_size=_lsh_hash, use_multiprobe=_lsh_mp)

    batch_size = 50000
    for bs in range(0, n_encoded, batch_size):
        be = min(bs + batch_size, n_encoded)
        bv, bi = [], []
        for row in range(bs, be):
            inds = np.ascontiguousarray(idx_mat[row])
            sgns = np.ascontiguousarray(sgn_mat[row])
            nz = k
            while nz > 0 and inds[nz - 1] == 0 and sgns[nz - 1] == 0:
                nz -= 1
            if nz > 0:
                bv.append(ehc.SparseVector(dim, inds[:nz], sgns[:nz]))
                bi.append(row)
        if bv:
            idx.add_items(bv, bi)
            lsh.add_items(bv, bi)
        del bv, bi
        gc.collect()

    # ── Save content index ───────────────────────────────────
    idx_dir = out / "index"
    idx_dir.mkdir(exist_ok=True)

    data = idx.serialize()
    np.savez_compressed(
        str(idx_dir / "chunk_index.npz"),
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
    del idx, data
    gc.collect()

    # ── Save LSH ─────────────────────────────────────────────
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
    np.savez_compressed(str(idx_dir / "lsh_index.npz"), **lsh_arrays)
    del lsh, lsh_data, lsh_arrays
    gc.collect()

    # ── Build separate media index (if any media encoded) ────
    if media_vecs:
        print(f"  [shard {worker_id:04d}] Building media index ({len(media_vecs):,})...")
        media_idx = ehc.BSCCompactIndex(dim, use_sign_scoring=True)
        media_lsh = ehc.BSCLSHIndex(dim, k, num_tables=_lsh_tables, hash_size=_lsh_hash, use_multiprobe=_lsh_mp)
        mvecs = [mv for _, mv in media_vecs]
        mids = [mid for mid, _ in media_vecs]
        media_idx.add_items(mvecs, mids)
        media_lsh.add_items(mvecs, mids)

        mdata = media_idx.serialize()
        np.savez_compressed(
            str(idx_dir / "media_index.npz"),
            dim=np.array([mdata.dim]),
            n_vectors=np.array([mdata.n_vectors]),
            use_sign_scoring=np.array([1], dtype=np.int32),
            ids=np.array(mdata.ids, dtype=np.int32),
            plus_data=np.array(mdata.plus_data, dtype=np.int32),
            plus_offsets=np.array(mdata.plus_offsets, dtype=np.int64),
            minus_data=np.array(mdata.minus_data, dtype=np.int32),
            minus_offsets=np.array(mdata.minus_offsets, dtype=np.int64),
            vec_indices=np.array(mdata.vec_indices, dtype=np.int16),
            vec_signs=np.array(mdata.vec_signs, dtype=np.int8),
            vec_offsets=np.array(mdata.vec_offsets, dtype=np.int64),
        )
        mlsh_data = media_lsh.serialize()
        mlsh_arrays = {
            "dim": np.array([mlsh_data.dim]),
            "k": np.array([mlsh_data.k]),
            "num_tables": np.array([mlsh_data.num_tables]),
            "hash_size": np.array([mlsh_data.hash_size]),
            "n_vectors": np.array([mlsh_data.n_vectors]),
            "ids": np.array(mlsh_data.ids, dtype=np.int64),
            "vec_indices": np.array(mlsh_data.vec_indices, dtype=np.int32),
            "vec_signs": np.array(mlsh_data.vec_signs, dtype=np.int8),
            "vec_offsets": np.array(mlsh_data.vec_offsets, dtype=np.int64),
        }
        for t in range(mlsh_data.num_tables):
            mlsh_arrays[f"bucket_ids_{t}"] = np.array(mlsh_data.bucket_ids[t], dtype=np.int32)
            mlsh_arrays[f"bucket_offsets_{t}"] = np.array(mlsh_data.bucket_offsets[t], dtype=np.int64)
        np.savez_compressed(str(idx_dir / "media_lsh_index.npz"), **mlsh_arrays)
        del media_idx, media_lsh, mdata, mlsh_data, mlsh_arrays, mvecs, mids
        gc.collect()
    del media_vecs
    gc.collect()

    # ── Save HIDDEN sidecar metadata (EHS1 binary format) ────
    from pathlib import Path as _Path
    _ga81 = _Path(__file__).resolve().parent.parent
    if str(_ga81) not in sys.path:
        sys.path.insert(0, str(_ga81))
    from sidecar_utils import iso_to_ms, write_manifest

    ehs_path = out / "sidecar.ehs"
    writer = ehc.SidecarWriter(str(ehs_path))
    for i in range(n_encoded):
        raw_tags = sidecar_tags[i]
        tags_list = json.loads(raw_tags) if raw_tags else []
        writer.append(
            text=sidecar_texts[i],
            author=sidecar_authors[i],
            channel=sidecar_channels[i],
            url=sidecar_urls[i],
            media_path=sidecar_media_paths[i],
            value=sidecar_values[i],
            tags=tags_list,
            timestamp=iso_to_ms(sidecar_timestamps[i]),
        )
    writer.finalize()
    write_manifest(out, [{"name": "sidecar.ehs", "n_vectors": n_encoded}])

    # Backward compat: JSON sidecars (benchmarks + legacy tools)
    meta_dir = out / "meta"
    meta_dir.mkdir(exist_ok=True)
    for name, arr in [("texts", sidecar_texts), ("authors", sidecar_authors),
                      ("tags", sidecar_tags), ("channels", sidecar_channels),
                      ("timestamps", sidecar_timestamps),
                      ("media_paths", sidecar_media_paths),
                      ("urls", sidecar_urls), ("values", sidecar_values)]:
        with open(meta_dir / f"{name}.json", "w") as f:
            json.dump(arr, f)
    with open(out / "texts.json", "w") as f:
        json.dump(sidecar_texts, f)

    # ── Centroid ─────────────────────────────────────────────
    sample_size = min(1000, n_encoded)
    sample_vecs = []
    for row in range(0, n_encoded, max(1, n_encoded // sample_size)):
        inds = np.ascontiguousarray(idx_mat[row])
        sgns = np.ascontiguousarray(sgn_mat[row])
        nz = k
        while nz > 0 and inds[nz - 1] == 0 and sgns[nz - 1] == 0:
            nz -= 1
        if nz > 0:
            sample_vecs.append(ehc.SparseVector(dim, inds[:nz], sgns[:nz]))
        if len(sample_vecs) >= sample_size:
            break
    if sample_vecs:
        centroid = ehc.superpose(sample_vecs)
        np.savez(str(out / "centroid.npz"),
                 indices=np.asarray(centroid.indices[:k], dtype=np.int16),
                 signs=np.asarray(centroid.signs[:k], dtype=np.int8))
    del sample_vecs
    gc.collect()

    # ── Cleanup memmap ───────────────────────────────────────
    del idx_mat, sgn_mat
    gc.collect()
    import shutil
    shutil.rmtree(str(mm_dir), ignore_errors=True)

    elapsed = time.perf_counter() - t0
    manifest = {
        "worker_id": worker_id,
        "n_chunks": n,
        "n_encoded": n_encoded,
        "n_media_encoded": n_media_encoded,
        "max_salient_tokens": MAX_SALIENT_TOKENS,
        "idf_vocab_size": len(idf),
        "dim": dim,
        "k": k,
        "elapsed_s": round(elapsed, 1),
        "rate_per_sec": round(n_encoded / elapsed, 1) if elapsed > 0 else 0,
    }
    with open(out / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    media_tag = f", {n_media_encoded:,} media" if n_media_encoded > 0 else ""
    print(f"  [shard {worker_id:04d}] Done: {n_encoded:,} vectors{media_tag} | "
          f"{elapsed:.1f}s | {manifest['rate_per_sec']:,.0f}/sec")
    return manifest
