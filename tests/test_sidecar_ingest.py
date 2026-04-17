"""Tests for sidecar delta ingest + compaction (phases c + d).

Exercises:
  - Delta writes via SidecarWriter + manifest updates
  - ShardSidecar multi-segment reads
  - Compaction trigger + merge
  - Concurrent-read safety (old mmap stays valid after compaction)
  - Crash recovery (orphan .new cleanup)
  - 10K records across N flushes with query-time retrieval
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "decode"))
for _d in (2, 3, 4):
    _ehc = Path(__file__).resolve().parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _ehc.exists():
        sys.path.insert(0, str(_ehc))
        break
import ehc
from sidecar_utils import (ShardSidecar, write_manifest, read_manifest,
                           next_delta_name, should_compact, compact_sidecar,
                           iso_to_ms, ms_to_iso)


def _make_shard(path, n, prefix="rec"):
    """Write n records to a base sidecar.ehs + manifest."""
    path.mkdir(parents=True, exist_ok=True)
    w = ehc.SidecarWriter(str(path / "sidecar.ehs"))
    for i in range(n):
        w.append(text=f"{prefix}_{i}", author=f"a{i%5}", channel="ch",
                 url="", media_path="", value=f"v_{i}",
                 tags=["x", "y"] if i % 2 else ["z"],
                 timestamp=1700000000000 + i * 1000)
    w.finalize()
    write_manifest(path, [{"name": "sidecar.ehs", "n_vectors": n}])


def _add_delta(path, n, prefix="delta"):
    """Append n records as a new delta file + update manifest."""
    delta_name = next_delta_name(path)
    w = ehc.SidecarWriter(str(path / delta_name))
    for i in range(n):
        w.append(text=f"{prefix}_{i}", author=f"d{i%3}", channel="dch",
                 url="", media_path="", value=f"dv_{i}",
                 tags=["d"], timestamp=1800000000000 + i * 1000)
    w.finalize()
    manifest = read_manifest(path)
    manifest["files"].append({"name": delta_name, "n_vectors": n})
    write_manifest(path, manifest["files"])


def test_single_delta_read():
    """Base + 1 delta, verify reads across boundary."""
    tmp = Path(tempfile.mkdtemp(prefix="ehs_c_"))
    try:
        _make_shard(tmp, 10, prefix="base")
        _add_delta(tmp, 5, prefix="d1")

        sc = ShardSidecar.open_dir(tmp)
        assert sc.n_vectors() == 15
        assert sc.text(0) == "base_0"
        assert sc.text(9) == "base_9"
        assert sc.text(10) == "d1_0"
        assert sc.text(14) == "d1_4"
        assert sc.author(10) == "d0"
        assert sc.tags(10) == ["d"]
        print("test_single_delta_read PASSED")
    finally:
        shutil.rmtree(tmp)


def test_multiple_deltas():
    """Base + 3 deltas, verify all segments."""
    tmp = Path(tempfile.mkdtemp(prefix="ehs_c_"))
    try:
        _make_shard(tmp, 20)
        _add_delta(tmp, 5, prefix="d1")
        _add_delta(tmp, 3, prefix="d2")
        _add_delta(tmp, 7, prefix="d3")

        sc = ShardSidecar.open_dir(tmp)
        assert sc.n_vectors() == 35
        assert sc.text(19) == "rec_19"
        assert sc.text(20) == "d1_0"
        assert sc.text(25) == "d2_0"
        assert sc.text(28) == "d3_0"
        assert sc.text(34) == "d3_6"
        print("test_multiple_deltas PASSED")
    finally:
        shutil.rmtree(tmp)


def test_compaction_merges_all():
    """Compaction merges base + deltas into a single base."""
    tmp = Path(tempfile.mkdtemp(prefix="ehs_d_"))
    try:
        _make_shard(tmp, 100)
        _add_delta(tmp, 30, prefix="d1")
        _add_delta(tmp, 20, prefix="d2")

        m_before = read_manifest(tmp)
        assert len(m_before["files"]) == 3

        cr = compact_sidecar(tmp)
        assert cr["compacted"]
        assert cr["n_vectors"] == 150
        assert cr["n_segments_merged"] == 3

        m_after = read_manifest(tmp)
        assert len(m_after["files"]) == 1
        assert m_after["files"][0]["n_vectors"] == 150

        # Deltas cleaned up
        assert not list(tmp.glob("sidecar.delta.*.ehs"))

        # Reads still correct
        sc = ShardSidecar.open_dir(tmp)
        assert sc.n_vectors() == 150
        assert sc.text(0) == "rec_0"
        assert sc.text(99) == "rec_99"
        assert sc.text(100) == "d1_0"
        assert sc.text(130) == "d2_0"
        assert sc.text(149) == "d2_19"
        print("test_compaction_merges_all PASSED")
    finally:
        shutil.rmtree(tmp)


def test_compaction_threshold():
    """should_compact returns False when deltas are small relative to base."""
    tmp = Path(tempfile.mkdtemp(prefix="ehs_d_"))
    try:
        _make_shard(tmp, 10000)
        _add_delta(tmp, 1, prefix="tiny")  # ~1 record vs 10K

        assert not should_compact(tmp, ratio_threshold=0.1)

        # Add enough deltas to trigger
        _add_delta(tmp, 5000, prefix="big")
        assert should_compact(tmp, ratio_threshold=0.1)
        print("test_compaction_threshold PASSED")
    finally:
        shutil.rmtree(tmp)


def test_crash_recovery_orphan_new():
    """Orphan .new file from crashed compaction gets cleaned up."""
    tmp = Path(tempfile.mkdtemp(prefix="ehs_d_"))
    try:
        _make_shard(tmp, 10)
        (tmp / "sidecar.ehs.new").write_bytes(b"garbage")

        # compact should clean up orphan
        cr = compact_sidecar(tmp)
        assert not (tmp / "sidecar.ehs.new").exists()
        print("test_crash_recovery_orphan_new PASSED")
    finally:
        shutil.rmtree(tmp)


def test_10k_records_across_flushes():
    """Ingest 10K records across 10 flushes, verify every record readable."""
    tmp = Path(tempfile.mkdtemp(prefix="ehs_cd_"))
    try:
        flush_size = 1000
        n_flushes = 10
        total = flush_size * n_flushes

        # First flush creates base
        _make_shard(tmp, flush_size, prefix="f0")

        # Remaining 9 flushes create deltas
        for fi in range(1, n_flushes):
            _add_delta(tmp, flush_size, prefix=f"f{fi}")

        m = read_manifest(tmp)
        assert len(m["files"]) == n_flushes

        sc = ShardSidecar.open_dir(tmp)
        assert sc.n_vectors() == total

        # Verify every record
        for fi in range(n_flushes):
            base = fi * flush_size
            for i in range(flush_size):
                vid = base + i
                expected = f"f{fi}_{i}"
                actual = sc.text(vid)
                assert actual == expected, \
                    f"vid {vid}: expected {expected!r}, got {actual!r}"

        print(f"test_10k_records_across_flushes PASSED — {total} records verified")

        # Compact and re-verify
        cr = compact_sidecar(tmp)
        assert cr["compacted"]
        assert cr["n_vectors"] == total

        sc2 = ShardSidecar.open_dir(tmp)
        for fi in range(n_flushes):
            base = fi * flush_size
            for i in [0, flush_size // 2, flush_size - 1]:
                vid = base + i
                assert sc2.text(vid) == f"f{fi}_{i}"

        print(f"  Post-compaction spot-check OK")
    finally:
        shutil.rmtree(tmp)


def test_concurrent_read_during_compaction():
    """Old ShardSidecar remains valid after compaction replaces files."""
    tmp = Path(tempfile.mkdtemp(prefix="ehs_d_"))
    try:
        _make_shard(tmp, 50)
        _add_delta(tmp, 25, prefix="d1")

        # Open reader BEFORE compaction
        sc_before = ShardSidecar.open_dir(tmp)
        assert sc_before.n_vectors() == 75
        assert sc_before.text(0) == "rec_0"
        assert sc_before.text(50) == "d1_0"

        # Compact
        compact_sidecar(tmp)

        # Old reader still works (mmap stays valid on POSIX)
        assert sc_before.text(0) == "rec_0"
        assert sc_before.text(50) == "d1_0"

        # New reader sees compacted view
        sc_after = ShardSidecar.open_dir(tmp)
        assert sc_after.n_vectors() == 75
        assert sc_after.text(0) == "rec_0"
        assert sc_after.text(50) == "d1_0"
        print("test_concurrent_read_during_compaction PASSED")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    test_single_delta_read()
    test_multiple_deltas()
    test_compaction_merges_all()
    test_compaction_threshold()
    test_crash_recovery_orphan_new()
    test_10k_records_across_flushes()
    test_concurrent_read_during_compaction()
    print("\n=== ALL TESTS PASSED ===")
