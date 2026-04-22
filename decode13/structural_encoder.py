"""Thin Python wrapper around EHC's StructuralPipelineV13.

All heavy lifting — tokenize, stem, role-bind, superpose, index,
Hebbian learning — happens inside the C++ pipeline. This module just:

  - Builds a `StructuralConfig` from `G.A8.1/config.py`.
  - Handles per-shard save/load using the existing shard layout.
  - Exposes a small factory so the production `encode/worker_encode.py`
    and `decode13/query_service.py` both construct the same pipeline
    by importing the same function.

Intentional non-goals (Python is NOT doing these):
  - No per-token loops here; `StructuralPipelineV13.ingest_text()` does it all in C++.
  - No regex extraction; tier-2 extraction is pure structural role binding.
  - No triple string materialization; the retrieval signal lives in the vector.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# EHC import probe (identical pattern to worker_encode.py).
for _d in (2, 3, 4):
    _p = Path(__file__).resolve().parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc  # noqa: E402

from .roles import tenant_domain_offset


def _a81_defaults() -> dict:
    """Pull defaults from G.A8.1/config.py when importable; otherwise
    fall back to literal constants. Keeps decode13 runnable in isolation
    but makes A81_* env vars actually take effect when running under the
    production pipeline."""
    try:
        _root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(_root))
        from config import cfg as _cfg  # type: ignore
        return {
            "dim":           _cfg.DIM,
            "k":             _cfg.K,
            "codebook_seed": _cfg.SEED,
            "lsh_tables":    _cfg.LSH_TABLES,
            "lsh_hash_size": _cfg.LSH_HASH_SIZE,
        }
    except Exception:
        return {
            "dim": 16384, "k": 128, "codebook_seed": 42,
            "lsh_tables": 8, "lsh_hash_size": 16,
        }


def build_config(
    *,
    dim: Optional[int] = None,
    k: Optional[int] = None,
    codebook_seed: Optional[int] = None,
    max_slots: int = 32,
    enable_bigram: bool = True,
    enable_kv: bool = True,
    enable_hebbian: bool = True,
    hebbian_window: int = 5,
    tenant: str = "default",
    domain: str = "default",
    tenant_offset: Optional[int] = None,
    lowercase: bool = True,
    remove_punct: bool = True,
    use_stemming: bool = True,
    remove_stopwords: bool = False,
    lsh_tables: Optional[int] = None,
    lsh_hash_size: Optional[int] = None,
) -> "ehc.StructuralConfig":
    """Build a `StructuralConfig` from `G.A8.1/config.py` defaults.

    Any keyword left as None inherits the A81_* environment value (via
    config.py) — that is the knob `config.env` exposes to operators.
    Explicit kwargs still override for tests and ad-hoc scripts.

    The tenant+domain pair is folded into a deterministic `tenant_offset`
    so MoE-style multi-domain corpora share no role-vector space.
    """
    d = _a81_defaults()
    cfg = ehc.StructuralConfig()
    cfg.dim              = int(dim              if dim              is not None else d["dim"])
    cfg.k                = int(k                if k                is not None else d["k"])
    cfg.codebook_seed    = int(codebook_seed    if codebook_seed    is not None else d["codebook_seed"])
    cfg.max_slots        = int(max_slots)
    cfg.enable_bigram    = bool(enable_bigram)
    cfg.enable_kv        = bool(enable_kv)
    cfg.enable_hebbian   = bool(enable_hebbian)
    cfg.hebbian_window   = int(hebbian_window)
    # tenant_offset resolution: explicit value wins; otherwise the
    # (tenant, domain) pair → deterministic offset; the stock
    # ("default", "default") pair maps to 0 so single-tenant deployments
    # get canonical role vectors (matches raw StructuralConfig defaults).
    if tenant_offset is not None:
        cfg.tenant_offset = int(tenant_offset)
    elif tenant == "default" and domain == "default":
        cfg.tenant_offset = 0
    else:
        cfg.tenant_offset = tenant_domain_offset(tenant, domain)
    cfg.lowercase        = bool(lowercase)
    cfg.remove_punct     = bool(remove_punct)
    cfg.use_stemming     = bool(use_stemming)
    cfg.remove_stopwords = bool(remove_stopwords)
    cfg.lsh_tables       = int(lsh_tables       if lsh_tables       is not None else d["lsh_tables"])
    cfg.lsh_hash_size    = int(lsh_hash_size    if lsh_hash_size    is not None else d["lsh_hash_size"])
    return cfg


def build_pipeline(cfg: Optional["ehc.StructuralConfig"] = None) -> "ehc.StructuralPipelineV13":
    """Construct a fresh pipeline from a config (or decode13 defaults)."""
    if cfg is None:
        cfg = build_config()
    return ehc.StructuralPipelineV13(cfg)


def build_sro_tier1_config(
    *,
    dim: Optional[int] = None,
    k: Optional[int] = None,
    codebook_seed: Optional[int] = None,
) -> "ehc.StructuralConfig":
    """Validated StructuralPipelineV13 config for Tier-1 SRO corpora.

    This is the production contract for atomic-triple corpora (Wikidata,
    knowledge graphs, etc.) where the lookup key is `(subject, relation)`
    and the object is the answer, not part of the key.

    Contract (discovered empirically in session; see PlanC_v13_1_*):

      1. Encode each record with text = `"{subject} {relation}"` (KEY only).
      2. Keep the full `(s, r, o)` in a sidecar keyed by `doc_id`
         (corpus.jsonl is the on-disk format; the edge shim reads it).
      3. Query with text = `"{subject} {relation}"` — exact self-identity
         match against the key.

    Config choices:

      - `remove_punct=False`, `use_stemming=False`, `remove_stopwords=False`:
        preserve compound atomic tokens (`lalit_kumar_goel`,
        `instance_of`) as single units. Underscores survive tokenization.
      - `enable_hebbian=False`: on single-exposure corpora like Wikidata,
        Hebbian learns noisy correlations (diagnostic showed 11% → 3%
        Hit@1 when expansion is on vs off).
      - `enable_bigram=True`, `enable_kv=True`: role binding is the
        geometric source of the (s,r)-as-subspace property once the key
        decoupling is in place.

    Measured result at 5M: Hit@1 = 100%, p50 latency = 33 ms.
    """
    return build_config(
        dim=dim, k=k, codebook_seed=codebook_seed,
        max_slots=24,
        enable_bigram=True,
        enable_kv=True,
        enable_hebbian=False,
        lowercase=True,
        remove_punct=False,
        use_stemming=False,
        remove_stopwords=False,
    )


def sro_tier1_encode_text(subject: str, relation: str) -> str:
    """Return the KEY text to ingest for an SRO Tier-1 record.

    Keeps punctuation and underscores so the C++ tokenizer treats
    compound tokens (`lalit_kumar_goel`) as atomic.
    """
    return f"{subject} {relation}"


def sro_tier1_query_text(subject: str, relation: str) -> str:
    """Return the query text for an SRO Tier-1 lookup — identical shape
    to the ingest text so query self-matches against its gold key."""
    return f"{subject} {relation}"


def load_pipeline(shard_dir: str) -> "ehc.StructuralPipelineV13":
    """Load a previously-persisted pipeline from a shard directory.

    Looks for `structural_v13.cfg` + optional `hebbian.bin` at the given
    path. Raises if the config file is absent (caller should treat that
    as "not a v13 shard" and fall back to another path).
    """
    p = Path(shard_dir)
    if not (p / "structural_v13.cfg").exists():
        raise FileNotFoundError(f"no v13 structural config in {shard_dir}")
    return ehc.StructuralPipelineV13.load(str(p))


def save_pipeline(pipeline: "ehc.StructuralPipelineV13", shard_dir: str) -> None:
    """Persist pipeline config + Hebbian snapshot to a shard directory.

    The C++ side writes `structural_v13.cfg` + `hebbian.bin` under
    `shard_dir`. The shard's BSC indices (written by worker_encode.py)
    are a separate concern and remain as before.
    """
    Path(shard_dir).mkdir(parents=True, exist_ok=True)
    pipeline.save(str(shard_dir))
