"""
M3 ternary transport tests.

End-to-end: spin up RemoteProcessor in a background thread serving over
plain HTTP (TLS is the proxy's job in production), point an EdgeClient
at it, push synthetic shards, run a query, verify the right hits come
back. Also exercises:
  - sparse-ternary wire round-trip
  - profile-pin enforcement (session and strict)
  - rejection of bad VSAs (out-of-range entries, dim mismatch)
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from wsgiref.simple_server import make_server

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from transport.wire import (                      # noqa: E402
    ProfileMetadata, decode_ternary, encode_ternary,
)
from transport.edge_client import (               # noqa: E402
    EdgeClient, EdgeClientConfig, EdgeTransportError,
)
from transport.remote_processor import (          # noqa: E402
    PinViolation, RemoteProcessor, RemoteProcessorConfig, make_wsgi_app,
)


D = 256
K = 16


def make_ternary(rng: np.random.Generator, *, dim: int = D, k: int = K) -> np.ndarray:
    v = np.zeros(dim, dtype=np.int8)
    idx = rng.choice(dim, size=k, replace=False)
    signs = rng.choice([-1, 1], size=k).astype(np.int8)
    v[idx] = signs
    return v


def _serve(app, host="127.0.0.1"):
    """Bring up a one-thread WSGI server on an ephemeral port. Returns (server, port)."""
    server = make_server(host, 0, app)  # port 0 → kernel picks
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, port


class WireFormatTest(unittest.TestCase):
    def test_round_trip_random(self):
        rng = np.random.default_rng(42)
        for _ in range(10):
            v = make_ternary(rng)
            self.assertTrue(np.array_equal(v, decode_ternary(encode_ternary(v))))

    def test_zero_vector(self):
        z = np.zeros(D, dtype=np.int8)
        self.assertTrue(np.array_equal(z, decode_ternary(encode_ternary(z))))

    def test_rejects_non_ternary(self):
        v = np.zeros(D, dtype=np.int8)
        v[0] = 2
        with self.assertRaises(ValueError):
            encode_ternary(v)

    def test_truncated_buffer(self):
        rng = np.random.default_rng(0)
        buf = encode_ternary(make_ternary(rng))
        with self.assertRaises(ValueError):
            decode_ternary(buf[:-1])


class TransportRoundTripTest(unittest.TestCase):
    def test_query_finds_seeded_vector(self):
        rng = np.random.default_rng(1)
        proc = RemoteProcessor(RemoteProcessorConfig(pin_mode="session"))

        # Build 3 shards × 5 slots of random VSAs, seed a known target.
        target = make_ternary(rng)
        for shard_id in range(3):
            slots = []
            for slot_id in range(5):
                vec = make_ternary(rng)
                slots.append((slot_id, vec))
            proc.load_shard(shard_id, slots)
        # Plant target at shard=1, slot=99.
        proc._shards[1].append((99, target))

        server, port = _serve(make_wsgi_app(proc))
        try:
            client = EdgeClient(
                EdgeClientConfig(
                    remote_url=f"http://127.0.0.1:{port}",
                    transport="http-loopback",
                ),
                ProfileMetadata(dim=D, k=K, source_hash="abc123"),
            )
            resp = client.query(target, top_k=3)
            self.assertGreaterEqual(len(resp.hits), 1)
            top = resp.hits[0]
            self.assertEqual(top.shard_id, 1)
            self.assertEqual(top.slot_id, 99)
            # Self-similarity is the maximum the BSC kernel returns.
            self.assertGreater(top.score, 0.9)
        finally:
            server.shutdown()

    def test_session_pin_rejects_dim_change(self):
        rng = np.random.default_rng(2)
        proc = RemoteProcessor(RemoteProcessorConfig(pin_mode="session"))
        proc.load_shard(0, [(0, make_ternary(rng))])

        server, port = _serve(make_wsgi_app(proc))
        try:
            client = EdgeClient(
                EdgeClientConfig(remote_url=f"http://127.0.0.1:{port}",
                                  transport="http-loopback"),
                ProfileMetadata(dim=D, k=K, source_hash="hash-A"),
            )
            client.query(make_ternary(rng), top_k=1)

            # Mutate profile dim mid-session; remote should reject (HTTP 409).
            client.profile = ProfileMetadata(dim=D, k=K, source_hash="hash-B")
            with self.assertRaises(EdgeTransportError) as ctx:
                client.query(make_ternary(rng), top_k=1)
            self.assertIn("409", str(ctx.exception))
        finally:
            server.shutdown()

    def test_pin_off_allows_divergence(self):
        rng = np.random.default_rng(3)
        proc = RemoteProcessor(RemoteProcessorConfig(pin_mode="off"))
        proc.load_shard(0, [(0, make_ternary(rng))])

        server, port = _serve(make_wsgi_app(proc))
        try:
            client = EdgeClient(
                EdgeClientConfig(remote_url=f"http://127.0.0.1:{port}",
                                  transport="http-loopback"),
                ProfileMetadata(dim=D, k=K, source_hash="hash-A"),
            )
            client.query(make_ternary(rng), top_k=1)
            client.profile = ProfileMetadata(dim=D, k=K, source_hash="hash-B")
            # Should succeed even though source_hash changed mid-session.
            resp = client.query(make_ternary(rng), top_k=1)
            self.assertEqual(len(resp.hits), 1)
        finally:
            server.shutdown()


class EdgeClientGuardTest(unittest.TestCase):
    def test_rejects_pre_tls13_under_https(self):
        # TLS 1.3 floor only applies under the https transport.
        with self.assertRaises(ValueError) as ctx:
            EdgeClient(
                EdgeClientConfig(
                    remote_url="https://example.invalid",
                    transport="https",
                    tls_min="1.2",
                ),
                ProfileMetadata(dim=D, k=K),
            )
        self.assertIn("TLS 1.3", str(ctx.exception))

    def test_rejects_dim_mismatch(self):
        client = EdgeClient(
            EdgeClientConfig(remote_url="http://127.0.0.1:1", transport="http-loopback"),
            ProfileMetadata(dim=D, k=K),
        )
        with self.assertRaises(ValueError):
            client.query(np.zeros(D + 1, dtype=np.int8))

    def test_ssh_tunnel_refuses_non_loopback(self):
        with self.assertRaises(ValueError) as ctx:
            EdgeClient(
                EdgeClientConfig(remote_url="http://remote.example.com",
                                  transport="ssh-tunnel"),
                ProfileMetadata(dim=D, k=K),
            )
        self.assertIn("loopback", str(ctx.exception))

    def test_https_refuses_http_url(self):
        with self.assertRaises(ValueError) as ctx:
            EdgeClient(
                EdgeClientConfig(remote_url="http://example.com",
                                  transport="https"),
                ProfileMetadata(dim=D, k=K),
            )
        self.assertIn("https://", str(ctx.exception))

    def test_ssh_tunnel_accepts_localhost(self):
        # Sanity: localhost (alias for 127.0.0.1) is acceptable for tunnel.
        EdgeClient(
            EdgeClientConfig(remote_url="http://localhost:18443",
                              transport="ssh-tunnel"),
            ProfileMetadata(dim=D, k=K),
        )

    def test_unknown_transport_rejected(self):
        with self.assertRaises(ValueError):
            EdgeClient(
                EdgeClientConfig(remote_url="http://127.0.0.1:1", transport="bogus"),
                ProfileMetadata(dim=D, k=K),
            )


if __name__ == "__main__":
    unittest.main()
