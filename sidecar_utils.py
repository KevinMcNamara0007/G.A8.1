"""
Sidecar utilities — shared by encode, ingest, decode, and compaction.

ShardSidecar: multi-segment reader (base + deltas via manifest).
Manifest I/O: read/write sidecar.manifest JSON.
Compaction:   merge base + deltas → new base, atomic manifest swap.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import sys
for _depth in (1, 2, 3):
    _ehc = Path(__file__).resolve().parents[_depth] / "EHC" / "build" / "bindings" / "python"
    if _ehc.exists():
        sys.path.insert(0, str(_ehc))
        break
import ehc


# ── Timestamp conversion ────────────────────────────────────────────────────

def iso_to_ms(s: str) -> int:
    """ISO-8601 UTC string → epoch milliseconds."""
    if not s:
        return 0
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def ms_to_iso(ms: int) -> str:
    """Epoch milliseconds → ISO-8601 UTC string."""
    if ms == 0:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


# ── Manifest I/O ────────────────────────────────────────────────────────────

MANIFEST_NAME = "sidecar.manifest"


def read_manifest(shard_dir: Path) -> Optional[dict]:
    """Read sidecar.manifest. Returns None if absent."""
    p = shard_dir / MANIFEST_NAME
    if not p.exists():
        return None
    with p.open() as f:
        return json.load(f)


def write_manifest(shard_dir: Path, files: List[dict]):
    """Atomic-write sidecar.manifest.

    files: [{"name": "sidecar.ehs", "n_vectors": 13506}, ...]
    """
    manifest = {"files": files}
    tmp = shard_dir / (MANIFEST_NAME + ".tmp")
    with tmp.open("w") as f:
        json.dump(manifest, f, indent=2)
    tmp.rename(shard_dir / MANIFEST_NAME)


def next_delta_name(shard_dir: Path) -> str:
    """Return the next sidecar.delta.NNNN.ehs filename."""
    existing = sorted(shard_dir.glob("sidecar.delta.*.ehs"))
    if not existing:
        return "sidecar.delta.0001.ehs"
    last_num = int(existing[-1].stem.split(".")[-1])
    return f"sidecar.delta.{last_num + 1:04d}.ehs"


# ── ShardSidecar — multi-segment reader ─────────────────────────────────────

class ShardSidecar:
    """Reads a shard's sidecar data across base + delta files.

    If a sidecar.manifest exists, opens all listed segments. Otherwise falls
    back to a single sidecar.ehs (or None if nothing exists).
    """

    def __init__(self, stores: list, cum_vids: List[int]):
        self._stores = stores        # list of ehc.SidecarStore
        self._cum = cum_vids          # cumulative vid boundaries, len = len(stores)+1
        self._total = cum_vids[-1] if cum_vids else 0

    @staticmethod
    def open_dir(shard_dir) -> Optional["ShardSidecar"]:
        shard_dir = Path(shard_dir)
        manifest = read_manifest(shard_dir)
        if manifest:
            stores, cum = [], [0]
            for entry in manifest["files"]:
                p = shard_dir / entry["name"]
                if not p.exists():
                    return None
                s = ehc.SidecarStore.open(str(p))
                if s is None:
                    return None
                stores.append(s)
                cum.append(cum[-1] + s.n_vectors())
            if not stores:
                return None
            return ShardSidecar(stores, cum)

        ehs = shard_dir / "sidecar.ehs"
        if ehs.exists():
            s = ehc.SidecarStore.open(str(ehs))
            if s is None:
                return None
            return ShardSidecar([s], [0, s.n_vectors()])
        return None

    def n_vectors(self) -> int:
        return self._total

    def _dispatch(self, vid: int):
        """Return (segment_index, local_vid)."""
        for i in range(len(self._stores)):
            if vid < self._cum[i + 1]:
                return i, vid - self._cum[i]
        return len(self._stores) - 1, vid - self._cum[-1]

    def text(self, vid: int) -> str:
        i, lv = self._dispatch(vid)
        return self._stores[i].text(lv)

    def author(self, vid: int) -> str:
        i, lv = self._dispatch(vid)
        return self._stores[i].author(lv)

    def channel(self, vid: int) -> str:
        i, lv = self._dispatch(vid)
        return self._stores[i].channel(lv)

    def url(self, vid: int) -> str:
        i, lv = self._dispatch(vid)
        return self._stores[i].url(lv)

    def media_path(self, vid: int) -> str:
        i, lv = self._dispatch(vid)
        return self._stores[i].media_path(lv)

    def value(self, vid: int) -> str:
        i, lv = self._dispatch(vid)
        return self._stores[i].value(lv)

    def tags(self, vid: int) -> list:
        i, lv = self._dispatch(vid)
        return self._stores[i].tags(lv)

    def timestamp(self, vid: int) -> int:
        i, lv = self._dispatch(vid)
        return self._stores[i].timestamp(lv)


# ── Compaction ──────────────────────────────────────────────────────────────

def should_compact(shard_dir: Path, ratio_threshold: float = 0.1) -> bool:
    """True if sum(delta sizes) / base_size > ratio_threshold."""
    shard_dir = Path(shard_dir)
    manifest = read_manifest(shard_dir)
    if not manifest or len(manifest["files"]) <= 1:
        return False
    base_path = shard_dir / manifest["files"][0]["name"]
    if not base_path.exists():
        return False
    base_size = base_path.stat().st_size
    if base_size == 0:
        return True
    delta_size = sum(
        (shard_dir / f["name"]).stat().st_size
        for f in manifest["files"][1:]
        if (shard_dir / f["name"]).exists()
    )
    return (delta_size / base_size) > ratio_threshold


def compact_sidecar(shard_dir: Path) -> dict:
    """Merge base + all deltas into a new base. Atomic manifest swap.

    Returns stats dict. Safe for concurrent readers: old mmaps remain valid
    (POSIX unlink semantics). Orphan .new files from crashed compactions are
    cleaned up.
    """
    shard_dir = Path(shard_dir)

    # Clean up any orphaned .new from a prior crash
    for orphan in shard_dir.glob("*.ehs.new"):
        orphan.unlink()

    manifest = read_manifest(shard_dir)
    if not manifest or len(manifest["files"]) <= 1:
        return {"compacted": False, "reason": "nothing to compact"}

    t0 = time.perf_counter()

    # Open all segments via ShardSidecar
    sc = ShardSidecar.open_dir(shard_dir)
    if sc is None:
        return {"compacted": False, "reason": "could not open segments"}

    total = sc.n_vectors()

    # Write merged base to .new file
    new_base = shard_dir / "sidecar.ehs.new"
    writer = ehc.SidecarWriter(str(new_base))
    for vid in range(total):
        writer.append(
            text=sc.text(vid),
            author=sc.author(vid),
            channel=sc.channel(vid),
            url=sc.url(vid),
            media_path=sc.media_path(vid),
            value=sc.value(vid),
            tags=sc.tags(vid),
            timestamp=sc.timestamp(vid),
        )
    if not writer.finalize():
        new_base.unlink(missing_ok=True)
        return {"compacted": False, "reason": "finalize failed"}

    new_size = new_base.stat().st_size

    # Collect old file names for cleanup
    old_files = [shard_dir / f["name"] for f in manifest["files"]]

    # Atomic swap: rename new base into place, write new manifest
    final_base = shard_dir / "sidecar.ehs"
    new_base.rename(final_base)
    write_manifest(shard_dir, [{"name": "sidecar.ehs", "n_vectors": total}])

    # Unlink old delta files (base was overwritten by rename)
    for f in old_files:
        if f.name != "sidecar.ehs" and f.exists():
            f.unlink()

    elapsed = time.perf_counter() - t0
    return {
        "compacted": True,
        "n_vectors": total,
        "n_segments_merged": len(old_files),
        "new_size_bytes": new_size,
        "elapsed_s": round(elapsed, 3),
    }
