"""
G.A8.1 / decode13 — Tier-Routed Encoding (Entangled Halo v13, PlanB)

Three-tier architecture that routes inputs through different pipelines
based on source shape:

  Tier 1 — structured_atomic   : S/R/O present. Escape-decode only, bind
                                 S/R/O as-provided. Compound tokens
                                 (joe_misiti, member_of_sports_team) are
                                 preserved atomically.
  Tier 2 — extracted_triple    : Free text. Escape → possessive → acronym
                                 → rule-based fact separation →
                                 lightweight NER/SRL → dual-extractor gate
                                 → bind validated triples individually.
  Tier 3 — emergent_structure  : Tier 2 extraction failed. Canonical
                                 fallback, low confidence, sidecar rerank
                                 becomes load-bearing.

Every encoded vector carries a per-vector TierManifest describing tier +
component versions. The manifest uses a structured composite hash so
queries that don't exercise an updated normalization axis still match
vectors encoded before the update (§4.4 of PlanB).

Preserves v12.5 geometry: binding, superposition, G.A8.1 two-tier shard
routing, BSCCompactIndex + BSCLSHIndex, deterministic 2:5 quorum. The
tier layer only decides *what tokens* enter binding, not *how* binding
works.
"""

from .tier_types import Tier, TierDecision, ExtractedTriple
from .tier_router import TierRouter
from .structured_pipeline import StructuredAtomicPipeline
from .extraction_pipeline import ExtractionPipeline
from .emergent_pipeline import EmergentStructureFallback
from .extractors import RuleBasedFactSeparator, HeuristicNER
from .tier_manifest import TierManifest, ComponentVersions, ManifestRegistry13
from .escape_decode import escape_decode
from .tier_encode import TierEncoder, VectorInfo
from .query_service import QueryService as QueryServiceV13, ShardData13, QueryHit13
from .structural_encoder import (
    build_config as build_structural_config,
    build_pipeline as build_structural_pipeline,
    load_pipeline as load_structural_pipeline,
    save_pipeline as save_structural_pipeline,
)

__all__ = [
    "Tier",
    "TierDecision",
    "ExtractedTriple",
    "TierRouter",
    "StructuredAtomicPipeline",
    "ExtractionPipeline",
    "EmergentStructureFallback",
    "RuleBasedFactSeparator",
    "HeuristicNER",
    "TierManifest",
    "ComponentVersions",
    "ManifestRegistry13",
    "escape_decode",
    "TierEncoder",
    "VectorInfo",
    "QueryServiceV13",
    "ShardData13",
    "QueryHit13",
    "build_structural_config",
    "build_structural_pipeline",
    "load_structural_pipeline",
    "save_structural_pipeline",
]
