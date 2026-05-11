"""
G.A8.1 — M3 Entangled DC ternary VSA wire format.

A sparse ternary VSA carries:
  - dimension D                  (uint32; redundant with session profile, included for sanity)
  - non-zero count nnz           (uint32)
  - (index, sign) pairs           (nnz × {uint32 index, int8 sign ∈ {-1, +1}})

Encoding is little-endian, dense over the nnz pairs. Zero entries are
not transmitted; sign tells us which of {-1, +1} a non-zero index holds.

This is the only place in G.A8.1 that knows the on-the-wire layout for
ternary vectors. Both edge_client and remote_processor depend on it.

The wire envelope (request and response payloads) is JSON. Vectors
are base64-encoded so they ride alongside session metadata cleanly.
"""

from __future__ import annotations

import base64
import struct
from dataclasses import dataclass, field
from typing import Iterable, List, Sequence, Tuple

import numpy as np


# ── Sparse-ternary serialization ─────────────────────────
_HEADER = struct.Struct("<II")  # D, nnz


def encode_ternary(vec: np.ndarray) -> bytes:
    """Pack a dense ternary numpy vector into the compact sparse layout.

    `vec` must contain only values in {-1, 0, +1} (or numerically equal).
    Validates and raises on out-of-range entries — silent truncation here
    would be a security issue, since the VSA crossing the trust boundary
    must match what the codebook will decode against.
    """
    if vec.ndim != 1:
        raise ValueError("encode_ternary expects a 1-D array")
    arr = np.asarray(vec, dtype=np.int8)
    if not np.all((arr == -1) | (arr == 0) | (arr == 1)):
        raise ValueError("encode_ternary: entries must be in {-1, 0, +1}")

    nz_idx = np.nonzero(arr)[0]
    if nz_idx.size and int(nz_idx[-1]) > 0xFFFFFFFF:
        raise ValueError("dimension exceeds uint32 index range")

    out = bytearray()
    out += _HEADER.pack(int(arr.size), int(nz_idx.size))
    if nz_idx.size:
        idx_bytes = nz_idx.astype("<u4").tobytes()
        sign_bytes = arr[nz_idx].astype("i1").tobytes()
        # Interleave (idx, sign) so partial recovery on truncation stays consistent.
        interleaved = bytearray()
        for i in range(nz_idx.size):
            interleaved += idx_bytes[i * 4:(i + 1) * 4]
            interleaved += sign_bytes[i:i + 1]
        out += interleaved
    return bytes(out)


def decode_ternary(buf: bytes) -> np.ndarray:
    """Inverse of encode_ternary."""
    if len(buf) < _HEADER.size:
        raise ValueError("ternary buffer truncated")
    dim, nnz = _HEADER.unpack_from(buf, 0)
    expected = _HEADER.size + nnz * 5
    if len(buf) != expected:
        raise ValueError(
            f"ternary buffer length mismatch: expected {expected}, got {len(buf)}"
        )
    out = np.zeros(dim, dtype=np.int8)
    off = _HEADER.size
    for _ in range(nnz):
        (idx,) = struct.unpack_from("<I", buf, off)
        sign = struct.unpack_from("<b", buf, off + 4)[0]
        if idx >= dim:
            raise ValueError(f"ternary index {idx} out of range for D={dim}")
        if sign not in (-1, 1):
            raise ValueError(f"ternary sign {sign} not in {{-1, +1}}")
        out[idx] = sign
        off += 5
    return out


def b64_ternary(vec: np.ndarray) -> str:
    return base64.b64encode(encode_ternary(vec)).decode("ascii")


def from_b64_ternary(s: str) -> np.ndarray:
    return decode_ternary(base64.b64decode(s))


# ── Session profile metadata ─────────────────────────────
@dataclass
class ProfileMetadata:
    """What the edge tells the remote processor about the active corpus profile.

    The remote processor pins this on first query of a session and rejects
    later queries that diverge — protects against profile-mismatch attacks
    where the edge silently re-encodes against a different basis.
    """
    dim: int
    k: int
    source_hash: str = ""

    def to_dict(self) -> dict:
        return {"dim": int(self.dim), "k": int(self.k), "source_hash": self.source_hash}

    @classmethod
    def from_dict(cls, d: dict) -> "ProfileMetadata":
        return cls(dim=int(d["dim"]), k=int(d["k"]), source_hash=d.get("source_hash", ""))


# ── Query envelope ───────────────────────────────────────
# No nonce, MAC, or seq number on this envelope by design — confidentiality
# rests on the two-layer posture in WP v1.2 §6.3 (algebraic OTP+QNR from §1.2
# + SSH/TLS transport). Generic transport hardening here would be redundant.
@dataclass
class QueryRequest:
    """JSON wire shape for an edge → remote query."""
    session_id: str
    profile: ProfileMetadata
    query_vsa_b64: str
    top_k: int = 10
    shard_filter: List[int] = field(default_factory=list)  # empty = all shards

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "profile": self.profile.to_dict(),
            "query_vsa_b64": self.query_vsa_b64,
            "top_k": int(self.top_k),
            "shard_filter": [int(s) for s in self.shard_filter],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "QueryRequest":
        return cls(
            session_id=str(d["session_id"]),
            profile=ProfileMetadata.from_dict(d["profile"]),
            query_vsa_b64=str(d["query_vsa_b64"]),
            top_k=int(d.get("top_k", 10)),
            shard_filter=[int(s) for s in d.get("shard_filter", [])],
        )


@dataclass
class QueryHit:
    """One ranked result. The remote does NOT decode source content;
    edge looks (shard_id, slot_id) up in its local sidecar."""
    shard_id: int
    slot_id: int
    score: float


@dataclass
class QueryResponse:
    hits: List[QueryHit]
    server_profile: ProfileMetadata    # echoed back so edge can verify pin

    def to_dict(self) -> dict:
        return {
            "hits": [{"shard_id": h.shard_id, "slot_id": h.slot_id, "score": float(h.score)}
                     for h in self.hits],
            "server_profile": self.server_profile.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "QueryResponse":
        hits = [QueryHit(shard_id=int(h["shard_id"]),
                         slot_id=int(h["slot_id"]),
                         score=float(h["score"]))
                for h in d.get("hits", [])]
        return cls(hits=hits, server_profile=ProfileMetadata.from_dict(d["server_profile"]))


# ── Helpers ──────────────────────────────────────────────
def bsc_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Sign-aligned overlap, normalized by the smaller support.

    Sparse ternary vectors aren't unit-norm; this is the BSC kernel used
    elsewhere in G.A8.1 for similarity. Defined here so the remote
    processor can compute it without depending on the codebook side.
    """
    if a.shape != b.shape:
        raise ValueError("BSC similarity: shape mismatch")
    nnz_a = int(np.count_nonzero(a))
    nnz_b = int(np.count_nonzero(b))
    if nnz_a == 0 or nnz_b == 0:
        return 0.0
    overlap = float(np.sum(a.astype(np.int32) * b.astype(np.int32)))
    denom = float(min(nnz_a, nnz_b))
    return overlap / denom


def topk_against(query: np.ndarray,
                 vectors: Sequence[Tuple[int, int, np.ndarray]],
                 k: int) -> List[QueryHit]:
    """Return top-k hits by BSC similarity. `vectors` is (shard_id, slot_id, vec)."""
    scored = []
    for shard_id, slot_id, vec in vectors:
        scored.append((bsc_similarity(query, vec), shard_id, slot_id))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [QueryHit(shard_id=s, slot_id=sl, score=score)
            for score, s, sl in scored[:max(0, int(k))]]
