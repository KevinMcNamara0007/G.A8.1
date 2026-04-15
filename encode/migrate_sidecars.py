"""Migrate OUT/shard_*/meta/*.json sidecars to sidecar.ehs (EHS1) format.

Reads the 8 JSON sidecars per shard and writes one sidecar.ehs per shard via
the C++ SidecarWriter nanobind binding. Tags are stored in the JSON as
double-encoded strings ('["a","b"]'), so each row is json.loads()-ed once
before append(). Timestamps arrive as ISO-8601 UTC strings and are converted
to int64 epoch milliseconds.

Run:  python3 migrate_sidecars.py [OUT_DIR]
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


COLUMNS = ("texts", "authors", "tags", "channels",
           "timestamps", "media_paths", "urls", "values")


def iso_to_ms(s: str) -> int:
    """ISO-8601 UTC string -> epoch milliseconds."""
    if not s:
        return 0
    # fromisoformat handles trailing 'Z' only on 3.11+; normalize.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def load_columns(meta_dir: Path) -> dict[str, list]:
    """Load all 8 sidecar JSONs for a shard and return parallel arrays."""
    cols: dict[str, list] = {}
    for name in COLUMNS:
        with (meta_dir / f"{name}.json").open("r", encoding="utf-8") as f:
            cols[name] = json.load(f)

    n = len(cols["texts"])
    for name in COLUMNS:
        if len(cols[name]) != n:
            raise ValueError(
                f"{meta_dir}: column {name} has {len(cols[name])} rows, "
                f"expected {n}")

    # tags is a list of JSON strings; parse each to list[str].
    cols["tags"] = [json.loads(t) if t else [] for t in cols["tags"]]
    # timestamps is a list of ISO strings; convert to int64 ms.
    cols["timestamps"] = [iso_to_ms(t) for t in cols["timestamps"]]
    return cols


def migrate_shard(shard_dir: Path) -> dict:
    """Convert one shard's JSON sidecars to sidecar.ehs. Returns stats."""
    meta_dir = shard_dir / "meta"
    out_path = shard_dir / "sidecar.ehs"

    t0 = time.perf_counter()
    cols = load_columns(meta_dir)
    n = len(cols["texts"])

    writer = ehc.SidecarWriter(str(out_path))
    for i in range(n):
        writer.append(
            text=cols["texts"][i],
            author=cols["authors"][i],
            channel=cols["channels"][i],
            url=cols["urls"][i],
            media_path=cols["media_paths"][i],
            value=cols["values"][i],
            tags=cols["tags"][i],
            timestamp=cols["timestamps"][i],
        )
    ok = writer.finalize()
    if not ok:
        raise RuntimeError(f"finalize() failed for {out_path}")
    elapsed = time.perf_counter() - t0

    json_bytes = sum((meta_dir / f"{c}.json").stat().st_size for c in COLUMNS)
    ehs_bytes  = out_path.stat().st_size
    return {
        "shard": shard_dir.name,
        "n_records": n,
        "elapsed_s": elapsed,
        "json_bytes": json_bytes,
        "ehs_bytes": ehs_bytes,
        "out_path": str(out_path),
    }


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    shards = sorted(p for p in out_dir.iterdir()
                    if p.is_dir() and p.name.startswith("shard_"))
    if not shards:
        print(f"No shards found under {out_dir}", file=sys.stderr)
        return 1

    print(f"Migrating {len(shards)} shards from {out_dir}")
    total_json = 0
    total_ehs  = 0
    total_rec  = 0
    t_start    = time.perf_counter()
    for shard in shards:
        try:
            s = migrate_shard(shard)
        except Exception as e:
            print(f"FAIL {shard.name}: {e}", file=sys.stderr)
            return 2
        total_json += s["json_bytes"]
        total_ehs  += s["ehs_bytes"]
        total_rec  += s["n_records"]
        print(f"  {s['shard']}  n={s['n_records']:>6}  "
              f"json={s['json_bytes']/1e6:>7.2f}MB  "
              f"ehs={s['ehs_bytes']/1e6:>7.2f}MB  "
              f"{s['elapsed_s']*1000:>7.1f}ms")

    elapsed = time.perf_counter() - t_start
    ratio   = total_ehs / max(total_json, 1)
    print()
    print(f"TOTAL shards={len(shards)} records={total_rec}  "
          f"json={total_json/1e9:.3f}GB  ehs={total_ehs/1e9:.3f}GB  "
          f"ratio={ratio:.3f}  wall={elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
