"""SpacyNERGazetteerExtractor — Tier-2 primary extractor for narrative.

Drop-in `primary=` for `decode13.extraction_pipeline.ExtractionPipeline`.

Replaces the legacy `RuleBasedFactSeparator` (regex templates over "X is Y"
and "X of Y is Z" patterns) for narrative corpora where social text
doesn't follow either pattern. Validated empirically on the EDGE
220K-record corpus in May 2026:

  metric                       legacy    spacy+gazetteer     Δ
  ─────────────────────────────────────────────────────────────
  Tier-2 share (≥1 triple)     18.6 %         90.8 %       +72.2 pp
  triples / record                1.11           2.12       +1.02
  mean confidence                 0.65 (fixed)   0.76       +0.11
  ≥0.75 confidence rate            0.0 %        85.3 %      +85.3 pp
  ms / record                     0.04           4.39        ×100

Same `.extract(sentence, anchor_subject=None) -> List[ExtractedTriple]`
interface as the other extractors. Same dual-gate compatibility (though
gate-agreement vs HeuristicNER will be low on most narrative because
HeuristicNER is capitalization-based and doesn't fire on most social text;
that's the empirical gap this extractor was built to close).

ARCHITECTURE
============
Per sentence:
  1. spaCy.ents → entity candidates (PERSON / ORG / GPE / NORP / FAC /
     LOC / EVENT). Subject candidates iterate over entities in
     left-to-right order, capped at 3 per sentence.
  2. Scan token lemmas for any gazetteer surface form. Take the closest
     match (by token distance) to the chosen subject as r. If no match →
     r = the gazetteer's `fallback` (default "mentions") with conf=0.55.
  3. Object = slug of remaining content words (drop entities, drop the
     relation token, drop stopwords/punct), capped at 6 tokens to keep
     the slug a meaningful topical anchor.

Emits ONE triple per entity. A sentence with N entities produces up to
min(N, 3) triples. Each triple shares the same (r, o) pair if they were
extracted at the same relation token — the only thing that differs is s.

PATH-B SYMMETRY
===============
The extractor's behavior is fully determined by:

  - spaCy model identifier (e.g. "en_core_web_sm")
  - gazetteer dict (json-serializable)

Both are persistable via `save(dir)` / `load(dir)`. The decode side
reconstructs the same extractor at query time, runs it on the query text,
and gets identical (s, r) atoms. Same encode-decode contract as
encode_triples — just with extracted (s, r) instead of declared (s, r).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, List, Optional, Tuple

from .tier_types import ExtractedTriple

VERSION                  = "v1"
EXTRACTOR_NAME           = "spacy_ner_gazetteer"

# spaCy entity labels that map to "subject" slot. PERSON / ORG / GPE
# (geo-political) / NORP (nationalities, religious/political groups) /
# FAC (facilities) / LOC (non-GPE locations) / EVENT cover most
# narrative shapes; deliberately excluding DATE, TIME, MONEY, PERCENT,
# ORDINAL, CARDINAL — those are object-side modifiers, not subjects.
SUBJECT_LABELS = frozenset({"PERSON", "ORG", "GPE", "NORP",
                              "FAC", "LOC", "EVENT"})

# Max entities to emit triples for per sentence. Keeps the LSH index
# from blowing up on entity-dense headlines ("Trump, Macron, Merkel
# and Erdogan met in Berlin").
MAX_ENTITIES_PER_SENTENCE = 3

# Max content tokens in the object slug. Beyond ~6 the slug becomes a
# one-shot fingerprint rather than a topical anchor.
MAX_OBJECT_TOKENS = 6

# Confidence stamps. The gazetteer match gets a higher score because
# the relation is grounded in a curated vocabulary; the `mentions`
# fallback gets a lower score so it falls below the ExtractionPipeline
# dual-gate threshold (0.6) when used in a real pipeline.
CONFIDENCE_GAZETTEER_MATCH = 0.80
CONFIDENCE_MENTIONS_FALLBACK = 0.55

_WORD_OK = re.compile(r"[A-Za-z][A-Za-z0-9_'-]*")


def _slug(text: str) -> str:
    """Lowercase + underscore-join, matching the style of decode13/extractors.py."""
    toks = _WORD_OK.findall(text or "")
    return "_".join(t.lower() for t in toks).strip("_")


class SpacyNERGazetteerExtractor:
    """Tier-2 primary extractor.

    Instantiate either with explicit spaCy + gazetteer objects:

        from decode13.extractors_ner_gazetteer import SpacyNERGazetteerExtractor
        import spacy
        nlp = spacy.load("en_core_web_sm")
        with open("edge_relation_gazetteer.json") as f:
            gaz = json.load(f)
        extractor = SpacyNERGazetteerExtractor(nlp, gaz)

    or by passing path-like arguments (deferred load):

        extractor = SpacyNERGazetteerExtractor(
            spacy_model="en_core_web_sm",
            gazetteer_path="/path/to/edge_relation_gazetteer.json",
        )
    """

    version: str        = VERSION
    extractor_name: str = EXTRACTOR_NAME

    def __init__(
        self,
        nlp: Optional[Any] = None,
        gazetteer: Optional[dict] = None,
        *,
        spacy_model: Optional[str] = None,
        gazetteer_path: Optional[str] = None,
    ):
        # Resolve spaCy
        if nlp is None:
            if not spacy_model:
                raise ValueError(
                    "SpacyNERGazetteerExtractor: pass either `nlp` "
                    "(a loaded spaCy Language) or `spacy_model` "
                    "(e.g. 'en_core_web_sm')")
            import spacy
            nlp = spacy.load(spacy_model)
        self.nlp = nlp
        # spaCy's nlp.meta["name"] is the bare model name (e.g. "core_web_sm");
        # the loadable identifier prepends the language tag (e.g.
        # "en_core_web_sm"). When inferring from a loaded Language, recombine.
        if spacy_model:
            self._spacy_model = spacy_model
        else:
            meta = getattr(nlp, "meta", {}) or {}
            bare = meta.get("name", "unknown")
            lang = meta.get("lang", "")
            self._spacy_model = f"{lang}_{bare}" if lang else bare

        # Resolve gazetteer
        if gazetteer is None:
            if not gazetteer_path:
                raise ValueError(
                    "SpacyNERGazetteerExtractor: pass either `gazetteer` "
                    "(a dict) or `gazetteer_path` (path to JSON)")
            with open(gazetteer_path) as f:
                gazetteer = json.load(f)
        if "relations" not in gazetteer:
            raise ValueError(
                "gazetteer missing required 'relations' key; "
                "see edge_relation_gazetteer.json for shape")
        self.gazetteer = gazetteer
        self.fallback_relation = gazetteer.get("fallback", "mentions")

        # Build inverse: surface lemma -> canonical relation. Cheap O(1)
        # lookup on the hot path.
        self._surface_to_canonical: dict[str, str] = {}
        for canonical, surfaces in gazetteer["relations"].items():
            self._surface_to_canonical[canonical.lower()] = canonical
            for s in surfaces:
                self._surface_to_canonical[s.lower()] = canonical

    # ── core extract ──────────────────────────────────────────────────

    def extract(
        self,
        sentence: str,
        anchor_subject: Optional[str] = None,  # accepted for interface compat
    ) -> List[ExtractedTriple]:
        sent = (sentence or "").strip()
        if not sent:
            return []
        doc = self.nlp(sent)

        entities = [e for e in doc.ents if e.label_ in SUBJECT_LABELS]
        if not entities:
            return []

        out: List[ExtractedTriple] = []
        for ent in entities[:MAX_ENTITIES_PER_SENTENCE]:
            s_slug = _slug(ent.text)
            if not s_slug:
                continue
            r_canonical, r_idx = self._find_relation_token(doc, ent)
            if r_canonical is None:
                r_canonical = self.fallback_relation
                conf = CONFIDENCE_MENTIONS_FALLBACK
            else:
                conf = CONFIDENCE_GAZETTEER_MATCH
            o_slug = self._build_object_slug(doc, ent, r_idx) or "context"
            out.append(ExtractedTriple(
                subject=s_slug,
                relation=r_canonical,
                obj=o_slug,
                confidence=conf,
                extractor=self.extractor_name,
                gate_agreement=False,
                source_span=sent,
            ))
        return out

    # ── internals ─────────────────────────────────────────────────────

    def _find_relation_token(self, doc, subject_span) -> Tuple[Optional[str], Optional[int]]:
        """Return (canonical_relation, token_idx) or (None, None) for no match.

        Prefers the closest match by token distance to the subject in
        either direction. Linear over the doc, cheap relative to spaCy's
        per-token pipeline cost."""
        best_canonical: Optional[str] = None
        best_idx: Optional[int]       = None
        best_dist = 10_000
        sj_mid = (subject_span.start + subject_span.end) // 2
        for tok in doc:
            lemma = (tok.lemma_ or tok.text).lower()
            canonical = self._surface_to_canonical.get(lemma)
            if canonical is None:
                continue
            dist = abs(tok.i - sj_mid)
            if dist < best_dist:
                best_dist = dist
                best_canonical = canonical
                best_idx = tok.i
        return best_canonical, best_idx

    def _build_object_slug(self, doc, subject_span, relation_idx) -> str:
        """Object slug = content tokens minus subject, minus relation, minus
        other entities and stopwords. Capped at MAX_OBJECT_TOKENS."""
        skip = set(range(subject_span.start, subject_span.end))
        if relation_idx is not None:
            skip.add(relation_idx)
        # Other entities are their own triples — don't bleed them into the
        # object of this triple.
        for ent in doc.ents:
            if ent.label_ in SUBJECT_LABELS and ent.start != subject_span.start:
                skip.update(range(ent.start, ent.end))
        kept: list[str] = []
        for tok in doc:
            if tok.i in skip:
                continue
            if tok.is_stop or tok.is_punct or tok.is_space:
                continue
            if not _WORD_OK.fullmatch(tok.text):
                continue
            kept.append(tok.text.lower())
            if len(kept) >= MAX_OBJECT_TOKENS:
                break
        return "_".join(kept).strip("_")

    # ── persistence (encode-decode symmetry artifact) ─────────────────

    def save(self, dir_path: str) -> str:
        """Persist extractor configuration so the decode side can rebuild
        an identical extractor at query time. Returns the artifact path.

        The artifact does NOT bundle the spaCy model itself (it'd be
        ~12 MB); just the *identifier*. The decode side must have the
        same model installed. Add the model name to your environment
        bootstrap (pip + spacy download) if it isn't already.
        """
        d = Path(dir_path)
        d.mkdir(parents=True, exist_ok=True)
        artifact = {
            "extractor":       EXTRACTOR_NAME,
            "version":         VERSION,
            "spacy_model":     self._spacy_model,
            "gazetteer":       self.gazetteer,
        }
        p = d / "extractor_config.json"
        with open(p, "w") as f:
            json.dump(artifact, f, indent=2)
        return str(p)

    @classmethod
    def load(cls, dir_path: str) -> "SpacyNERGazetteerExtractor":
        """Rehydrate from a save()'d artifact. Loads the named spaCy model
        and reconstructs the gazetteer surface→canonical inverse."""
        p = Path(dir_path) / "extractor_config.json"
        with open(p) as f:
            artifact = json.load(f)
        if artifact.get("extractor") != EXTRACTOR_NAME:
            raise ValueError(
                f"artifact at {p} is for extractor "
                f"{artifact.get('extractor')!r}; expected {EXTRACTOR_NAME!r}")
        return cls(
            spacy_model    = artifact["spacy_model"],
            gazetteer      = artifact["gazetteer"],
        )
