"""Extractors for Tier 2: RuleBasedFactSeparator + HeuristicNER.

These are surrogates for the plan's T5 fact separator (encode-side) and
lightweight NER/SRL (decode-side). They are NOT production extractors;
they exist so the architecture — tier routing, dual-extractor gate, and
confidence calibration — can be validated end-to-end without a neural
extractor dependency. Swap for real T5 and LightweightSRL via the same
interface once §6.3 fidelity measurements are done.

Interface contract:
    class Extractor:
        def extract(self, sentence: str) -> List[ExtractedTriple]: ...

The dual-extractor gate compares outputs on the same source span — it
doesn't care which extractor produced which triple as long as both
implement `extract()`.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .tier_types import ExtractedTriple


VERSION = "rulebased-v1"
NER_VERSION = "heuristic-ner-v1"


# ─── sentence splitting ───────────────────────────────────────
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def split_sentences(text: str) -> List[str]:
    text = text.strip()
    if not text:
        return []
    # Period-ended sentences plus the last fragment (which might not end
    # in punctuation).
    parts = _SENT_SPLIT.split(text)
    return [p.strip(" .,;") for p in parts if p.strip()]


# ─── light tokenization (shared) ──────────────────────────────
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'-]*|\d[\d,\.]*")


def _tokens(sentence: str) -> List[str]:
    return _WORD_RE.findall(sentence)


# ─── auxiliary / copula verbs ─────────────────────────────────
_COPULAS = frozenset({"is", "are", "was", "were", "be", "been", "being"})
_POSSESSION = frozenset({"has", "have", "had"})
_STOP_SHORT = frozenset({
    "the", "a", "an", "of", "to", "in", "on", "at", "for", "by",
    "and", "or", "but", "with", "from", "as",
})

# Wh-words and interrogatives — never valid S/R/O atoms. A triple whose
# any role contains one of these should be rejected; it's a query artifact.
_WH_WORDS = frozenset({
    "what", "where", "when", "who", "whom", "why", "which", "how",
    "whose", "whether",
})


def _has_wh(slug: str) -> bool:
    """True if any component of the slug is a wh-word."""
    return any(p in _WH_WORDS for p in slug.split("_"))


def _normalize(token: str) -> str:
    return token.lower().strip(".,;:\"'()[]")


def _slug(tokens: List[str]) -> str:
    """Join a phrase into a single atomic token (Tier 1-style compound).

    Multi-word subjects/objects are bound atomically so they survive
    retrieval. This is the Tier 2 bridge to Tier 1's atomic guarantee —
    once extracted, each emitted triple's S/R/O is a single atom.
    """
    parts = [_normalize(t) for t in tokens if t]
    parts = [p for p in parts if p]
    return "_".join(parts) if parts else ""


# ═══════════════════════════════════════════════════════════════
#  RuleBasedFactSeparator — "T5 surrogate"
# ═══════════════════════════════════════════════════════════════

# Ordered pattern list. Earlier patterns fire first when multiple match.
# Each entry: (label, regex over the lowercased sentence, role assigner).
#
# Role assigners receive the match.groupdict() and return (S, R, O) as
# token-list tuples (order preserved, caller slugs them). Returning None
# means the pattern did not actually apply despite matching.

_PATTERNS: List[Tuple[str, "re.Pattern"]] = [
    # "the R of S is O"            -> (S, R, O)           most common
    ("rel_of_subj_is_obj",
     re.compile(r"\bthe\s+(?P<r>[a-z][a-z_ -]+?)\s+of\s+(?P<s>[a-z][a-z0-9_ '-]+?)\s+(?:is|are|was|were)\s+(?P<o>[a-z0-9][a-z0-9_ '-]+)")),
    # "S's R is O"                -> (S, R, O)
    ("poss_rel_is_obj",
     re.compile(r"\b(?P<s>[a-z][a-z0-9_'-]+)\'s\s+(?P<r>[a-z][a-z_ -]+?)\s+(?:is|are|was|were)\s+(?P<o>[a-z0-9][a-z0-9_ '-]+)")),
    # "S has/have O"              -> (S, has, O)
    ("poss_have",
     re.compile(r"\b(?P<s>[a-z][a-z0-9_'-]+)\s+(?:has|have|had)\s+(?P<o>[a-z0-9][a-z0-9_ '-]+)")),
    # "S is/are a/an R"           -> (S, is_a, R)
    ("is_a",
     re.compile(r"\b(?P<s>[a-z][a-z0-9_'-]+)\s+(?:is|are|was|were)\s+(?:a|an|the)\s+(?P<o>[a-z0-9][a-z0-9_ '-]+)")),
    # Question form: "is/was S a O ?" -> (S, is_a, O). The interrogative
    # form drops S before the copula; we need an explicit pattern.
    ("question_is_a",
     re.compile(r"^(?:is|are|was|were)\s+(?P<s>[a-z][a-z0-9_ '-]+?)\s+(?:a|an|the)\s+(?P<o>[a-z0-9][a-z0-9_ '-]+)")),
    # "native R (is) O" (side-fact from the "France" example)
    ("native_of",
     re.compile(r"native\s+(?P<r>[a-z_ -]+?)\s+(?P<o>[a-z0-9][a-z0-9_ '-]+)")),
]


class RuleBasedFactSeparator:
    """T5 surrogate: produces one or more (S, R, O) triples per sentence.

    The pattern set is narrow on purpose — when a pattern does NOT match,
    the sentence falls through to Tier 3. This is the plan's "extraction
    failure taxonomy": conservative extraction + graceful degradation
    beats broad extraction with silent low-quality triples.
    """

    version = VERSION
    extractor_name = "rule_based_fact_separator"

    def extract(
        self,
        sentence: str,
        anchor_subject: Optional[str] = None,
    ) -> List[ExtractedTriple]:
        """Extract triples from a single sentence.

        `anchor_subject` is a hint from context — e.g., when the previous
        sentence established that "France" is the topic, subsequent
        sentences can inherit it for patterns that produce R/O but leave
        S ambiguous (pronouns etc.). Not used heavily here; kept for when
        a real extractor replaces this one.
        """
        sent = escape_strip_punct(sentence.lower())
        out: List[ExtractedTriple] = []

        for label, pat in _PATTERNS:
            m = pat.search(sent)
            if not m:
                continue
            gd = m.groupdict()
            tri = self._from_groups(label, gd, sentence, anchor_subject)
            if tri is not None and tri.is_valid():
                out.append(tri)

        return out

    def _from_groups(
        self,
        label: str,
        gd: dict,
        source_span: str,
        anchor_subject: Optional[str],
    ) -> Optional[ExtractedTriple]:
        if label == "rel_of_subj_is_obj":
            s = _slug(_tokens(gd["s"]))
            r = _slug(_tokens(gd["r"]))
            o = _slug(_tokens(gd["o"]))
        elif label == "poss_rel_is_obj":
            s = _slug(_tokens(gd["s"]))
            r = _slug(_tokens(gd["r"]))
            o = _slug(_tokens(gd["o"]))
        elif label == "poss_have":
            s = _slug(_tokens(gd["s"]))
            r = "has"
            o = _slug(_tokens(gd["o"]))
        elif label == "is_a":
            s = _slug(_tokens(gd["s"]))
            r = "is_a"
            o = _slug(_tokens(gd["o"]))
        elif label == "question_is_a":
            s = _slug(_tokens(gd["s"]))
            r = "is_a"
            o = _slug(_tokens(gd["o"]))
        elif label == "native_of":
            # (anchor_subject, language, <o>) / (anchor_subject, tongue, <o>)
            if not anchor_subject:
                return None
            s = _slug(_tokens(anchor_subject))
            r = _slug(_tokens(gd["r"]))
            o = _slug(_tokens(gd["o"]))
        else:
            return None

        if not (s and r and o):
            return None
        # Reject triples where any role contains a wh-word — those are
        # query artifacts, not facts. Let caller fall to Tier 3.
        if _has_wh(s) or _has_wh(r) or _has_wh(o):
            return None
        # Strip trailing non-informative words from O (e.g., "people" in
        # "10,000,000 people"). Keep the informative head for atomic bind.
        o = _trim_trailing_filler(o)

        return ExtractedTriple(
            subject=s, relation=r, obj=o,
            confidence=0.8,
            extractor=self.extractor_name,
            gate_agreement=False,  # set by the gate, not here
            source_span=source_span.strip(),
        )


def escape_strip_punct(s: str) -> str:
    # Keep a few compounds like "10,000,000" readable by spaces around
    # them; the tokenizer will strip the commas.
    return re.sub(r"[\.;:\"]", " ", s)


def _trim_trailing_filler(slug: str) -> str:
    # Drop trailing stop-like words from compounds: "paris_home_to" → "paris"
    tail_stop = frozenset({"home", "to", "in", "on", "at", "of", "and",
                           "with", "by", "for", "people", "persons"})
    parts = slug.split("_")
    while len(parts) > 1 and parts[-1] in tail_stop:
        parts.pop()
    return "_".join(parts)


# ═══════════════════════════════════════════════════════════════
#  HeuristicNER — independent extractor used by the dual-gate
# ═══════════════════════════════════════════════════════════════

# Capitalized multi-word entity, allowing inner caps + digits.
_ENTITY_RE = re.compile(r"\b([A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*)*)\b")
# Number-like entity for population/count relations.
_NUM_RE = re.compile(r"\b\d[\d,\.]{2,}\b")


class HeuristicNER:
    """Independent decode-side extractor (LightweightSRL surrogate).

    Mechanism: pick capitalized entities + numeric tokens as nominals,
    look for relational verbs/prepositions between them, emit triples.
    This is DIFFERENT from the rule-based separator — different error
    modes — which is the whole point of the dual-extractor gate.
    """

    version = NER_VERSION
    extractor_name = "heuristic_ner"

    def extract(
        self,
        sentence: str,
        anchor_subject: Optional[str] = None,
    ) -> List[ExtractedTriple]:
        sent = sentence.strip()
        if not sent:
            return []

        entities = self._find_entities(sent)
        numbers = [(m.group(0), m.start(), m.end()) for m in _NUM_RE.finditer(sent)]

        out: List[ExtractedTriple] = []

        # Fire on the same "R of S is O" shape but via a different
        # mechanism: find "X is Y" anywhere in the sentence.
        low = sent.lower()

        # Question form (e): "Was <Entity> a <Entity>?" or "Is X a Y"
        m = re.search(r"^(?:Is|Are|Was|Were)\s+([A-Z][A-Za-z0-9 ]+?)\s+(?:a|an|the)\s+([A-Za-z][A-Za-z0-9 ]+)", sent)
        if m:
            s_slug = _slug(_tokens(m.group(1)))
            o_slug = _slug(_tokens(m.group(2)))
            if s_slug and o_slug and not _has_wh(s_slug) and not _has_wh(o_slug):
                out.append(ExtractedTriple(
                    subject=s_slug, relation="is_a", obj=o_slug,
                    confidence=0.7,
                    extractor=self.extractor_name,
                    gate_agreement=False,
                    source_span=sent,
                ))

        # (a) "capital of <Entity> is <Entity>"
        m = re.search(r"([a-z_]+)\s+of\s+([A-Z][A-Za-z0-9]+)\s+(?:is|are|was|were)\s+([A-Z][A-Za-z0-9]+)", sent)
        if m:
            r_slug = _slug(_tokens(m.group(1)))
            s_slug = _slug(_tokens(m.group(2)))
            o_slug = _slug(_tokens(m.group(3)))
            if s_slug and r_slug and o_slug:
                out.append(ExtractedTriple(
                    subject=s_slug, relation=r_slug, obj=o_slug,
                    confidence=0.75,
                    extractor=self.extractor_name,
                    gate_agreement=False,
                    source_span=sent,
                ))

        # (b) "<Entity>'s <rel> is <Entity>"
        m = re.search(r"([A-Z][A-Za-z0-9]+)'s\s+([a-z_]+)\s+(?:is|are|was|were)\s+([A-Z][A-Za-z0-9]+)", sent)
        if m:
            s_slug = _slug(_tokens(m.group(1)))
            r_slug = _slug(_tokens(m.group(2)))
            o_slug = _slug(_tokens(m.group(3)))
            if s_slug and r_slug and o_slug:
                out.append(ExtractedTriple(
                    subject=s_slug, relation=r_slug, obj=o_slug,
                    confidence=0.75,
                    extractor=self.extractor_name,
                    gate_agreement=False,
                    source_span=sent,
                ))

        # (c) population-style: "<Entity> ... <Number> people" with anchor
        # subject context — credits the count to the anchor.
        if anchor_subject and "people" in low:
            for tok, _, _ in numbers:
                o_slug = tok.replace(",", "").replace(".", "")
                s_slug = _slug(_tokens(anchor_subject))
                if s_slug and o_slug:
                    out.append(ExtractedTriple(
                        subject=s_slug, relation="population", obj=o_slug,
                        confidence=0.65,
                        extractor=self.extractor_name,
                        gate_agreement=False,
                        source_span=sent,
                    ))
                    break

        # (d) "native tongue <Entity>"
        m = re.search(r"native\s+([a-z_]+)\s+([A-Z][A-Za-z0-9]+)", sent)
        if m and anchor_subject:
            r_slug = _slug(_tokens(m.group(1)))
            o_slug = _slug(_tokens(m.group(2)))
            s_slug = _slug(_tokens(anchor_subject))
            if s_slug and r_slug and o_slug:
                # Map "tongue" → "language" for the anchor-population path.
                # Keep both alternates emitted so the dual gate can agree.
                r_norm = "language" if r_slug == "tongue" else r_slug
                out.append(ExtractedTriple(
                    subject=s_slug, relation=r_norm, obj=o_slug,
                    confidence=0.7,
                    extractor=self.extractor_name,
                    gate_agreement=False,
                    source_span=sent,
                ))

        return out

    def _find_entities(self, sent: str) -> List[Tuple[str, int, int]]:
        out: List[Tuple[str, int, int]] = []
        for m in _ENTITY_RE.finditer(sent):
            tok = m.group(1)
            # Skip sentence-initial "The"/"A" etc. if they happen to be
            # capitalized — they're not entities.
            first = tok.split()[0].lower()
            if first in _STOP_SHORT or first in _COPULAS or first in _POSSESSION:
                continue
            out.append((tok, m.start(), m.end()))
        return out


# ═══════════════════════════════════════════════════════════════
#  Dual-extractor gate
# ═══════════════════════════════════════════════════════════════

def dual_gate(
    primary: List[ExtractedTriple],
    secondary: List[ExtractedTriple],
    mode: str = "default",
) -> List[ExtractedTriple]:
    """Compare two extractors' outputs on the same source span.

    Returns a merged list with `gate_agreement` marked per triple. A
    triple that appears in both lists (by canonical S/R/O slug match) is
    high-confidence; single-extractor triples are medium-confidence.
    Completely missing → upstream caller will drop the sentence to Tier 3.

    Modes:
      strict      — exact (S, R, O) match required
      default     — role agreement: S agrees AND R agrees AND O agrees,
                    allowing one extractor's O to be a prefix of the
                    other's when the phrase was truncated differently
      permissive  — S and R agree; O overlap >= 1 token
    """
    # Index secondary by key for lookup
    if mode == "strict":
        keyfn = lambda t: (t.subject, t.relation, t.obj)
    elif mode == "permissive":
        keyfn = lambda t: (t.subject, t.relation)
    else:  # default
        keyfn = lambda t: (t.subject, t.relation, t.obj)

    sec_index: dict = {}
    for t in secondary:
        sec_index.setdefault(keyfn(t), []).append(t)

    out: List[ExtractedTriple] = []
    matched_secondary: set = set()

    for p in primary:
        key = keyfn(p)
        agrees = False
        if key in sec_index:
            if mode == "default":
                # Confirm O agreement with prefix tolerance.
                for s in sec_index[key]:
                    if _o_agrees(p.obj, s.obj):
                        agrees = True
                        matched_secondary.add(id(s))
                        break
            elif mode == "permissive":
                for s in sec_index[key]:
                    if _o_overlap(p.obj, s.obj):
                        agrees = True
                        matched_secondary.add(id(s))
                        break
            else:  # strict
                agrees = True
                matched_secondary.add(id(sec_index[key][0]))

        merged = ExtractedTriple(
            subject=p.subject, relation=p.relation, obj=p.obj,
            confidence=(0.95 if agrees else 0.65),
            extractor=(f"{p.extractor}+matched" if agrees else p.extractor),
            gate_agreement=agrees,
            source_span=p.source_span,
        )
        out.append(merged)

    # Include secondary-only triples (medium confidence)
    for s in secondary:
        if id(s) in matched_secondary:
            continue
        out.append(ExtractedTriple(
            subject=s.subject, relation=s.relation, obj=s.obj,
            confidence=0.6,
            extractor=s.extractor,
            gate_agreement=False,
            source_span=s.source_span,
        ))
    return out


def _o_agrees(a: str, b: str) -> bool:
    if a == b:
        return True
    # Prefix tolerance: Paris vs Paris_home_to
    return a.startswith(b) or b.startswith(a)


def _o_overlap(a: str, b: str) -> bool:
    ta = set(a.split("_"))
    tb = set(b.split("_"))
    return bool(ta & tb)
