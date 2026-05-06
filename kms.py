"""
G.A8.1 — KMS provider abstraction.

Single seam between G.A8.1 and key material. Concrete providers:

  * NoneProvider   — disabled. Any call raises ConfigError.
  * LocalProvider  — file-rooted. Dev/test only. Reads/writes raw bytes
                     in $A81_KMS_LOCAL_DIR/<ref>.key.
  * QKeyProvider   — Mjolnir OneShot/qkey REST appliance. Calls
                     POST {QKEY_URL}/v1/key/<mode>-enhanced with
                     X-Access-Key auth and returns the derived key.

Interface (KMSProvider):
  key_for(ref, length, *, context="")  → bytes  : derive material for the named ref
  attest()                               → dict   : liveness + identity probe
  describe()                             → str    : human-readable provider summary

Callers should treat returned bytes as one-shot; do not cache.
The config_singleton drives provider selection from cfg.KMS_PROVIDER.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from config import cfg, ConfigError


# ── Interface ────────────────────────────────────────────
class KMSProvider:
    """Minimal contract every provider implements."""

    name: str = "abstract"

    def key_for(self, ref: str, length: int, *, context: str = "") -> bytes:
        raise NotImplementedError

    def attest(self) -> dict:
        raise NotImplementedError

    def describe(self) -> str:
        return self.name


# ── None ─────────────────────────────────────────────────
class NoneProvider(KMSProvider):
    name = "none"

    def key_for(self, ref: str, length: int, *, context: str = "") -> bytes:
        raise ConfigError(
            "KMS is disabled (A81_KMS_PROVIDER=none). Set provider to "
            "'local' for dev or 'qkey' for production before requesting key material."
        )

    def attest(self) -> dict:
        return {"provider": "none", "live": False}


# ── Local (dev only) ─────────────────────────────────────
class LocalProvider(KMSProvider):
    """File-rooted provider for dev/test.

    Layout:  $A81_KMS_LOCAL_DIR/<ref>.key   (raw bytes, length-prefixed elsewhere)
    Auto-creates the directory; lazily generates a key with os.urandom on miss.
    Not for production — keys live on disk in plaintext.
    """

    name = "local"

    def __init__(self, root: str) -> None:
        if not root:
            raise ConfigError("LocalProvider requires A81_KMS_LOCAL_DIR")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, ref: str) -> Path:
        # Reject refs that would escape root.
        safe = ref.replace("..", "").replace("/", "_").replace("\\", "_")
        if not safe:
            raise ConfigError(f"invalid key ref: {ref!r}")
        return self.root / f"{safe}.key"

    def key_for(self, ref: str, length: int, *, context: str = "") -> bytes:
        p = self._path(ref)
        if p.exists():
            data = p.read_bytes()
            if len(data) >= length:
                return data[:length]
            # Length grew — extend deterministically from the existing seed.
            extra = os.urandom(length - len(data))
            data = data + extra
            p.write_bytes(data)
            return data
        data = os.urandom(length)
        p.write_bytes(data)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
        return data

    def attest(self) -> dict:
        return {"provider": "local", "live": True, "root": str(self.root)}


# ── qkey (Day 2 — out of scope for current G.A8.1 sprint) ──────
#
# The QKeyProvider below is a working REST client against the OneShot/qkey
# FastAPI service. It is intentionally NOT part of the active G.A8.1 KMS
# story. The architectural decision is that production KMS integration
# happens at the OS layer (PKCS#11 module, kernel keyring, systemd
# credential, or a local Unix-socket shim) — NOT inside G.A8.1 or the
# Internet Subspace product.
#
# The class is kept here, working, so that:
#   1) anyone who already has qkey running can opt in via A81_KMS_PROVIDER=qkey;
#   2) the KMSProvider interface stays exercised by a non-trivial provider;
#   3) when we move to OS-level KMS, the migration path is "swap the
#      provider class" — not "design the abstraction from scratch".
#
# Do not extend QKeyProvider. New KMS work belongs in a Day 2 OS-level
# provider class.
# ────────────────────────────────────────────────────────────────
class QKeyProvider(KMSProvider):
    """Mjolnir OneShot/qkey REST client. *Day 2 — see header comment.*

    Backed by FastAPI service at {QKEY_URL}/v1/...
    See: product.quantum.oneshot/mjolnir_oneshot/routes/enhanced.py.

    Endpoint selection is driven by cfg.QKEY_MODE:
      omega          → /v1/key/omega-enhanced       (ML-KEM-1024 + AES-256-GCM + OTP)
      otp            → /v1/key/otp-enhanced         (one-time pad)
      quantum_noise  → /v1/key/quantum-noise-enhanced
      pqc            → /v1/key/pqc-enhanced
      kem            → /v1/key/kem-enhanced

    Authentication: X-Access-Key header, value from QKEY_ACCESS_KEY or
    file contents at QKEY_ACCESS_KEY_FILE.
    """

    name = "qkey"

    _MODE_PATHS = {
        "omega":         "/v1/key/omega-enhanced",
        "otp":           "/v1/key/otp-enhanced",
        "quantum_noise": "/v1/key/quantum-noise-enhanced",
        "pqc":           "/v1/key/pqc-enhanced",
        "kem":           "/v1/key/kem-enhanced",
    }

    def __init__(
        self,
        url: str,
        access_key: str,
        mode: str,
        timeout: int,
        verify_tls: bool,
    ) -> None:
        if not url:
            raise ConfigError("QKeyProvider requires A81_QKEY_URL")
        if not access_key:
            raise ConfigError("QKeyProvider requires A81_QKEY_ACCESS_KEY[_FILE]")
        if mode not in self._MODE_PATHS:
            raise ConfigError(f"unsupported A81_QKEY_MODE={mode!r}")
        self.url = url.rstrip("/")
        self.access_key = access_key
        self.mode = mode
        self.timeout = timeout
        self.verify_tls = verify_tls

    @classmethod
    def from_config(cls) -> "QKeyProvider":
        access_key = cfg.QKEY_ACCESS_KEY
        if not access_key and cfg.QKEY_ACCESS_KEY_FILE:
            access_key = Path(cfg.QKEY_ACCESS_KEY_FILE).read_text().strip()
        return cls(
            url=cfg.QKEY_URL,
            access_key=access_key,
            mode=cfg.QKEY_MODE,
            timeout=cfg.QKEY_TIMEOUT_SECONDS,
            verify_tls=cfg.QKEY_VERIFY_TLS,
        )

    def _payload(self, ref: str, length: int, context: str) -> dict:
        """Build the request body for the configured mode.

        We pass `context` as the qkey "context" field so the same ref+context
        deterministically binds to the same audit_hash on the qkey side.
        Length maps to:
          omega:         otp_len (the OTP layer length)
          otp:           length_bytes
          quantum_noise: length_bytes
          pqc:           ignored (algorithm-fixed key length)
          kem:           ignored (KEM-fixed key length)
        """
        ctx = context or ref
        if self.mode == "omega":
            return {"mode": "hybrid", "otp_len": length, "context": ctx}
        if self.mode in ("otp", "quantum_noise"):
            return {"length_bytes": length, "context": ctx}
        # pqc / kem do not take a length; caller gets fixed-size material.
        return {"context": ctx}

    def _post(self, path: str, body: dict) -> dict:
        import ssl
        req = urllib.request.Request(
            url=self.url + path,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Access-Key": self.access_key,
            },
            method="POST",
        )
        ctx_ssl: Optional[ssl.SSLContext] = None
        if not self.verify_tls:
            ctx_ssl = ssl.create_default_context()
            ctx_ssl.check_hostname = False
            ctx_ssl.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=ctx_ssl) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise ConfigError(
                f"qkey {path} returned HTTP {e.code}: {detail[:200]}"
            ) from e
        except urllib.error.URLError as e:
            raise ConfigError(f"qkey unreachable at {self.url}: {e.reason}") from e

    @staticmethod
    def _extract_key_b64(resp: dict, mode: str) -> str:
        """Different endpoints return key material under different fields."""
        if mode == "omega":
            otp = resp.get("otp") or {}
            for field in ("key_b64", "pad_b64", "otp_b64"):
                v = otp.get(field) if isinstance(otp, dict) else None
                if v:
                    return v
            v = resp.get("wrapped_dek_b64")
            if v:
                return v
            raise ConfigError("qkey omega response missing key material")
        if mode in ("otp", "quantum_noise"):
            v = resp.get("key_b64")
            if v:
                return v
        for field in ("key_b64", "wrapped_dek_b64", "kem_capsule_b64"):
            v = resp.get(field)
            if v:
                return v
        raise ConfigError(f"qkey {mode} response missing key material")

    def key_for(self, ref: str, length: int, *, context: str = "") -> bytes:
        path = self._MODE_PATHS[self.mode]
        resp = self._post(path, self._payload(ref, length, context))
        key_b64 = self._extract_key_b64(resp, self.mode)
        data = base64.b64decode(key_b64)
        return data[:length] if length and length <= len(data) else data

    def attest(self) -> dict:
        try:
            with urllib.request.urlopen(self.url + "/info", timeout=self.timeout) as resp:
                info = json.loads(resp.read().decode("utf-8"))
            return {"provider": "qkey", "live": True, "url": self.url, "info": info}
        except Exception as e:  # liveness probe; don't fail hard
            return {"provider": "qkey", "live": False, "url": self.url, "error": str(e)}

    def describe(self) -> str:
        return f"qkey({self.url}, mode={self.mode})"


# ── Factory ──────────────────────────────────────────────
_provider_singleton: Optional[KMSProvider] = None


def get_kms() -> KMSProvider:
    """Return the configured KMS provider (cached)."""
    global _provider_singleton
    if _provider_singleton is not None:
        return _provider_singleton
    p = cfg.KMS_PROVIDER
    if p == "none":
        _provider_singleton = NoneProvider()
    elif p == "local":
        _provider_singleton = LocalProvider(cfg.KMS_LOCAL_DIR)
    elif p == "qkey":
        _provider_singleton = QKeyProvider.from_config()
    elif p == "aws_kms":
        raise ConfigError("A81_KMS_PROVIDER=aws_kms is reserved; not yet implemented")
    else:
        raise ConfigError(f"unknown KMS provider: {p!r}")
    return _provider_singleton


def reset_kms_for_tests() -> None:
    """Drop the cached singleton so tests can re-init with new env."""
    global _provider_singleton
    _provider_singleton = None
