"""Phase 3: Images D/k sweep on 5K real edge images.

Retrieval task: self-identity with light augmentation. For each image:
  - Encode original at (D, k)
  - Query with a slightly-resized variant (simulates JPEG re-save /
    CDN transform)
  - Measure Hit@1 — can the encoder find the "same" image through a
    transform?

This tests encoder robustness + LSH routing on image vectors.

Uses ehc.VisionEncoder (deterministic hashing over spatial grid +
color + edge + texture features). Configurable dim/k.
"""

from __future__ import annotations

import argparse
import gc
import glob
import json
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent))

for _d in (2, 3, 4):
    _p = _HERE.parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc  # noqa: E402
import numpy as np  # noqa: E402


DEFAULT_MEDIA_DIR = ("/Users/stark/Quantum_Computing_Lab/MjolnirPhotonics/"
                      "product.edge.analyst.bsc_old/edge_service/staged/data2/media")


_TARGET_SIZE = (224, 224)  # VisionEncoder requires this exact shape


def _load_image_rgb(path: str):
    """Load via Pillow → numpy uint8 (224, 224, 3) — size mandated by
    ehc.VisionEncoder's spatial grid feature extraction."""
    from PIL import Image
    img = Image.open(path).convert("RGB").resize(_TARGET_SIZE, Image.BILINEAR)
    return np.ascontiguousarray(np.array(img, dtype=np.uint8))


def _augment(img_arr, seed: int):
    """Light augmentation that survives the 224×224 constraint: a down-
    sample + re-upsample that simulates a JPEG re-save / CDN transform.
    Keeps semantic content; changes pixel-level signal slightly."""
    from PIL import Image
    rng = random.Random(seed)
    pil = Image.fromarray(img_arr)
    intermediate = int(224 * rng.uniform(0.80, 0.95))
    pil = pil.resize((intermediate, intermediate), Image.BILINEAR)
    pil = pil.resize(_TARGET_SIZE, Image.BILINEAR)
    return np.ascontiguousarray(np.array(pil, dtype=np.uint8))


def _build_encoder(dim: int, k: int, seed: int = 42):
    cfg = ehc.VisionEncoderConfig()
    cfg.dim = dim
    cfg.k = k
    cfg.seed = seed
    # Leave the other fields at their defaults (grid_size, edge_bins, etc.)
    return ehc.VisionEncoder(cfg)


def _build_index(dim: int, k: int):
    from config import resolve_lsh_hash_size
    hs = resolve_lsh_hash_size(dim)  # using D to hint bucket count — acceptable for 5K
    return ehc.BSCLSHIndex(dim, k, num_tables=8, hash_size=hs,
                            use_multiprobe=True)


def run_config(image_paths: List[str], n_query: int, dim: int, k: int,
               query_threads: int, top_k: int):
    enc = _build_encoder(dim, k)

    # Encode all images → SparseVector. Load/encode sequentially — Pillow
    # decode isn't GIL-released in this binding. Workers could decode in
    # parallel but that adds complexity; 5K images is fast enough.
    t_e = time.perf_counter()
    vecs = []
    ids = []
    for i, pth in enumerate(image_paths):
        try:
            img = _load_image_rgb(pth)
            v = enc.encode_rgb(img)
            vecs.append(v)
            ids.append(i)
        except Exception:
            continue  # skip unreadable
    t_encode = time.perf_counter() - t_e

    # Build LSH
    t_b = time.perf_counter()
    lsh = _build_index(dim, k)
    BATCH = 1000
    for bs in range(0, len(vecs), BATCH):
        be = min(bs + BATCH, len(vecs))
        lsh.add_items(vecs[bs:be], ids[bs:be])
    t_build = time.perf_counter() - t_b

    # Build query set: augmented variants of first n_query images
    t_q = time.perf_counter()
    query_indices = list(range(min(n_query, len(vecs))))
    augmented_vecs = []
    for i in query_indices:
        try:
            img = _load_image_rgb(image_paths[i])
            img_aug = _augment(img, seed=42 + i)
            augmented_vecs.append(enc.encode_rgb(img_aug))
        except Exception:
            augmented_vecs.append(None)

    # Warmup 20 queries
    for qv in augmented_vecs[:20]:
        if qv is not None:
            lsh.knn_query(qv, k=top_k)

    # Benchmark
    latencies = []
    hits_at_1 = 0
    hits_at_10 = 0
    n_valid = 0
    for qi, qv in enumerate(augmented_vecs):
        if qv is None:
            continue
        n_valid += 1
        ta = time.perf_counter()
        r = lsh.knn_query(qv, k=top_k)
        latencies.append((time.perf_counter() - ta) * 1000.0)
        hit_ids = list(r.ids)
        if hit_ids:
            if hit_ids[0] == query_indices[qi]:
                hits_at_1 += 1
                hits_at_10 += 1
            else:
                for h in hit_ids[:top_k]:
                    if h == query_indices[qi]:
                        hits_at_10 += 1
                        break
    t_query = time.perf_counter() - t_q

    result = {
        "dim": dim, "k": k,
        "n_encoded": len(vecs),
        "n_queries": n_valid,
        "encode_s": round(t_encode, 2),
        "encode_rate": round(len(vecs) / t_encode, 0) if t_encode else 0,
        "lsh_build_s": round(t_build, 2),
        "query_s": round(t_query, 2),
        "Hit@1": round(100 * hits_at_1 / max(n_valid, 1), 2),
        "Hit@10": round(100 * hits_at_10 / max(n_valid, 1), 2),
        "p50_ms": round(statistics.median(latencies), 2) if latencies else 0.0,
        "p95_ms": (round(statistics.quantiles(latencies, n=100)[94], 2)
                    if len(latencies) >= 100 else
                    round(max(latencies), 2) if latencies else 0.0),
    }

    del enc, lsh, vecs, augmented_vecs
    gc.collect()
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--media-dir", default=DEFAULT_MEDIA_DIR)
    ap.add_argument("--n-images", type=int, default=5000)
    ap.add_argument("--n-queries", type=int, default=500)
    ap.add_argument("--grid", default="4096,8192,16384,32768")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--query-threads", type=int, default=12)
    ap.add_argument("--out-json", default=None)
    args = ap.parse_args()

    # Sample image file list
    print(f"=== v13.1 image D/k sweep ===", flush=True)
    print(f"  media_dir : {args.media_dir}", flush=True)
    all_paths = sorted(glob.glob(str(Path(args.media_dir) / "*.jpg")))
    print(f"  found     : {len(all_paths):,} .jpg files", flush=True)
    random.Random(42).shuffle(all_paths)
    paths = all_paths[:args.n_images]
    print(f"  using     : {len(paths)} images (self-identity + augmentation)",
          flush=True)

    grid = [int(x) for x in args.grid.split(",")]
    results = []
    for dim in grid:
        k = max(1, int(round(dim ** 0.5)))
        print(f"\n── D={dim}, k={k} ──", flush=True)
        r = run_config(paths, args.n_queries, dim, k,
                       args.query_threads, args.top_k)
        print(f"   encoded {r['n_encoded']} imgs in {r['encode_s']}s "
              f"({r['encode_rate']:,.0f}/s)  Hit@1={r['Hit@1']}%  "
              f"p50={r['p50_ms']}ms", flush=True)
        results.append(r)

    print(f"\n{'─' * 90}", flush=True)
    print(f"  {'D':>5}  {'k':>4}  {'encode/s':>10}  {'Hit@1':>7}  "
          f"{'Hit@10':>7}  {'p50 ms':>8}  {'p95 ms':>8}", flush=True)
    for r in results:
        print(f"  {r['dim']:>5}  {r['k']:>4}  {r['encode_rate']:>10,.0f}  "
              f"{r['Hit@1']:>6.2f}%  {r['Hit@10']:>6.2f}%  "
              f"{r['p50_ms']:>7.2f}  {r['p95_ms']:>7.2f}", flush=True)
    print(f"{'─' * 90}", flush=True)

    if args.out_json:
        with open(args.out_json, "w") as f:
            json.dump({
                "media_dir": args.media_dir,
                "n_images": len(paths),
                "n_queries_target": args.n_queries,
                "grid": grid,
                "results": results,
            }, f, indent=2)
        print(f"\nfull results: {args.out_json}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
