#!/usr/bin/env python3
"""G.A8.1 M3 Entangled-DC processor: loads encoded shards from disk and serves
the ternary VSA wire on 127.0.0.1:8443.

This is the operator-side bootstrap script that MIGRATION.md §4.1 calls out
as not-yet-wired-over-the-wire. Shards live on the processor's local disk;
this script reconstructs dense ternary vectors from the on-disk sparse
(indices+signs+offsets) format and feeds them to RemoteProcessor.load_shard()
before serving.

Run via systemd. Reads the same config as the rest of G.A8.1
(env vars + configs/entangled_dc.env).
"""
from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path
from typing import List, Tuple

import numpy as np

sys.path.insert(0, "/opt/G.A8.1")

from config import cfg                                           # noqa: E402
from transport.remote_processor import (                         # noqa: E402
    RemoteProcessor,
    RemoteProcessorConfig,
    serve,
)


def _load_shard_from_disk(shard_dir: Path, dim: int) -> Tuple[int, List[Tuple[int, np.ndarray]]]:
    """Reconstruct dense ternary vectors from a shard's chunk_index.npz.

    The on-disk format is sparse:
      vec_indices[start:end]  active dimension indices for vector i
      vec_signs[start:end]    matching {-1, +1} signs
      vec_offsets[i]          cumulative offset for vector i

    Returns (shard_id, [(slot_id, dense_int8_vec), ...]).
    """
    shard_id = int(shard_dir.name.split("_")[1])
    npz = shard_dir / "index" / "chunk_index.npz"
    if not npz.exists():
        raise FileNotFoundError(f"missing {npz}")

    d = np.load(str(npz), allow_pickle=True)
    n_vectors = int(d["n_vectors"][0])
    file_dim = int(d["dim"][0])
    if file_dim != dim:
        raise ValueError(
            f"shard {shard_id} dim={file_dim} != configured dim={dim}; "
            f"re-encode at the configured geometry"
        )

    vi = d["vec_indices"].astype(np.int32, copy=False)
    vs = d["vec_signs"].astype(np.int8, copy=False)
    vo = d["vec_offsets"].astype(np.int64, copy=False)
    ids = d["ids"].astype(np.int32, copy=False) if "ids" in d.files else np.arange(n_vectors, dtype=np.int32)

    out: List[Tuple[int, np.ndarray]] = []
    for i in range(n_vectors):
        start = int(vo[i])
        end = int(vo[i + 1]) if i + 1 < len(vo) else len(vi)
        dense = np.zeros(dim, dtype=np.int8)
        if end > start:
            dense[vi[start:end]] = vs[start:end]
        out.append((int(ids[i]), dense))
    return shard_id, out


def _shard_dirs(index_path: Path) -> List[Path]:
    """Return shard_NNNN/ directories under INDEX_PATH, sorted by id."""
    shards = sorted(p for p in index_path.iterdir()
                    if p.is_dir() and p.name.startswith("shard_"))
    if not shards and (index_path / "structural_v13").is_dir():
        shards = [index_path / "structural_v13"]
    return shards


def main() -> None:
    index_path = Path(os.environ.get("A81_INDEX_PATH", "/opt/G.A8.1/data/encoded"))
    host = os.environ.get("A81_M3_HOST", "127.0.0.1")
    port = int(os.environ.get("A81_M3_PORT", "8443"))
    pin_mode = os.environ.get("A81_M3_PIN_MODE", "session")

    cfg.assert_ready_for("entangled_dc")
    print(f"[m3] config: {cfg.summary()}", flush=True)
    print(f"[m3] index_path: {index_path}", flush=True)

    profile_path = index_path / "corpus_profile.json"
    if not profile_path.exists():
        raise SystemExit(f"missing corpus_profile.json at {profile_path}; encode first")

    import json
    with open(profile_path) as f:
        prof = json.load(f)
    dim = int(prof["recommended_dim"])

    proc = RemoteProcessor(RemoteProcessorConfig(pin_mode=pin_mode))

    # ── Load all shards ───────────────────────────────────
    t0 = time.monotonic()
    total_vecs = 0
    for sd in _shard_dirs(index_path):
        sid, vecs = _load_shard_from_disk(sd, dim=dim)
        proc.load_shard(sid, vecs)
        total_vecs += len(vecs)
        print(f"[m3] loaded shard {sid:04d} from {sd.name} ({len(vecs):,} vectors)",
              flush=True)
    elapsed = time.monotonic() - t0
    print(f"[m3] {total_vecs:,} vectors loaded in {elapsed:.1f}s; serving on "
          f"{host}:{port} pin_mode={pin_mode}", flush=True)

    # Graceful shutdown on SIGTERM
    def _stop(signum, frame):
        print(f"[m3] received signal {signum}, exiting", flush=True)
        sys.exit(0)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    serve(proc, host=host, port=port)


if __name__ == "__main__":
    main()
