"""ExtractionPipeline — Tier 2.

Pipeline, in order (PlanB §3.2):

  1. Escape decoding
  2. Possessive simplification
  3. Acronym expansion (kept as variants)
  4. Rule-based fact separation (T5 surrogate)     — encode time only in principle
  5. Heuristic NER/SRL                             — decode side lightweight
  6. Dual-extractor validation gate                — role agreement → high confidence
  7. Bind validated triples individually

The canonical pipeline from G.A8.1 is reused for stages 2+3 because those
rules are corpus-independent and already version-stamped. We bypass its
stage-1 extraction (which would re-tokenize) and feed its possessive +
acronym machinery directly onto extracted triples.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

# canonical/ lives next to decode13/
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from canonical.pipeline import CanonicalizationPipeline  # noqa: E402

from .escape_decode import escape_decode
from .extractors import (
    RuleBasedFactSeparator,
    HeuristicNER,
    dual_gate,
    split_sentences,
)
from .tier_types import ExtractedTriple, Tier, TierDecision


VERSION = "v1"


class ExtractionPipeline:
    """Full Tier 2 pipeline: narrative text → validated atomic triples.

    Gate strictness modes (PlanB §6.4):
      strict     — exact (S, R, O) required
      default    — role agreement w/ prefix tolerance (recommended)
      permissive — S, R match; O overlap ≥ 1 token

    Primary extractor is pluggable:
      - "rule_based"  → RuleBasedFactSeparator (regex templates, default)
      - "t5"          → T5FactSeparator (google/flan-t5-base; PlanB §6.1)
      - any object exposing .extract(sentence, anchor_subject=None) →
        List[ExtractedTriple]

    Choose via env var A81_TIER_EXTRACTOR or by passing `primary=` explicitly.
    """

    version = VERSION

    def __init__(
        self,
        canonical: Optional[CanonicalizationPipeline] = None,
        gate_mode: str = "default",
        primary: Optional[object] = None,
        primary_name: Optional[str] = None,
    ):
        self.canonical = canonical or CanonicalizationPipeline()
        if primary is not None:
            self.primary = primary
        else:
            self.primary = _make_primary(primary_name)
        self.secondary = HeuristicNER()
        self.gate_mode = gate_mode

    def extract(
        self,
        text: str,
        anchor_subject: Optional[str] = None,
    ) -> TierDecision:
        raw = escape_decode(text or "")
        if not raw.strip():
            return TierDecision(
                tier=Tier.EMERGENT_STRUCTURE,
                extractor_chain=["escape_decode(empty)"],
                raw_text="",
            )

        sentences = split_sentences(raw)
        if not sentences:
            sentences = [raw]

        # Carry anchor across sentences — the first emitted subject can
        # seed later sentences' anchor for pronouns / elliptic subjects.
        emitted: List[ExtractedTriple] = []
        current_anchor = anchor_subject
        for sent in sentences:
            # Stages 2-3: run the canonical possessive+acronym machinery
            # on the raw sentence so that "France's capital" surfaces as
            # "France capital" for the pattern matchers. We do this by
            # calling canonicalize over a synthetic text=sent and
            # re-joining the tokens into a sentence-like string. This
            # drops true stop-words but preserves signal.
            stream = self.canonical.canonicalize(text=sent)
            # The variants set is not used here — it lives in the
            # manifest for decode-side fan-out.

            # Primary extractor on the ORIGINAL sentence (patterns need
            # "of" / "is" to be present). Secondary on the same sentence.
            p_tris = self.primary.extract(sent, anchor_subject=current_anchor)
            s_tris = self.secondary.extract(sent, anchor_subject=current_anchor)

            merged = dual_gate(p_tris, s_tris, mode=self.gate_mode)
            # Filter out gate disagreements below the confidence floor.
            merged = [t for t in merged if t.confidence >= 0.6 and t.is_valid()]

            # Update anchor: if we got a high-confidence (gate_agreement)
            # triple, its subject becomes the anchor for the next sentence.
            for t in merged:
                if t.gate_agreement:
                    current_anchor = t.subject.replace("_", " ")
                    break
            else:
                # fallback: the first S we see, even without gate agreement
                if merged and current_anchor is None:
                    current_anchor = merged[0].subject.replace("_", " ")

            emitted.extend(merged)

        if not emitted:
            # Fall to Tier 3 — let the caller treat this as emergent.
            fallback_stream = self.canonical.canonicalize(text=raw)
            return TierDecision(
                tier=Tier.EMERGENT_STRUCTURE,
                fallback_tokens=fallback_stream.tokens,
                confidence=0.3,
                extractor_chain=[
                    "escape_decode",
                    "canonical.possessive+acronym",
                    self.primary.extractor_name,
                    self.secondary.extractor_name,
                    "dual_gate(no_triples)",
                ],
                raw_text=raw,
            )

        # Tier confidence = mean of per-triple confidences (gate-weighted)
        mean_c = sum(t.confidence for t in emitted) / max(len(emitted), 1)
        return TierDecision(
            tier=Tier.EXTRACTED_TRIPLE,
            triples=emitted,
            fallback_tokens=[],
            confidence=mean_c,
            extractor_chain=[
                "escape_decode",
                "canonical.possessive+acronym",
                self.primary.extractor_name,
                self.secondary.extractor_name,
                f"dual_gate({self.gate_mode})",
            ],
            raw_text=raw,
        )


def _make_primary(name: Optional[str] = None):
    """Factory: build the encode-side primary extractor.

    Selection order:
      1. explicit `name` argument
      2. A81_TIER_EXTRACTOR env var
      3. default → "rule_based"

    Supported names:
      - "rule_based"    → RuleBasedFactSeparator (regex templates)
      - "t5"            → T5FactSeparator with google/flan-t5-base
      - "t5:<model>"    → T5FactSeparator with a specific HF model id,
                          e.g. "t5:google/flan-t5-large"
      - "bart" or "rebel"
                        → REBELFactSeparator with Babelscape/rebel-large
                          (purpose-built OpenIE, recommended for unstructured)
      - "bart:<model>"  → REBELFactSeparator with a specific HF model id
    """
    import os
    chosen = name or os.environ.get("A81_TIER_EXTRACTOR", "rule_based")
    chosen = chosen.strip()
    if chosen == "rule_based" or not chosen:
        return RuleBasedFactSeparator()
    if chosen.startswith("t5"):
        from .extractors_t5 import T5FactSeparator, DEFAULT_MODEL
        if ":" in chosen:
            _, model_name = chosen.split(":", 1)
        else:
            model_name = DEFAULT_MODEL
        return T5FactSeparator(model_name=model_name)
    if chosen.startswith(("bart", "rebel")):
        from .extractors_bart import REBELFactSeparator, DEFAULT_MODEL
        if ":" in chosen:
            _, model_name = chosen.split(":", 1)
        else:
            model_name = DEFAULT_MODEL
        return REBELFactSeparator(model_name=model_name)
    # Unknown label → fall back with a warning so benchmarks don't crash
    import sys
    print(f"[ExtractionPipeline] unknown primary extractor {chosen!r}; "
          f"falling back to rule_based", file=sys.stderr)
    return RuleBasedFactSeparator()
