"""TierRouter — decides which tier an input belongs to.

Shape-based routing with one extraction probe:

  - Input has non-empty S, R, O fields (or S+R with free-text "object")  →  Tier 1
  - Input is free text only  →  probe extraction → Tier 2 if it produces at
    least one valid triple, else Tier 3.

The router runs at the front of every encode. At decode time queries are
routed the same way — a query carrying explicit SRO fields goes to Tier 1
matching, a free-text query goes through decode-side extraction first.
"""

from __future__ import annotations

from typing import Dict, Optional

from .tier_types import Tier, TierDecision


class TierRouter:
    """Pure classifier. Does NOT run heavy pipelines — just inspects shape.

    The full pipelines (escape/extraction/canonical) are invoked by the
    caller after the router returns a tier assignment, so the router is
    cheap and callable in hot paths.
    """

    def __init__(self, min_field_len: int = 1, min_text_len_for_extract: int = 8):
        self.min_field_len = min_field_len
        # Below this threshold, free text is too short to extract — fall
        # directly to Tier 3 rather than emit spurious triples.
        self.min_text_len_for_extract = min_text_len_for_extract

    def classify(
        self,
        subject: str = "",
        relation: str = "",
        obj: str = "",
        text: str = "",
        explicit_sro: Optional[bool] = None,
    ) -> Tier:
        """Classify the input shape.

        `explicit_sro` overrides auto-detection — useful when the source
        format guarantees structured triples (e.g., a Wikidata JSON ingest)
        and we want to short-circuit the shape test.
        """
        if explicit_sro is True:
            return Tier.STRUCTURED_ATOMIC
        if explicit_sro is False:
            return self._classify_free_text(text or obj)

        s = (subject or "").strip()
        r = (relation or "").strip()
        o = (obj or "").strip()
        t = (text or "").strip()

        has_s = len(s) >= self.min_field_len
        has_r = len(r) >= self.min_field_len
        has_o = len(o) >= self.min_field_len

        # Full SRO triple — the canonical Tier 1 case
        if has_s and has_r and has_o:
            return Tier.STRUCTURED_ATOMIC
        # S + R with text as object — still structured (Wikidata-style
        # exports sometimes deliver the object in a text field)
        if has_s and has_r and t:
            return Tier.STRUCTURED_ATOMIC

        # Free text only — defer to extraction outcome
        free = t or o or ""
        return self._classify_free_text(free)

    def _classify_free_text(self, text: str) -> Tier:
        if len(text.strip()) < self.min_text_len_for_extract:
            return Tier.EMERGENT_STRUCTURE
        # Speculative Tier 2; final tier is decided by the extraction
        # pipeline based on whether the dual-extractor gate produces any
        # validated triples.
        return Tier.EXTRACTED_TRIPLE

    def from_record(self, record: Dict) -> Tier:
        """Convenience wrapper for dict records used by the encode path."""
        return self.classify(
            subject=record.get("subject", "") or "",
            relation=record.get("relation", "") or "",
            obj=record.get("object", "") or "",
            text=record.get("text", "") or "",
            explicit_sro=record.get("_explicit_sro"),
        )
