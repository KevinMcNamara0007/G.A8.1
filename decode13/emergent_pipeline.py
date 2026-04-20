"""EmergentStructureFallback — Tier 3.

When Tier 2 fails to produce any validated triples the input still needs
to land in the index — the plan guarantees every input is retrievable
from *somewhere*. Tier 3 reuses the existing G.A8.1 canonical pipeline
(possessive + acronym + stop-word removal + legacy tokenization, the one
that DID shatter Wikidata) to produce a fallback token list.

That's fine here: Tier 3 inputs are inherently unstructured narrative
where no atomic triple could be extracted. The canonical pipeline's
token stream is a reasonable bag-of-concepts for BSC superposition, and
the caller marks these vectors as low-confidence so ranking doesn't
treat them as authoritative.

The decode-side query path uses the tier marker to:
  - Accept Tier 3 matches as candidate answers only
  - Favor S/R abductive search over bag-of-concepts search
  - Rely on the sidecar rerank for final ordering
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from canonical.pipeline import CanonicalizationPipeline  # noqa: E402

from .escape_decode import escape_decode
from .tier_types import Tier, TierDecision


VERSION = "v1"


class EmergentStructureFallback:
    """Tier 3 — canonical bag-of-tokens fallback for free text."""

    version = VERSION

    def __init__(self, canonical: Optional[CanonicalizationPipeline] = None):
        self.canonical = canonical or CanonicalizationPipeline()

    def emit(self, text: str) -> TierDecision:
        raw = escape_decode(text or "")
        if not raw.strip():
            return TierDecision(
                tier=Tier.EMERGENT_STRUCTURE,
                fallback_tokens=[],
                confidence=0.0,
                extractor_chain=["escape_decode(empty)"],
                raw_text="",
            )
        stream = self.canonical.canonicalize(text=raw)
        return TierDecision(
            tier=Tier.EMERGENT_STRUCTURE,
            fallback_tokens=stream.tokens,
            confidence=0.3,
            extractor_chain=[
                "escape_decode",
                "canonical.full",
                "emergent_fallback",
            ],
            raw_text=raw,
        )
