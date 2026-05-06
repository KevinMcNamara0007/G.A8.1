"""
G.A8.1 — Configuration

Single source of truth for all tunables.

Resolution order (later wins):
    base config.env  →  configs/<A81_MODALITY>.env  →  process environment

The overlay is loaded at import time, before Config attributes evaluate.

Usage:
    from config import cfg
    dim = cfg.DIM           # 16384
    cfg.assert_ready_for("entangled_dc")  # raises if required keys missing
"""

import math
import os
from pathlib import Path


# ── Modality constants ───────────────────────────────────
# Whitepaper §3.2 — four modalities along the trust spectrum.
HALO_DC       = "halo_dc"
EDGE_DC       = "edge_dc"
ENTANGLED_DC  = "entangled_dc"
EDGE_TO_EDGE  = "edge_to_edge"
MODALITIES    = (HALO_DC, EDGE_DC, ENTANGLED_DC, EDGE_TO_EDGE)

# Process roles within a modality.
ROLE_ENCODER          = "encoder"
ROLE_EDGE             = "edge"
ROLE_REMOTE_PROCESSOR = "remote_processor"
ROLE_HYBRID           = "hybrid"
ROLES = (ROLE_ENCODER, ROLE_EDGE, ROLE_REMOTE_PROCESSOR, ROLE_HYBRID)


# ── Overlay loader ───────────────────────────────────────
def _load_modality_overlay() -> None:
    """Layer configs/<A81_MODALITY>.env on top of the base config.env.

    Process env always wins over overlay values (we only set keys the
    process didn't already define). Called at module import, before
    Config class attributes evaluate os.environ.
    """
    modality = os.environ.get("A81_MODALITY", "").strip()
    if not modality:
        return
    overlay = Path(__file__).resolve().parent / "configs" / f"{modality}.env"
    if not overlay.exists():
        return
    for raw in overlay.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        # Strip inline comments and surrounding quotes.
        val = val.split("#", 1)[0].strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        if not key.startswith("A81_"):
            continue
        # Process env wins. Overlay only fills holes.
        if key not in os.environ:
            os.environ[key] = val


_load_modality_overlay()


def _env(key: str, default, type_fn=str):
    """Read env var with type conversion and default."""
    val = os.environ.get(key)
    if val is None:
        return default
    if type_fn == bool:
        return val.lower() in ("1", "true", "yes", "on")
    return type_fn(val)


class Config:
    """All G.A8.1 tunables. Reads from A81_* environment variables."""

    # ── Modality / Role ──────────────────────────────────
    MODALITY: str = _env("A81_MODALITY", HALO_DC)
    ROLE:     str = _env("A81_ROLE", ROLE_HYBRID)

    # ── Vector Space ─────────────────────────────────────
    DIM:        int   = _env("A81_DIM", 16384, int)
    K:          int   = _env("A81_K", 128, int)
    SEED:       int   = _env("A81_SEED", 42, int)
    MAX_SALIENT_TOKENS: int = _env("A81_MAX_SALIENT_TOKENS", 12, int)

    # ── Sharding ─────────────────────────────────────────
    ENTITY_BUCKETS:  int = _env("A81_ENTITY_BUCKETS", 4, int)
    ACTION_CLUSTERS: int = _env("A81_ACTION_CLUSTERS", 20, int)
    CLUSTER_SAMPLE:  int = _env("A81_CLUSTER_SAMPLE", 100000, int)
    WAVES:           int = _env("A81_WAVES", 4, int)

    # ── LSH Index ────────────────────────────────────────
    LSH_TABLES:     int  = _env("A81_LSH_TABLES", 8, int)
    LSH_HASH_SIZE:  int  = _env("A81_LSH_HASH_SIZE", 16, int)
    LSH_MULTIPROBE: bool = _env("A81_LSH_MULTIPROBE", True, bool)

    # ── Query ────────────────────────────────────────────
    QUERY_SHARDS:           int = _env("A81_QUERY_SHARDS", 3, int)
    QUERY_TOP_K:            int = _env("A81_QUERY_TOP_K", 10, int)
    QUERY_FETCH_MULTIPLIER: int = _env("A81_QUERY_FETCH_MULTIPLIER", 5, int)

    # ── Scoring Weights ──────────────────────────────────
    WEIGHT_BSC:       int = _env("A81_WEIGHT_BSC", 50, int)
    WEIGHT_KEYWORD:   int = _env("A81_WEIGHT_KEYWORD", 40, int)
    WEIGHT_PROXIMITY: int = _env("A81_WEIGHT_PROXIMITY", 10, int)

    # ── Gazetteer ────────────────────────────────────────
    GAZETTEER_BOOST:      float = _env("A81_GAZETTEER_BOOST", 3.0, float)
    GAZETTEER_GUARANTEED: bool  = _env("A81_GAZETTEER_GUARANTEED", True, bool)

    # ── Adaptive Learning ────────────────────────────────
    ADAPTIVE_GAZ:            bool  = _env("A81_ADAPTIVE_GAZ", False, bool)
    ADAPTIVE_MIN_SCORE:      float = _env("A81_ADAPTIVE_MIN_SCORE", 0.15, float)
    ADAPTIVE_MAX_EXPANSIONS: int   = _env("A81_ADAPTIVE_MAX_EXPANSIONS", 5, int)
    ADAPTIVE_RETENTION:      float = _env("A81_ADAPTIVE_RETENTION", 0.1, float)

    # ── Media ────────────────────────────────────────────
    MEDIA_ENABLED:  bool = _env("A81_MEDIA_ENABLED", True, bool)
    VISION_SEED:    int  = _env("A81_VISION_SEED", 2100, int)
    VIDEO_SEED:     int  = _env("A81_VIDEO_SEED", 2300, int)
    VIDEO_FRAMES:   int  = _env("A81_VIDEO_FRAMES", 8, int)

    # ── Attention ────────────────────────────────────────
    ATTENTION_BETA:      float = _env("A81_ATTENTION_BETA", 1.5, float)
    ATTENTION_MIN_SCORE: float = _env("A81_ATTENTION_MIN_SCORE", 0.0, float)

    # ── Closed-Loop Encode/Decode (v13) ──────────────────
    CLOSED_LOOP_ENABLED:     bool = _env("A81_CLOSED_LOOP", False, bool)
    CLOSED_LOOP_AXES:        str  = _env("A81_CLOSED_LOOP_AXES", "possessive,acronym")
    CLOSED_LOOP_LOG_PATH:    str  = _env("A81_CLOSED_LOOP_LOG", "")
    CLOSED_LOOP_WINDOW:      int  = _env("A81_CLOSED_LOOP_WINDOW", 100, int)
    CLOSED_LOOP_STRICT:      bool = _env("A81_CLOSED_LOOP_STRICT", False, bool)

    # ── Tier-Routed Encoding v13 (PlanB) ─────────────────
    TIER_ROUTED_ENABLED: bool = _env("A81_TIER_ROUTED", False, bool)
    TIER_GATE_MODE:      str  = _env("A81_TIER_GATE_MODE", "default")
    TIER_TENANT_DOMAIN:  str  = _env("A81_TIER_TENANT", "default::default")
    TIER_EXTRACTOR:      str  = _env("A81_TIER_EXTRACTOR", "rule_based")

    # ── CPU / parallelism ────────────────────────────────
    CPU_FRACTION:   float = _env("A81_CPU_FRACTION", 0.8, float)

    # ── Corpus Profiler v13.1 (PlanC) ────────────────────
    DIMENSIONS_PROFILE_REQUIRED: bool = _env("A81_DIMENSIONS_PROFILE_REQUIRED", True, bool)
    DIMENSIONS_HEADROOM:         float = _env("A81_DIMENSIONS_HEADROOM", 1.2, float)
    DIMENSIONS_TRIVIAL_THRESHOLD: int  = _env("A81_DIMENSIONS_TRIVIAL_THRESHOLD", 10_000, int)
    DIMENSIONS_GRID_EXTENDED:    bool  = _env("A81_DIMENSIONS_GRID_EXTENDED", False, bool)
    DIMENSIONS_PROFILE_SAMPLE:   int   = _env("A81_DIMENSIONS_PROFILE_SAMPLE", 10_000, int)
    DIMENSIONS_PROFILE_QUERIES:  int   = _env("A81_DIMENSIONS_PROFILE_QUERIES", 200, int)
    DIMENSIONS_LEGACY_SENTINEL:  str   = _env("A81_DIMENSIONS_LEGACY_SENTINEL", "v13.0-default")

    # ── Codebook & Indices Location ──────────────────────
    # halo_dc → local; edge_dc → edge; entangled_dc / edge_to_edge → edge (MUST).
    CODEBOOK_LOCATION: str = _env("A81_CODEBOOK_LOCATION", "local")
    INDICES_LOCATION:  str = _env("A81_INDICES_LOCATION", "local")

    # ── Bundle (M2 — Edge DC) ────────────────────────────
    BUNDLE_PATH:            str  = _env("A81_BUNDLE_PATH", "")
    BUNDLE_SIGNING_KEY_REF: str  = _env("A81_BUNDLE_SIGNING_KEY_REF", "")
    BUNDLE_ENC_KEY_REF:     str  = _env("A81_BUNDLE_ENC_KEY_REF", "")
    BUNDLE_DELTA_BASE:      str  = _env("A81_BUNDLE_DELTA_BASE", "")
    BUNDLE_VERIFY_ON_LOAD:  bool = _env("A81_BUNDLE_VERIFY_ON_LOAD", True, bool)
    BUNDLE_INCLUDE_PROFILE: bool = _env("A81_BUNDLE_INCLUDE_PROFILE", True, bool)

    # ── Transport / Channel privacy (M3, M4) ─────────────
    # ssh-tunnel | http-loopback | https
    REMOTE_TRANSPORT:  str  = _env("A81_REMOTE_TRANSPORT", "ssh-tunnel")
    REMOTE_URL:        str  = _env("A81_REMOTE_URL", "")
    TLS_MIN:           str  = _env("A81_TLS_MIN", "1.3")
    TLS_PQ_HYBRID:     bool = _env("A81_TLS_PQ_HYBRID", True, bool)
    TLS_CERT_PIN:      str  = _env("A81_TLS_CERT_PIN", "")
    TLS_CIPHERSUITES:  str  = _env("A81_TLS_CIPHERSUITES",
                                   "TLS_AES_256_GCM_SHA384,TLS_CHACHA20_POLY1305_SHA256")

    # ── Subspace Privacy (M3, M4) ────────────────────────
    BASIS_ROTATION:        bool = _env("A81_BASIS_ROTATION", True, bool)
    BASIS_WINDOW_SECONDS:  int  = _env("A81_BASIS_WINDOW_SECONDS", 3600, int)
    BASIS_OVERLAP:         float = _env("A81_BASIS_OVERLAP", 0.10, float)
    BLINDING:              bool = _env("A81_BLINDING", True, bool)
    BLINDING_KEY_REF:      str  = _env("A81_BLINDING_KEY_REF", "")
    REMOTE_PROFILE_PIN:    str  = _env("A81_REMOTE_PROFILE_PIN", "session")

    # ── KMS / OneShot (qkey) ─────────────────────────────
    # Provider:  none | local | qkey | aws_kms
    # qkey is the proprietary OneShot REST service:
    #   POST {QKEY_URL}/v1/key/<mode>-enhanced  with header X-Access-Key.
    # See product.quantum.oneshot/mjolnir_oneshot/routes/enhanced.py.
    KMS_PROVIDER:           str  = _env("A81_KMS_PROVIDER", "none")
    KMS_LOCAL_DIR:          str  = _env("A81_KMS_LOCAL_DIR", "")
    QKEY_URL:               str  = _env("A81_QKEY_URL", "")
    QKEY_ACCESS_KEY:        str  = _env("A81_QKEY_ACCESS_KEY", "")
    QKEY_ACCESS_KEY_FILE:   str  = _env("A81_QKEY_ACCESS_KEY_FILE", "")
    QKEY_MODE:              str  = _env("A81_QKEY_MODE", "omega")
    QKEY_TIMEOUT_SECONDS:   int  = _env("A81_QKEY_TIMEOUT_SECONDS", 10, int)
    QKEY_VERIFY_TLS:        bool = _env("A81_QKEY_VERIFY_TLS", True, bool)

    # ── Ternary-Native LLM (M4) ──────────────────────────
    LLM_PROVIDER:             str  = _env("A81_LLM_PROVIDER", "none")
    LLM_ENDPOINT:             str  = _env("A81_LLM_ENDPOINT", "")
    LLM_ATTESTATION_REQUIRED: bool = _env("A81_LLM_ATTESTATION_REQUIRED", True, bool)

    # ── Paths ────────────────────────────────────────────
    SOURCE_PATH:    str = _env("A81_SOURCE_PATH", "")
    INDEX_PATH:     str = _env("A81_INDEX_PATH", "")
    PRODUCT_DIR:    str = _env("A81_PRODUCT_DIR", "")
    MEDIA_DIR:      str = _env("A81_MEDIA_DIR", "")
    GAZETTEER_PATH: str = _env("A81_GAZETTEER_PATH", "")
    CLUSTERS_PATH:  str = _env("A81_CLUSTERS_PATH", "")

    @property
    def N_SHARDS(self) -> int:
        """Total shard slots (entity_buckets × action_clusters)."""
        return self.ENTITY_BUCKETS * self.ACTION_CLUSTERS

    def summary(self) -> str:
        return (f"modality={self.MODALITY} role={self.ROLE} "
                f"D={self.DIM} k={self.K} salient={self.MAX_SALIENT_TOKENS} "
                f"shards={self.ENTITY_BUCKETS}×{self.ACTION_CLUSTERS}={self.N_SHARDS} "
                f"LSH={self.LSH_TABLES}t/{self.LSH_HASH_SIZE}b "
                f"query={self.QUERY_SHARDS}sh/{self.QUERY_TOP_K}k "
                f"weights={self.WEIGHT_BSC}/{self.WEIGHT_KEYWORD}/{self.WEIGHT_PROXIMITY} "
                f"gaz_boost={self.GAZETTEER_BOOST} "
                f"kms={self.KMS_PROVIDER}")

    def assert_ready_for(self, modality: str) -> None:
        """Validate that required keys for the given modality are populated.

        Raises ConfigError on the first violation. Call early at process
        startup so misconfigurations fail loudly rather than at first query.
        """
        if modality not in MODALITIES:
            raise ConfigError(f"unknown modality: {modality!r} (expected one of {MODALITIES})")
        if self.ROLE not in ROLES:
            raise ConfigError(f"A81_ROLE={self.ROLE!r} not one of {ROLES}")

        # Transport selector — applies whenever the modality talks to a remote.
        if modality in (ENTANGLED_DC, EDGE_TO_EDGE):
            if self.REMOTE_TRANSPORT not in ("ssh-tunnel", "http-loopback", "https"):
                raise ConfigError(
                    f"A81_REMOTE_TRANSPORT={self.REMOTE_TRANSPORT!r} not one of "
                    "(ssh-tunnel, http-loopback, https)"
                )
            # TLS settings only matter when transport=https. ssh-tunnel and
            # http-loopback delegate channel privacy to sshd / loopback.
            if self.REMOTE_TRANSPORT == "https":
                if self.TLS_MIN not in ("1.3",):
                    raise ConfigError(
                        f"A81_TLS_MIN={self.TLS_MIN!r} unsupported when "
                        "A81_REMOTE_TRANSPORT=https. TLS 1.3 is the minimum; "
                        "1.2 and earlier are explicitly rejected (whitepaper §8.1)."
                    )

        # KMS provider validation — applies to any modality that selects qkey.
        if self.KMS_PROVIDER == "qkey":
            self._require("A81_QKEY_URL", self.QKEY_URL)
            if not (self.QKEY_ACCESS_KEY or self.QKEY_ACCESS_KEY_FILE):
                raise ConfigError(
                    "A81_KMS_PROVIDER=qkey requires A81_QKEY_ACCESS_KEY or "
                    "A81_QKEY_ACCESS_KEY_FILE to be set"
                )
            if self.QKEY_MODE not in ("omega", "otp", "quantum_noise", "pqc", "kem"):
                raise ConfigError(
                    f"A81_QKEY_MODE={self.QKEY_MODE!r} not one of "
                    "(omega, otp, quantum_noise, pqc, kem)"
                )
        elif self.KMS_PROVIDER == "local":
            self._require("A81_KMS_LOCAL_DIR", self.KMS_LOCAL_DIR)
        elif self.KMS_PROVIDER not in ("none", "aws_kms"):
            raise ConfigError(
                f"A81_KMS_PROVIDER={self.KMS_PROVIDER!r} unsupported "
                "(expected: none | local | qkey | aws_kms)"
            )

        if modality == HALO_DC:
            self._require("A81_INDEX_PATH", self.INDEX_PATH)
            return

        if modality == EDGE_DC:
            self._require("A81_BUNDLE_PATH", self.BUNDLE_PATH)
            if self.ROLE == ROLE_ENCODER:
                self._require("A81_BUNDLE_SIGNING_KEY_REF", self.BUNDLE_SIGNING_KEY_REF)
            if self.CODEBOOK_LOCATION != "edge":
                raise ConfigError(
                    "edge_dc requires A81_CODEBOOK_LOCATION=edge after bundle import"
                )
            return

        if modality == ENTANGLED_DC:
            if self.CODEBOOK_LOCATION != "edge":
                raise ConfigError(
                    "entangled_dc REQUIRES A81_CODEBOOK_LOCATION=edge — moving the "
                    "codebook off-edge collapses the subspace privacy claim"
                )
            if self.INDICES_LOCATION != "edge":
                raise ConfigError("entangled_dc REQUIRES A81_INDICES_LOCATION=edge")
            if self.ROLE == ROLE_EDGE:
                self._require("A81_REMOTE_URL", self.REMOTE_URL)
            if not self.BASIS_ROTATION:
                raise ConfigError(
                    "entangled_dc REQUIRES A81_BASIS_ROTATION=true (whitepaper §8.3)"
                )
            if not self.BLINDING:
                raise ConfigError(
                    "entangled_dc REQUIRES A81_BLINDING=true (whitepaper §8.4)"
                )
            if self.REMOTE_PROFILE_PIN not in ("off", "session", "strict"):
                raise ConfigError(
                    f"A81_REMOTE_PROFILE_PIN={self.REMOTE_PROFILE_PIN!r} "
                    "not one of (off, session, strict)"
                )
            return

        if modality == EDGE_TO_EDGE:
            # M4 is scaffold-only today.
            if self.LLM_PROVIDER != "none":
                raise ConfigError(
                    f"A81_LLM_PROVIDER={self.LLM_PROVIDER!r} is not yet supported. "
                    "Edge↔Edge is config-scaffolded; only 'none' is wired today. "
                    "T5 validation track and BitNet 2.5 production track land later."
                )
            return

    @staticmethod
    def _require(env_name: str, value) -> None:
        if not value:
            raise ConfigError(f"{env_name} is required for this modality but is empty")


class ConfigError(RuntimeError):
    """Raised when assert_ready_for() finds a missing or invalid required key."""


# Singleton
cfg = Config()


def resolve_lsh_hash_size(n_records: int) -> int:
    """Auto-tune LSH hash_size so average bucket holds ~10 vectors.

    Derivation:  hash_size = ceil(log2(n_records / 10)), clamped [14, 28].

    The clamp:
      - Floor 14 matches the v13.0 default (safe for corpora < ~160K).
      - Ceiling 28 = 2^28 = 268M buckets. Above ~100B records buckets
        unavoidably over-fill — tune more LSH tables instead.

    Reference table (records → hash_size → avg vec/bucket):
        100K   → 14   (6 vec/bucket)
        1M     → 17   (8 vec/bucket)
        10M    → 20   (10 vec/bucket)
        100M   → 24   (6 vec/bucket)
        1B     → 27   (7 vec/bucket)
        100B   → 28   (373 vec/bucket — at the clamp ceiling)

    The 21M Wikidata regression lived at the 20 line. Old default of
    16 put 325 vectors/bucket → LSH multiprobe effectively scanned a
    huge chunk of the corpus → ~60s query latency at k=90.
    """
    if n_records <= 0:
        return 16
    ideal = math.ceil(math.log2(max(1, n_records / 10.0)))
    return max(14, min(28, int(ideal)))


def resolve_workers(requested: int = 0, *, minimum: int = 1) -> int:
    """Resolve a worker / thread count.

    If `requested` is positive, it wins (explicit override). Otherwise
    return `floor(cpu_count * CPU_FRACTION)`, clamped to `minimum` or
    above. Container-aware on Linux via `os.sched_getaffinity`; falls
    back to `os.cpu_count()` on macOS / other platforms.

    This is the single place in G.A8.1 that converts "0 means auto" to
    an integer. Encode waves, ingest threads, and benchmark thread
    flags all funnel through here so one env var (`A81_CPU_FRACTION`)
    controls everything.
    """
    if requested and requested > 0:
        return max(minimum, int(requested))
    try:
        cores = len(os.sched_getaffinity(0))  # respects cgroup / taskset on Linux
    except (AttributeError, OSError):
        cores = os.cpu_count() or minimum
    return max(minimum, int(cores * max(cfg.CPU_FRACTION, 0.0)))
