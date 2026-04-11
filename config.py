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
