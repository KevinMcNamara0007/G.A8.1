"""Role seed authority for decode13.

Single source of truth for the integer seeds used by the v13 structural
pipeline. Both encode-side (`encode/worker_encode.py` with tier-routed
on) and decode-side (`decode13/query_service.py`) import from here. Any
change here triggers a manifest composite-hash change via
`structural_config.components_hash()`, so drift is mechanically detected.

The seeds themselves are mirrored in C++ at
`EHC/include/ehc/pipeline/structural_v13.hpp::ehc::pipeline::v13_seeds`.
If you change one, change both.

Multi-tenant / MoE isolation: every seed is shifted by a per-tenant
`tenant_offset` inside the C++ `StructuralPipelineV13`. So `SUBJECT` for
tenant A and `SUBJECT` for tenant B are near-orthogonal role vectors —
their encoded triples cannot accidentally match across tenants.
"""

from __future__ import annotations


# Tier 1 — structured SRO (Wikidata / KG exports / labelled facts).
# Reserved range, not currently consumed by the structural pipeline.
SEED_SUBJECT     = 1
SEED_RELATION    = 2
SEED_OBJECT      = 3

# Tier 2/3 — structural slot + local syntax bindings.
# Must match C++ ehc::pipeline::v13_seeds::* values.
SEED_SLOT_BASE   = 10000   # SLOT_i = SEED_SLOT_BASE + i
SEED_BIGRAM      = 11000
SEED_KV          = 11100
SEED_TIMESTAMP   = 11200
SEED_AUTHOR      = 11300


def slot_seed(i: int) -> int:
    """Seed for SLOT_i within the reserved v13 slot range."""
    return SEED_SLOT_BASE + int(i)


def tenant_domain_offset(tenant: str, domain: str) -> int:
    """Deterministic offset for a (tenant, domain) pair.

    Applied via `StructuralConfig.tenant_offset`. Same string → same
    offset → same role vectors (cross-session stability). Different
    pair → different offset → near-orthogonal role space.
    """
    import hashlib
    key = f"{tenant}::{domain}".encode("utf-8")
    h = hashlib.blake2b(key, digest_size=4).digest()
    # 31-bit positive to keep clear of sign + leave 32-bit room.
    return int.from_bytes(h, "little") & 0x7FFF_FFFF
