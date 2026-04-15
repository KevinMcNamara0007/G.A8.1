"""Round-trip validation for migrated sidecar.ehs files.

For each OUT/shard_*/sidecar.ehs, read every record and diff against the
original JSON sidecars in shard/meta/. Strings must be byte-equal; timestamps
must be numerically equal after the same ISO->ms conversion used by the
migrator.

Run:  python3 validate_sidecars.py [OUT_DIR]
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path("/Users/stark/Quantum_Computing_Lab")
DEFAULT_OUT = REPO_ROOT / "OUT"
EHC_BUILD  = REPO_ROOT / "EHC/build/bindings/python"

sys.path.insert(0, str(EHC_BUILD))
import ehc  # noqa: E402


def iso_to_ms(s: str) -> int:
    if not s:
        return 0
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def validate_shard(shard_dir: Path) -> dict:
    meta_dir = shard_dir / "meta"
    ehs_path = shard_dir / "sidecar.ehs"

    with (meta_dir / "texts.json").open() as f:        texts = json.load(f)
    with (meta_dir / "authors.json").open() as f:      authors = json.load(f)
    with (meta_dir / "tags.json").open() as f:         tags_raw = json.load(f)
    with (meta_dir / "channels.json").open() as f:     channels = json.load(f)
    with (meta_dir / "timestamps.json").open() as f:   timestamps = json.load(f)
    with (meta_dir / "media_paths.json").open() as f:  media_paths = json.load(f)
    with (meta_dir / "urls.json").open() as f:         urls = json.load(f)
    with (meta_dir / "values.json").open() as f:       values = json.load(f)

    tags = [json.loads(t) if t else [] for t in tags_raw]
    ts_ms = [iso_to_ms(t) for t in timestamps]

    store = ehc.SidecarStore.open(str(ehs_path))
    if store is None:
        raise RuntimeError(f"SidecarStore.open returned None for {ehs_path}")

    n = store.n_vectors()
    if n != len(texts):
        raise RuntimeError(f"{shard_dir.name}: n_vectors {n} != {len(texts)}")

    mismatches = 0
    first_mismatch: str | None = None

    def fail(field: str, i: int, want, got):
        nonlocal mismatches, first_mismatch
        mismatches += 1
        if first_mismatch is None:
            first_mismatch = (f"{shard_dir.name}:{i} {field} "
                              f"want={want!r} got={got!r}")

    for i in range(n):
        if store.text(i) != texts[i]:           fail("text", i, texts[i], store.text(i))
        if store.author(i) != authors[i]:       fail("author", i, authors[i], store.author(i))
        if store.channel(i) != channels[i]:     fail("channel", i, channels[i], store.channel(i))
        if store.url(i) != urls[i]:             fail("url", i, urls[i], store.url(i))
        if store.media_path(i) != media_paths[i]:
            fail("media_path", i, media_paths[i], store.media_path(i))
        if store.value(i) != values[i]:         fail("value", i, values[i], store.value(i))
        if store.tags(i) != tags[i]:            fail("tags", i, tags[i], store.tags(i))
        if store.timestamp(i) != ts_ms[i]:      fail("timestamp", i, ts_ms[i], store.timestamp(i))

    return {
        "shard": shard_dir.name,
        "n_records": n,
        "mismatches": mismatches,
        "first_mismatch": first_mismatch,
    }


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    shards = sorted(p for p in out_dir.iterdir()
                    if p.is_dir() and p.name.startswith("shard_")
                    and (p / "sidecar.ehs").exists())
    if not shards:
        print(f"No shard_*/sidecar.ehs under {out_dir}", file=sys.stderr)
        return 1

    print(f"Validating {len(shards)} shards from {out_dir}")
    t_start = time.perf_counter()
    total_rec = 0
    total_mismatch = 0
    failing_shards: list[str] = []
    for shard in shards:
        r = validate_shard(shard)
        total_rec      += r["n_records"]
        total_mismatch += r["mismatches"]
        flag = "OK" if r["mismatches"] == 0 else f"FAIL ({r['mismatches']})"
        print(f"  {r['shard']}  n={r['n_records']:>6}  {flag}")
        if r["mismatches"]:
            failing_shards.append(r["shard"])
            print(f"    first: {r['first_mismatch']}")

    elapsed = time.perf_counter() - t_start
    print()
    print(f"TOTAL shards={len(shards)} records={total_rec}  "
          f"mismatches={total_mismatch}  wall={elapsed:.1f}s")
    if failing_shards:
        print(f"FAILED: {failing_shards}")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
