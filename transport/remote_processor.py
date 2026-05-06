"""
G.A8.1 — M3 Entangled DC remote processor (thin first cut).

Stateless similarity service. Holds encoded VSAs in memory; runs BSC
similarity on demand; returns ranked (shard_id, slot_id, score) tuples.

CRITICAL: this process never holds the codebook, never holds inverted
indices keyed on symbol, never holds source content. Its inputs are
sparse ternary VSAs and shard/slot IDs only.

Profile pinning (cfg.REMOTE_PROFILE_PIN):
  off      - never pin
  session  - first query in a session pins (D, k, source_hash); reject divergence
  strict   - first query EVER pins; reject divergence across all sessions

The processor exposes a tiny WSGI app via wsgiref so tests and the
edge_client can run it in-process without a FastAPI dependency. In
production this would sit behind an ASGI server (uvicorn) with TLS 1.3
termination handled at the proxy or by the runtime.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from wsgiref.simple_server import WSGIServer, make_server

import numpy as np

from .wire import (
    ProfileMetadata,
    QueryRequest,
    QueryResponse,
    from_b64_ternary,
    topk_against,
)


@dataclass
class _SessionState:
    pinned_profile: Optional[ProfileMetadata] = None
    query_count: int = 0


@dataclass
class RemoteProcessorConfig:
    pin_mode: str = "session"  # off | session | strict


class RemoteProcessor:
    """In-memory shard store + similarity service.

    Thread-safe: a single lock guards the shard store and session map.
    The thin-cut does not partition by shard for parallel scoring; if
    that becomes a bottleneck, swap topk_against for a per-shard pool.
    """

    def __init__(self, config: Optional[RemoteProcessorConfig] = None) -> None:
        self.config = config or RemoteProcessorConfig()
        self._lock = threading.Lock()
        # shard_id -> list of (slot_id, ternary vector)
        self._shards: Dict[int, List[Tuple[int, np.ndarray]]] = {}
        self._sessions: Dict[str, _SessionState] = {}
        self._global_pin: Optional[ProfileMetadata] = None

    # ── Shard ingestion ──────────────────────────────────
    def load_shard(self, shard_id: int, vectors: List[Tuple[int, np.ndarray]]) -> None:
        """Push a shard's encoded VSAs into the in-memory store.

        In production, this is the one-time corpus upload step that
        moves encoded VSAs from the edge encoder to the remote
        processor. The remote never sees decoded content; vectors
        arrive already in the ternary substrate.
        """
        with self._lock:
            self._shards[int(shard_id)] = [(int(sl), np.asarray(v, dtype=np.int8))
                                           for sl, v in vectors]

    def stats(self) -> dict:
        with self._lock:
            return {
                "shards": len(self._shards),
                "vectors": sum(len(v) for v in self._shards.values()),
                "sessions": len(self._sessions),
                "global_pin": self._global_pin.to_dict() if self._global_pin else None,
                "pin_mode": self.config.pin_mode,
            }

    # ── Profile pin enforcement ──────────────────────────
    def _check_and_pin(self, session_id: str, profile: ProfileMetadata) -> None:
        mode = self.config.pin_mode
        if mode == "off":
            return

        with self._lock:
            session = self._sessions.setdefault(session_id, _SessionState())

            if mode == "strict":
                if self._global_pin is None:
                    self._global_pin = profile
                elif not _profiles_match(self._global_pin, profile):
                    raise PinViolation(
                        f"strict pin: incoming profile {profile.to_dict()} "
                        f"differs from pinned {self._global_pin.to_dict()}"
                    )

            if session.pinned_profile is None:
                session.pinned_profile = profile
            elif not _profiles_match(session.pinned_profile, profile):
                raise PinViolation(
                    f"session {session_id}: incoming profile "
                    f"{profile.to_dict()} differs from pinned "
                    f"{session.pinned_profile.to_dict()}"
                )
            session.query_count += 1

    # ── Query path ───────────────────────────────────────
    def handle_query(self, req: QueryRequest) -> QueryResponse:
        self._check_and_pin(req.session_id, req.profile)

        query_vec = from_b64_ternary(req.query_vsa_b64)
        if query_vec.shape[0] != req.profile.dim:
            raise PinViolation(
                f"query VSA dim {query_vec.shape[0]} != declared profile dim {req.profile.dim}"
            )

        # Materialize the candidate iterable. Apply optional shard filter.
        with self._lock:
            shards = (set(req.shard_filter) if req.shard_filter
                      else set(self._shards.keys()))
            candidates: List[Tuple[int, int, np.ndarray]] = []
            for sid in shards:
                for slot_id, vec in self._shards.get(sid, []):
                    if vec.shape[0] != query_vec.shape[0]:
                        # Skip vectors with mismatched D — should not happen if
                        # the loader validated; this is a belt-and-braces guard.
                        continue
                    candidates.append((sid, slot_id, vec))

        hits = topk_against(query_vec, candidates, req.top_k)
        return QueryResponse(hits=hits, server_profile=req.profile)


def _profiles_match(a: ProfileMetadata, b: ProfileMetadata) -> bool:
    if a.dim != b.dim or a.k != b.k:
        return False
    if a.source_hash and b.source_hash and a.source_hash != b.source_hash:
        return False
    return True


class PinViolation(Exception):
    """Raised when an incoming query disagrees with a pinned profile."""


# ── WSGI front end ──────────────────────────────────────
def make_wsgi_app(processor: RemoteProcessor):
    """Build a tiny WSGI app exposing /v1/query and /v1/health.

    Production deployments terminate TLS 1.3 ahead of this — the app
    speaks plain HTTP and assumes the proxy enforces transport policy.
    The X-Subspace-Session header carries the session id; clients
    should rotate it per cfg.BASIS_WINDOW_SECONDS.
    """
    def app(environ, start_response):
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "GET")

        if path == "/v1/health":
            return _json(start_response, "200 OK", processor.stats())

        if path == "/v1/query" and method == "POST":
            try:
                length = int(environ.get("CONTENT_LENGTH") or 0)
                body = environ["wsgi.input"].read(length).decode("utf-8")
                req = QueryRequest.from_dict(json.loads(body))
                resp = processor.handle_query(req)
                return _json(start_response, "200 OK", resp.to_dict())
            except PinViolation as e:
                return _json(start_response, "409 Conflict", {"error": str(e)})
            except (ValueError, KeyError) as e:
                return _json(start_response, "400 Bad Request", {"error": str(e)})

        return _json(start_response, "404 Not Found", {"error": "not found"})

    return app


def _json(start_response, status: str, body: dict):
    payload = json.dumps(body).encode("utf-8")
    start_response(status, [
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(payload))),
    ])
    return [payload]


def serve(processor: RemoteProcessor, host: str = "127.0.0.1",
          port: int = 8443) -> WSGIServer:
    """Convenience: start a foreground HTTP server. Blocks."""
    server = make_server(host, port, make_wsgi_app(processor))
    server.serve_forever()
    return server
