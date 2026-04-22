"""
G.A8.1 — Configuration

Single source of truth for all tunables.
Reads from environment variables (set via config.env, .env, docker, etc.)
Falls back to sensible defaults.

Usage:
    from config import cfg
    dim = cfg.DIM           # 16384
    k = cfg.K               # 128
    shards = cfg.QUERY_SHARDS  # 3
"""

import math
import os


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

    # ── Closed-Loop Encode/Decode (v13, Closed_Loop_Encode_Decode_Plan) ──
    # When CLOSED_LOOP_ENABLED is True, both encode and decode route tokens
    # through canonical.CanonicalizationPipeline, and decode fans queries
    # out along configured axes. Disabled by default — enabling requires
    # re-encoding so shards carry symmetry_manifest.json.
    CLOSED_LOOP_ENABLED:     bool = _env("A81_CLOSED_LOOP", False, bool)
    CLOSED_LOOP_AXES:        str  = _env("A81_CLOSED_LOOP_AXES", "possessive,acronym")
    CLOSED_LOOP_LOG_PATH:    str  = _env("A81_CLOSED_LOOP_LOG", "")
    CLOSED_LOOP_WINDOW:      int  = _env("A81_CLOSED_LOOP_WINDOW", 100, int)
    CLOSED_LOOP_STRICT:      bool = _env("A81_CLOSED_LOOP_STRICT", False, bool)

    # ── Tier-Routed Encoding v13 (PlanB) ───────────────────
    # When TIER_ROUTED_ENABLED is True, encode + decode dispatch through
    # decode13/ tier router. Three-tier architecture; defaults to Tier 1
    # pass-through for structured SRO inputs and Tier 2 extraction for
    # free text. Disabled by default — enabling requires re-encoding so
    # shards carry per-vector TierManifest records.
    TIER_ROUTED_ENABLED: bool = _env("A81_TIER_ROUTED", False, bool)
    TIER_GATE_MODE:      str  = _env("A81_TIER_GATE_MODE", "default")
    TIER_TENANT_DOMAIN:  str  = _env("A81_TIER_TENANT", "default::default")
    # Tier-2 primary extractor selector:
    #   "rule_based" (default) | "t5" | "t5:google/flan-t5-large"
    TIER_EXTRACTOR:      str  = _env("A81_TIER_EXTRACTOR", "rule_based")

    # ── CPU / parallelism ────────────────────────────────
    #   Fraction of hardware cores that the auto paths are allowed to
    #   use. Leaves headroom for the main thread, GIL-holding Python,
    #   and OS/IO. Only consulted when callers pass 0 / don't set
    #   A81_WAVES explicitly — explicit values always win.
    CPU_FRACTION:   float = _env("A81_CPU_FRACTION", 0.8, float)

    # ── Corpus Profiler v13.1 (PlanC) ────────────────────
    #   Pre-encode dimensionality calibration. When PROFILE_REQUIRED is
    #   True, encode aborts on corpora above TRIVIAL_THRESHOLD if no
    #   corpus_profile.json is found next to the target index dir.
    DIMENSIONS_PROFILE_REQUIRED: bool = _env("A81_DIMENSIONS_PROFILE_REQUIRED", True, bool)
    DIMENSIONS_HEADROOM:         float = _env("A81_DIMENSIONS_HEADROOM", 1.2, float)
    DIMENSIONS_TRIVIAL_THRESHOLD: int  = _env("A81_DIMENSIONS_TRIVIAL_THRESHOLD", 10_000, int)
    #   Extended grid adds 6144 and 12288 to the power-of-2 base grid.
    #   Gated off by default pending EHC C++ review — non-power-of-2 D
    #   may crash the BSC kernel. See PlanC_cpp_engineer_memo.md.
    DIMENSIONS_GRID_EXTENDED:    bool  = _env("A81_DIMENSIONS_GRID_EXTENDED", False, bool)
    DIMENSIONS_PROFILE_SAMPLE:   int   = _env("A81_DIMENSIONS_PROFILE_SAMPLE", 10_000, int)
    DIMENSIONS_PROFILE_QUERIES:  int   = _env("A81_DIMENSIONS_PROFILE_QUERIES", 200, int)
    #   Sentinel stamped on v13.0-era shards that predate the dimensions
    #   axis. Query-time runtime maps it to the hardcoded D=16384/k=128.
    DIMENSIONS_LEGACY_SENTINEL:  str   = _env("A81_DIMENSIONS_LEGACY_SENTINEL", "v13.0-default")

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
        return (f"D={self.DIM} k={self.K} salient={self.MAX_SALIENT_TOKENS} "
                f"shards={self.ENTITY_BUCKETS}×{self.ACTION_CLUSTERS}={self.N_SHARDS} "
                f"LSH={self.LSH_TABLES}t/{self.LSH_HASH_SIZE}b "
                f"query={self.QUERY_SHARDS}sh/{self.QUERY_TOP_K}k "
                f"weights={self.WEIGHT_BSC}/{self.WEIGHT_KEYWORD}/{self.WEIGHT_PROXIMITY} "
                f"gaz_boost={self.GAZETTEER_BOOST}")


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
