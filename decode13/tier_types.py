"""Tier enum, decision record, and extracted-triple record."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class Tier(str, Enum):
    STRUCTURED_ATOMIC = "structured_atomic"
    EXTRACTED_TRIPLE = "extracted_triple"
    EMERGENT_STRUCTURE = "emergent_structure"


# Per-tier default confidence floor. Populated by the tier pipelines; the
# dual-extractor gate in Tier 2 refines the value per-triple.
TIER_CONFIDENCE_FLOOR = {
    Tier.STRUCTURED_ATOMIC: 1.0,
    Tier.EXTRACTED_TRIPLE: 0.6,
    Tier.EMERGENT_STRUCTURE: 0.3,
}


@dataclass
class ExtractedTriple:
    """A single atomic (S, R, O) triple plus extraction provenance."""
    subject: str = ""
    relation: str = ""
    obj: str = ""
    confidence: float = 1.0
    extractor: str = ""
    gate_agreement: bool = True
    source_span: str = ""

    def is_valid(self) -> bool:
        return bool(self.subject) and bool(self.relation) and bool(self.obj)


@dataclass
class TierDecision:
    """Output of the tier router + per-tier pipeline.

    `triples` is the list of (S, R, O) records to encode. Tier 1 emits one
    triple per input; Tier 2 may emit several per narrative sentence; Tier 3
    emits zero triples and relies on the canonical fallback tokens.
    """
    tier: Tier
    triples: List[ExtractedTriple] = field(default_factory=list)
    fallback_tokens: List[str] = field(default_factory=list)
    confidence: float = 1.0
    extractor_chain: List[str] = field(default_factory=list)
    raw_text: str = ""

    def is_empty(self) -> bool:
        return not self.triples and not self.fallback_tokens
