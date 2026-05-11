"""StructuredAtomicPipeline — Tier 1.

The source provides S, R, O as discrete fields. The pipeline gets out of
the way: escape decoding only, everything else passes through. Compound
tokens stay compound; generic helper words stay put.

Contract:
  - Input is a triple with explicit subject, relation, object.
  - Output tokens are [subject_atom, relation_atom, object_atom].
  - No underscore splitting, no stop-word removal, no stemming, no
    possessive normalization, no acronym expansion.

Rationale from Phase 1 (PlanB §1.3): uniform canonicalization shattered
4824/5000 Wikidata queries at the tokenization layer. For Tier 1, the
source has already done the extraction — the pipeline's job is to not
undo it.
"""

from __future__ import annotations

from typing import List

from .escape_decode import escape_decode
from .tier_types import ExtractedTriple, Tier, TierDecision


VERSION = "v1"


def _atomize(field_value: str) -> str:
    """Collapse whitespace and lowercase the field; keep underscores.

    Lowercasing is the corpus-query symmetry contract for Tier 1:
    `_atomize` is called by both the encode-side
    `StructuredAtomicPipeline.emit` (worker_encode.py:549) and the
    query-side `decode13.QueryService.query` (query_service.py:494
    via `[a.lower().strip() ...]`). The codebook itself is hash-mode
    and case-sensitive in v13.1 — `cb.encode_token("Q1860")` and
    `cb.encode_token("q1860")` produce different sparse signatures.
    The lowercase boundary at this function is what makes encode and
    query produce matching VSAs. Verified empirically 2026-05-07 in
    the M3 wire test (lowercase path → Hit@1 = 1.0; capitalized
    path → 0.30 / rank 3 for the same gold record). Anything that
    moves or replaces `_atomize` must preserve the lowercase
    boundary or Hit@1 will collapse silently.

    Underscores are kept — that is the whole point of Tier 1.
    """
    if not field_value:
        return ""
    s = escape_decode(field_value)
    # Internal whitespace → single space (source-side typos shouldn't break
    # atomic match). We keep the whole thing as a single token by using a
    # single-underscore separator internally would be wrong; atomic means
    # the field is ONE token as-supplied.
    s = " ".join(s.split())
    return s.lower()


class StructuredAtomicPipeline:
    """Tier 1 pass-through binder.

    `emit(triple_dict)` returns a TierDecision with one ExtractedTriple
    carrying the atomized S/R/O tokens. Caller feeds those tokens to
    `ehc.TokenCodebook.encode_token()` and superposes.
    """

    version = VERSION

    def emit(
        self,
        subject: str,
        relation: str,
        obj: str = "",
        text: str = "",
    ) -> TierDecision:
        s_tok = _atomize(subject)
        r_tok = _atomize(relation)
        # Wikidata exports sometimes place object in "text" when unambiguous
        o_source = obj if obj else text
        o_tok = _atomize(o_source)

        tri = ExtractedTriple(
            subject=s_tok,
            relation=r_tok,
            obj=o_tok,
            confidence=1.0,
            extractor="structured_atomic",
            gate_agreement=True,
            source_span=f"{subject} {relation} {o_source}".strip(),
        )
        # Only valid triples are emitted; if the source was malformed the
        # router should have sent it to Tier 2/3 instead. We still guard
        # here because the escape-decode step can strip S or O down to "".
        triples = [tri] if tri.is_valid() else []
        fallback: List[str] = []
        if not triples:
            # All three fields were empty after escape-decode. Fall to the
            # raw joined text so the sidecar path can still surface it.
            fallback = [t for t in [s_tok, r_tok, o_tok] if t]

        return TierDecision(
            tier=Tier.STRUCTURED_ATOMIC,
            triples=triples,
            fallback_tokens=fallback,
            confidence=1.0,
            extractor_chain=["structured_atomic"],
            raw_text=tri.source_span,
        )

    def tokens_from_triple(self, tri: ExtractedTriple) -> List[str]:
        """Return the atomic tokens to bind for this triple.

        Path-B-symmetric SRO Tier-1 contract: only the (s, r) atoms
        enter the vector. The object atom O is preserved in the
        sidecar (`value` column) as its own canonical form O' — a
        "small semantic summary" available at query time for
        filtering, re-ranking, or display, but never for the
        primary-retrieval LSH bucketing.

        Why drop tri.obj from the vector: encoding it adds positions
        that V_query (which has only s, r at lookup time) doesn't
        share, which causes LSH hash signatures to diverge between
        encode and query, and the gold record stops landing in the
        candidate set. Dropping it makes V_record bit-identical to
        V_query for the same (s, r) — Path B symmetry — restoring
        ~100% unique-key Hit@1 while keeping the full O reachable
        through the sidecar.
        """
        return [t for t in [tri.subject, tri.relation] if t]

    def emit_query(
        self,
        subject: str = "",
        relation: str = "",
        obj: str = "",
        text: str = "",
    ) -> TierDecision:
        """Query-time variant that accepts partial SRO.

        A Tier 1 query commonly supplies only (S, R) and asks the index
        for the best O match. Unlike `emit()` (encode side) we do NOT
        require all three fields populated — an empty role simply drops
        out of the binding token list. The ExtractedTriple is still
        returned for trace / tokens_from_triple, with empty slots blank.
        """
        s_tok = _atomize(subject)
        r_tok = _atomize(relation)
        o_source = obj if obj else text
        o_tok = _atomize(o_source)

        tri = ExtractedTriple(
            subject=s_tok,
            relation=r_tok,
            obj=o_tok,
            confidence=1.0,
            extractor="structured_atomic_query",
            gate_agreement=True,
            source_span=f"{subject} {relation} {o_source}".strip(),
        )
        triples = [tri] if any([s_tok, r_tok, o_tok]) else []
        return TierDecision(
            tier=Tier.STRUCTURED_ATOMIC,
            triples=triples,
            confidence=1.0,
            extractor_chain=["structured_atomic_query"],
            raw_text=tri.source_span,
        )
