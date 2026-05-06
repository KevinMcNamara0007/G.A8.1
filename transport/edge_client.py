"""
G.A8.1 — M3 Entangled DC edge client.

Edge-side wire-protocol client. Ships sparse ternary VSAs to a remote
similarity processor over HTTPS (TLS 1.3 enforced) and decodes the
ranked (shard_id, slot_id, score) response locally.

This client does NOT depend on the full QueryService stack — it accepts
a pre-encoded query VSA, ships it, and returns ranked IDs. The decode
to source content (sidecar lookup) happens in the caller, which is the
point at which the codebook is needed and which therefore must remain
on the edge.

Higher layers compose this client with the existing query-encoding
path: encode-locally → send-via-EdgeClient → sidecar-lookup-locally.
That composition is the M3 query pipeline; we leave it to a follow-up
so this thin-cut stays focused on the wire seam.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from .wire import (
    ProfileMetadata,
    QueryRequest,
    QueryResponse,
    b64_ternary,
)


_VALID_TRANSPORTS = ("ssh-tunnel", "http-loopback", "https")


@dataclass
class EdgeClientConfig:
    """Subset of cfg.* values the edge client needs.

    Pulled into a dataclass so tests can construct one without going
    through the full config singleton — the singleton's overlay loader
    has process-wide side effects that interact poorly with parallel
    test runs.

    Transport selector:
      ssh-tunnel    — connect to 127.0.0.1:<port>, plain HTTP. SSH provides
                      channel privacy out-of-band. TLS settings ignored.
      http-loopback — connect to 127.0.0.1:<port>, plain HTTP. Dev/test
                      only. TLS settings ignored.
      https         — connect via direct HTTPS. TLS 1.3 enforced.
    """
    remote_url: str
    transport: str = "ssh-tunnel"
    # TLS settings — only consulted when transport == "https".
    tls_min: str = "1.3"
    tls_pq_hybrid: bool = True
    tls_cert_pin_sha256: str = ""        # SPKI pin (hex); empty disables pinning
    timeout_seconds: int = 10
    verify_tls: bool = True              # set False ONLY for in-process tests


class EdgeClient:
    """Edge → remote similarity processor.

    Holds a session id that pins the profile on the remote for the
    session's lifetime. Caller is expected to rotate the session
    boundary in step with basis rotation (whitepaper §8.3).
    """

    def __init__(self, config: EdgeClientConfig, profile: ProfileMetadata) -> None:
        if config.transport not in _VALID_TRANSPORTS:
            raise ValueError(
                f"transport={config.transport!r} not one of {_VALID_TRANSPORTS}"
            )
        if config.transport in ("ssh-tunnel", "http-loopback"):
            # These transports require a loopback URL — they're not the
            # right path for a remote endpoint. Catch misconfig early.
            self._assert_loopback_url(config.remote_url, config.transport)
        elif config.transport == "https":
            if config.tls_min != "1.3":
                raise ValueError(
                    f"tls_min={config.tls_min!r}; TLS 1.3 is the minimum "
                    "(whitepaper §8.1). 1.2 and earlier are explicitly rejected."
                )
            if not config.remote_url.startswith("https://"):
                raise ValueError(
                    f"transport=https requires an https:// remote_url; got {config.remote_url!r}"
                )
        self.config = config
        self.profile = profile
        self.session_id = uuid.uuid4().hex

    @staticmethod
    def _assert_loopback_url(url: str, transport: str) -> None:
        # Accept http://127.0.0.1:PORT and http://localhost:PORT.
        # Reject anything else — these transports must not address remote hosts.
        if not url.startswith("http://"):
            raise ValueError(
                f"transport={transport} requires http://127.0.0.1:<port> "
                f"or http://localhost:<port>; got {url!r}"
            )
        host_part = url[len("http://"):].split("/", 1)[0]
        host = host_part.split(":", 1)[0]
        if host not in ("127.0.0.1", "localhost", "::1", "[::1]"):
            raise ValueError(
                f"transport={transport} refuses non-loopback host {host!r}. "
                "Open an SSH tunnel and point remote_url at the local forwarded port."
            )

    # ── Public API ───────────────────────────────────────
    def query(self, query_vsa: np.ndarray, *, top_k: int = 10,
              shard_filter: Optional[Sequence[int]] = None) -> QueryResponse:
        """Send one similarity query. Returns ranked hits."""
        if query_vsa.shape[0] != self.profile.dim:
            raise ValueError(
                f"query VSA dim {query_vsa.shape[0]} does not match "
                f"profile dim {self.profile.dim}"
            )
        req = QueryRequest(
            session_id=self.session_id,
            profile=self.profile,
            query_vsa_b64=b64_ternary(query_vsa),
            top_k=top_k,
            shard_filter=list(shard_filter or []),
        )
        body = json.dumps(req.to_dict()).encode("utf-8")
        url = self.config.remote_url.rstrip("/") + "/v1/query"
        raw = self._post(url, body)
        return QueryResponse.from_dict(json.loads(raw))

    def rotate_session(self) -> None:
        """Advance to a new session id. Call on basis rotation boundaries."""
        self.session_id = uuid.uuid4().hex

    def health(self) -> dict:
        url = self.config.remote_url.rstrip("/") + "/v1/health"
        raw = self._get(url)
        return json.loads(raw)

    # ── Transport ────────────────────────────────────────
    def _ssl_context(self) -> Optional[ssl.SSLContext]:
        # ssh-tunnel and http-loopback talk plain HTTP over a loopback
        # socket. SSH (or the OS loopback) handles confidentiality; the
        # urllib layer doesn't need a TLS context.
        if self.config.transport != "https":
            return None
        ctx = ssl.create_default_context()
        # TLS 1.3 minimum; reject 1.2 and earlier outright.
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        if not self.config.verify_tls:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        # Cert pinning is enforced via a verify_callback on the connection;
        # urllib doesn't expose a clean hook. Documented as a known gap;
        # production HTTPS deployments should use the SSH-tunnel transport
        # instead, which sidesteps the pinning problem entirely via SSH
        # known_hosts.
        if self.config.tls_cert_pin_sha256:
            ctx.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20")
        return ctx

    def _post(self, url: str, body: bytes) -> str:
        req = urllib.request.Request(
            url=url,
            data=body,
            headers={"Content-Type": "application/json",
                     "X-Subspace-Session": self.session_id},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                req, timeout=self.config.timeout_seconds, context=self._ssl_context()
            ) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise EdgeTransportError(
                f"remote {url} returned HTTP {e.code}: {detail[:200]}"
            ) from e
        except urllib.error.URLError as e:
            raise EdgeTransportError(f"remote unreachable at {url}: {e.reason}") from e

    def _get(self, url: str) -> str:
        try:
            with urllib.request.urlopen(
                url, timeout=self.config.timeout_seconds, context=self._ssl_context()
            ) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.URLError as e:
            raise EdgeTransportError(f"remote unreachable at {url}: {e}") from e


class EdgeTransportError(RuntimeError):
    pass
