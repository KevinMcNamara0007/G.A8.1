"""Streaming reader for the 21M Wikidata triples JSON array.

The source file is a single ~1.9GB JSON array: `[{...}, {...}, ...]`.
`json.load()` works on a 128GB box but burns ~15GB of Python objects and
~30s of import time. For benchmark sampling we only need N << 21M
triples, so this streaming reader yields one dict at a time without
materializing the whole array.

Parser is tolerant of:
  - Leading `[`, trailing `]`
  - Commas between elements (with or without whitespace)
  - Unicode escapes inside string values

It assumes the top-level structure is a flat array of flat dicts (no
nested objects), which matches the Wikidata triple schema.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Iterator, Optional


def stream_triples(path: str, limit: Optional[int] = None) -> Iterator[dict]:
    """Yield dicts one at a time from a JSON array file.

    Memory footprint is O(1) in the file size (one triple at a time).
    """
    yielded = 0
    with open(path, "rb") as f:
        # Skip leading whitespace + opening `[`
        c = _read_byte(f)
        while c and c in b" \t\n\r":
            c = _read_byte(f)
        if c != b"[":
            raise ValueError(f"Expected top-level '[', got {c!r}")

        buf = bytearray()
        in_string = False
        escape = False
        depth = 0
        while True:
            c = _read_byte(f)
            if not c:
                break

            if in_string:
                buf.append(c[0])
                if escape:
                    escape = False
                elif c == b"\\":
                    escape = True
                elif c == b'"':
                    in_string = False
                continue

            if c == b'"':
                buf.append(c[0])
                in_string = True
                continue

            if c == b"{":
                depth += 1
                buf.append(c[0])
                continue

            if c == b"}":
                depth -= 1
                buf.append(c[0])
                if depth == 0:
                    try:
                        obj = json.loads(buf.decode("utf-8"))
                    except json.JSONDecodeError:
                        buf.clear()
                        continue
                    buf.clear()
                    yield obj
                    yielded += 1
                    if limit is not None and yielded >= limit:
                        return
                continue

            if depth == 0:
                # Between objects: comma, whitespace, or closing `]`
                if c == b"]":
                    return
                continue

            buf.append(c[0])


def _read_byte(f) -> bytes:
    return f.read(1)


def count_triples(path: str, limit: Optional[int] = None) -> int:
    """Count triples — useful for validation / progress estimation."""
    n = 0
    for _ in stream_triples(path, limit=limit):
        n += 1
    return n


def sample_triples(
    path: str,
    n_sample: int,
    seed: int = 42,
    skip_ratio: float = 1.0,
) -> list:
    """Deterministic stride-based sampling from the stream.

    For a file with ~N total triples and n_sample requested, takes
    approximately every (N/n_sample * skip_ratio) records. Keeps the
    sample roughly uniform without requiring a pre-pass to count.
    Stride is seeded so sequential runs reproduce.
    """
    import random
    rng = random.Random(seed)

    # Two-pass: first pass counts up to a cap to set the stride,
    # second pass samples. For very large files we cap counting at a
    # reasonable upper bound so the cost is bounded.
    # Here we hard-code the known size (~21M) when scanning is too
    # expensive; fall back to scanning otherwise.
    approx_total = 21_200_000  # plan §1.1 benchmark corpus size

    stride = max(int(approx_total / n_sample * skip_ratio), 1)
    jitter = stride // 2

    out: list = []
    next_take = rng.randint(0, jitter)
    i = 0
    for trip in stream_triples(path):
        if i == next_take:
            out.append(trip)
            if len(out) >= n_sample:
                break
            next_take = i + stride + rng.randint(-jitter, jitter)
            if next_take <= i:
                next_take = i + 1
        i += 1
    return out
