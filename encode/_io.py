"""Source-format iteration helper used by both encoders.

Auto-detects and streams records from:
  - **JSONL** — one JSON object per line (the default staging format)
  - **JSON array** — a single `[{...}, {...}, ...]` file (Wikidata/DBpedia
    dumps ship this way; a 2GB single-line file would OOM a naive
    `json.load`).

Format is detected by peeking the first non-whitespace character. Both
paths use constant memory.

Public API
==========
    iter_json_records(source) -> Iterator[dict]
    count_records(source)     -> int

Both encoders (`encode_triples`, `encode_unstructured`) route through
`iter_json_records`, so any new source-JSON-array corpus works without
a manual pre-conversion step.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator


def iter_json_records(source: Path | str) -> Iterator[dict]:
    """Yield parsed dict records from `source`, auto-detecting format."""
    source = Path(source)
    with open(source, "r", encoding="utf-8", errors="replace") as f:
        first = ""
        while True:
            c = f.read(1)
            if not c:
                return
            if not c.isspace():
                first = c
                break
        if first == "[":
            yield from _stream_json_array(f)
        elif first == "{":
            yield from _stream_jsonl(f, first)
        else:
            raise ValueError(
                f"{source}: unsupported format — first non-whitespace "
                f"char is {first!r}. Expected '[' (JSON array) or "
                f"'{{' (JSONL)."
            )


def count_records(source: Path | str) -> int:
    """Fast count without yielding records upstream. JSONL uses a
    line-count shortcut; JSON arrays stream-parse (same cost either way
    once the file is in page cache)."""
    source = Path(source)
    with open(source, "rb") as f:
        first = b""
        while True:
            c = f.read(1)
            if not c:
                return 0
            if not c.isspace():
                first = c
                break
        if first == b"{":
            f.seek(0)
            return sum(1 for line in f if line.strip())
    return sum(1 for _ in iter_json_records(source))


def _stream_json_array(f, chunk: int = 1 << 20) -> Iterator[dict]:
    """Stream records out of a JSON array. Caller has already consumed
    the leading '['. Uses `JSONDecoder.raw_decode` to parse one record
    at a time out of a rolling buffer — constant memory regardless of
    file size."""
    dec = json.JSONDecoder()
    buf = ""
    while True:
        new = f.read(chunk)
        if not new and not buf.strip():
            return
        buf = (buf + new).lstrip(", \n\t\r")
        if buf.startswith("]"):
            return
        while buf:
            buf = buf.lstrip(", \n\t\r")
            if not buf or buf.startswith("]"):
                return
            try:
                obj, idx = dec.raw_decode(buf)
            except json.JSONDecodeError:
                if not new:
                    raise
                break
            yield obj
            buf = buf[idx:]


def _stream_jsonl(f, prefix: str) -> Iterator[dict]:
    """JSONL iterator. `prefix` is the first char we already read during
    format detection."""
    first_line = (prefix + f.readline()).strip()
    if first_line:
        try:
            yield json.loads(first_line)
        except json.JSONDecodeError:
            pass
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue
