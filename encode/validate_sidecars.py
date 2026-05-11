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

    store = ehc.SidecarStore.open(str(ehs_path))
    if store is None:
        raise RuntimeError(f"SidecarStore.open returned None for {ehs_path}")
    n = store.n_vectors()

    mismatches = 0
    first_mismatch: str | None = None

    def fail(field: str, i: int, want, got):
        nonlocal mismatches, first_mismatch
        mismatches += 1
        if first_mismatch is None:
            first_mismatch = (f"{shard_dir.name}:{i} {field} "
                              f"want={want!r} got={got!r}")

    # Validate one JSON column at a time so peak per-shard memory is
    # one column instead of all eight simultaneously.
    columns = [
        ("text",       "texts.json",       store.text,       lambda v: v),
        ("author",     "authors.json",     store.author,     lambda v: v),
        ("channel",    "channels.json",    store.channel,    lambda v: v),
        ("url",        "urls.json",        store.url,        lambda v: v),
        ("media_path", "media_paths.json", store.media_path, lambda v: v),
        ("value",      "values.json",      store.value,      lambda v: v),
        ("tags",       "tags.json",        store.tags,       lambda v: json.loads(v) if v else []),
        ("timestamp",  "timestamps.json",  store.timestamp,  iso_to_ms),
    ]

    for field, fname, getter, transform in columns:
        with (meta_dir / fname).open() as f:
            col = json.load(f)
        # Length check on the first column doubles as the n_vectors check.
        if field == "text" and n != len(col):
            raise RuntimeError(f"{shard_dir.name}: n_vectors {n} != {len(col)}")
        for i in range(n):
            want = transform(col[i])
            got = getter(i)
            if got != want:
                fail(field, i, want, got)
        del col

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
