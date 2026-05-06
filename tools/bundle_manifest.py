"""
G.A8.1 — Bundle manifest schema.

A bundle is a tar archive containing:
  manifest.json          ← schema below
  manifest.sig           ← HMAC-SHA-256(manifest.json) using KMS-derived key
  payload/<files>        ← everything from INDEX_PATH at export time

The manifest has the same source-of-truth role as a TLS certificate:
file hashes are computed at export time, the manifest pins them, the
signature pins the manifest, and import refuses to extract any file
that doesn't match its manifest entry.

Profile gate: when cfg.BUNDLE_INCLUDE_PROFILE is True (default),
export aborts if corpus_profile.json is missing from the source dir,
and import aborts if the manifest's payload list does not contain it.
Edge has no corpus to re-profile against, so the profile must travel
with the bundle.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


MANIFEST_VERSION = 1


@dataclass
class FileEntry:
    """One file in the bundle payload."""
    path: str           # relative path under payload/
    size: int
    sha256: str         # hex
    mode: int = 0o644


@dataclass
class Manifest:
    """Top-level bundle manifest. Serialized to JSON, signed separately."""
    version: int = MANIFEST_VERSION
    created_at: str = ""                  # ISO 8601 UTC
    bundle_id: str = ""                   # 16-byte hex random; identifies this bundle
    delta_base: str = ""                  # bundle_id of previous bundle, if delta
    source_index_path: str = ""           # purely informational
    signing_key_ref: str = ""             # KMS ref used to derive the HMAC key
    encryption_key_ref: str = ""          # reserved; payload encryption not in thin-cut
    profile_present: bool = False         # corpus_profile.json was included
    files: List[FileEntry] = field(default_factory=list)

    def to_json(self) -> str:
        """Canonical JSON for signing. Sorted keys, no whitespace variance."""
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> "Manifest":
        d = json.loads(raw)
        files = [FileEntry(**f) for f in d.pop("files", [])]
        return cls(files=files, **d)

    def file_index(self) -> Dict[str, FileEntry]:
        return {f.path: f for f in self.files}


def hash_file(path: Path, *, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            buf = fh.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def sign_manifest(manifest_json: str, key: bytes) -> bytes:
    """HMAC-SHA-256 over the canonical manifest JSON."""
    return hmac.new(key, manifest_json.encode("utf-8"), hashlib.sha256).digest()


def verify_manifest(manifest_json: str, signature: bytes, key: bytes) -> bool:
    """Constant-time signature comparison."""
    expected = sign_manifest(manifest_json, key)
    return hmac.compare_digest(expected, signature)


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def random_bundle_id() -> str:
    import os
    return os.urandom(16).hex()


def collect_files(root: Path, *, skip_names: Optional[set] = None) -> List[FileEntry]:
    """Walk root, hash each file, return FileEntry list with relative paths."""
    skip_names = skip_names or {".DS_Store", "__pycache__"}
    entries: List[FileEntry] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in skip_names for part in p.parts):
            continue
        rel = p.relative_to(root).as_posix()
        entries.append(FileEntry(
            path=rel,
            size=p.stat().st_size,
            sha256=hash_file(p),
            mode=p.stat().st_mode & 0o777,
        ))
    return entries


PROFILE_FILENAME = "corpus_profile.json"


def has_profile(entries: List[FileEntry]) -> bool:
    return any(e.path == PROFILE_FILENAME for e in entries)
