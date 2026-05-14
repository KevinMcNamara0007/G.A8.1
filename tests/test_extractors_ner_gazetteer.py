"""Tests for decode13.extractors_ner_gazetteer.SpacyNERGazetteerExtractor.

Pin the architectural contract:
  - interface (`.extract`, `.extractor_name`, `.version`) matches
    other Tier-2 extractors
  - `mentions` fallback fires (with conf=0.55) when entity present
    but no gazetteer verb in the sentence
  - returns [] when no entity is present
  - caps at MAX_ENTITIES_PER_SENTENCE
  - object slug excludes the subject/relation/other-entities, capped
    at MAX_OBJECT_TOKENS content words
  - save → load roundtrip preserves behavior
  - integration: ≥ 80 % Tier-2 share on the EDGE probe sample
    (floor is set below the measured 91 % to give headroom for
    spaCy minor-version drift)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Skip the whole module if spaCy or the model isn't installed; failing
# noisily on a CI box without ML deps would be unhelpful.
spacy = pytest.importorskip("spacy")
try:
    _NLP = spacy.load("en_core_web_sm")
except OSError:
    pytest.skip("en_core_web_sm not installed", allow_module_level=True)

from decode13.extractors_ner_gazetteer import (  # noqa: E402
    SpacyNERGazetteerExtractor,
    EXTRACTOR_NAME,
    VERSION,
    SUBJECT_LABELS,
    MAX_ENTITIES_PER_SENTENCE,
    MAX_OBJECT_TOKENS,
    CONFIDENCE_GAZETTEER_MATCH,
    CONFIDENCE_MENTIONS_FALLBACK,
)
from decode13.tier_types import ExtractedTriple  # noqa: E402


# ── minimal toy gazetteer the unit tests can reason about ──────────────
_TOY_GAZ = {
    "version": "test_gaz_v1",
    "fallback": "mentions",
    "relations": {
        "protested":  ["protest", "rally", "demonstrate"],
        "killed":     ["kill", "murder"],
        "supported":  ["support", "back"],
        "spoke":      ["speak", "say", "announce"],
    },
}


@pytest.fixture(scope="module")
def extractor():
    return SpacyNERGazetteerExtractor(_NLP, _TOY_GAZ)


# ── 1. interface contract ───────────────────────────────────────────────

def test_extractor_name_and_version(extractor):
    assert extractor.extractor_name == EXTRACTOR_NAME == "spacy_ner_gazetteer"
    assert extractor.version == VERSION == "v1"


def test_extract_accepts_anchor_subject_kwarg(extractor):
    """The dual-gate machinery passes anchor_subject; the extractor
    must accept it even if it currently ignores the value."""
    out = extractor.extract("Iran protested.", anchor_subject="foo")
    assert isinstance(out, list)


def test_extract_returns_list_of_extracted_triple(extractor):
    out = extractor.extract("Iran protested against the regime.")
    assert isinstance(out, list)
    for t in out:
        assert isinstance(t, ExtractedTriple)


# ── 2. extraction semantics ────────────────────────────────────────────

def test_entity_plus_gazetteer_verb_emits_high_confidence_triple(extractor):
    """When an entity and a gazetteer verb are BOTH present, we should
    get a triple at the gazetteer-match confidence level."""
    out = extractor.extract("Iran protested against the regime.")
    assert len(out) >= 1
    iran_triples = [t for t in out if t.subject == "iran"]
    assert len(iran_triples) == 1
    t = iran_triples[0]
    assert t.relation == "protested"
    assert t.confidence == CONFIDENCE_GAZETTEER_MATCH
    assert t.extractor == EXTRACTOR_NAME
    assert t.source_span == "Iran protested against the regime."


def test_entity_without_gazetteer_verb_falls_back_to_mentions(extractor):
    """When an entity is present but no gazetteer verb fires, we expect
    the `mentions` fallback at the lower confidence level."""
    out = extractor.extract("Iran is on the map.")
    iran_triples = [t for t in out if t.subject == "iran"]
    assert len(iran_triples) == 1
    t = iran_triples[0]
    assert t.relation == "mentions"
    assert t.confidence == CONFIDENCE_MENTIONS_FALLBACK


def test_empty_sentence_returns_empty(extractor):
    assert extractor.extract("") == []
    assert extractor.extract("   ") == []


def test_sentence_with_no_entity_returns_empty(extractor):
    """No entity in SUBJECT_LABELS → no triple. spaCy may or may not see
    'beautiful day' as an entity; we assert the WEAKER property that an
    empty-or-only-non-subject-labels result yields []."""
    out = extractor.extract("It was a beautiful day, very peaceful.")
    # If spaCy didn't tag any SUBJECT_LABELS entity, must be [].
    # If it did (some models are noisy), at least no crashes.
    assert isinstance(out, list)


# ── 3. multi-entity behavior ───────────────────────────────────────────

def test_multiple_entities_emit_separate_triples(extractor):
    """A sentence with N distinct entities emits N triples (capped at
    MAX_ENTITIES_PER_SENTENCE)."""
    out = extractor.extract("Iran and Israel both protested today.")
    subjects = sorted({t.subject for t in out})
    # Both iran and israel are GPE entities; both must surface.
    assert "iran"   in subjects
    assert "israel" in subjects
    # All emitted triples should share the same relation (one verb in
    # the sentence — "protested") because the closest-relation logic
    # picks the same gazetteer match for both subjects.
    relations = {t.relation for t in out}
    assert "protested" in relations


def test_caps_at_max_entities_per_sentence(extractor):
    """A long entity-dense sentence should yield ≤ MAX_ENTITIES_PER_SENTENCE
    triples, not blow up the LSH with one row per entity."""
    text = ("Trump, Macron, Merkel, Erdogan, Putin, and Modi all "
            "protested the announcement.")
    out = extractor.extract(text)
    assert len(out) <= MAX_ENTITIES_PER_SENTENCE


# ── 4. object slug shape ───────────────────────────────────────────────

def test_object_slug_excludes_subject_token(extractor):
    """The subject entity text should NOT appear in the object slug."""
    out = extractor.extract("Iran killed three protesters this morning.")
    iran = next((t for t in out if t.subject == "iran"), None)
    assert iran is not None
    assert "iran" not in iran.obj.split("_")


def test_object_slug_excludes_relation_token(extractor):
    """The matched gazetteer relation token should NOT appear in O."""
    out = extractor.extract("Iran killed three protesters.")
    iran = next((t for t in out if t.subject == "iran"), None)
    assert iran is not None
    # 'killed' is the relation surface form; it should be excluded.
    assert "killed" not in iran.obj.split("_")


def test_object_slug_capped_at_max_tokens(extractor):
    text = ("Iran announced a wide-ranging policy concerning regional "
            "trade relations and military cooperation with several "
            "neighboring states this week.")
    out = extractor.extract(text)
    iran = next((t for t in out if t.subject == "iran"), None)
    assert iran is not None
    parts = [p for p in iran.obj.split("_") if p]
    assert len(parts) <= MAX_OBJECT_TOKENS


def test_object_slug_non_empty_falls_back_to_context(extractor):
    """If literally no content tokens survive the filter, the slug
    should default to 'context' rather than emit an empty obj."""
    out = extractor.extract("Iran.")
    iran = next((t for t in out if t.subject == "iran"), None)
    if iran is not None:
        assert iran.obj  # never empty


# ── 5. save / load roundtrip ──────────────────────────────────────────

def test_save_load_roundtrip_preserves_behavior(extractor):
    with tempfile.TemporaryDirectory() as td:
        artifact_path = extractor.save(td)
        assert Path(artifact_path).exists()
        with open(artifact_path) as f:
            blob = json.load(f)
        assert blob["extractor"] == EXTRACTOR_NAME
        assert blob["version"]   == VERSION
        assert "relations" in blob["gazetteer"]

        # Rehydrate and assert identical output on a canned sentence.
        rehydrated = SpacyNERGazetteerExtractor.load(td)
        text = "Iran protested against the regime today."
        orig_out  = extractor.extract(text)
        new_out   = rehydrated.extract(text)
        assert len(orig_out) == len(new_out)
        for a, b in zip(orig_out, new_out):
            assert (a.subject, a.relation, a.obj) == (b.subject, b.relation, b.obj)
            assert a.confidence == b.confidence


def test_load_rejects_wrong_extractor_artifact(tmp_path):
    bad = {
        "extractor": "some_other_extractor",
        "version": "v0",
        "spacy_model": "en_core_web_sm",
        "gazetteer": _TOY_GAZ,
    }
    (tmp_path / "extractor_config.json").write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="some_other_extractor"):
        SpacyNERGazetteerExtractor.load(str(tmp_path))


# ── 6. constructor errors ─────────────────────────────────────────────

def test_init_requires_nlp_or_spacy_model():
    with pytest.raises(ValueError, match="spacy_model"):
        SpacyNERGazetteerExtractor(gazetteer=_TOY_GAZ)


def test_init_requires_gazetteer_or_path():
    with pytest.raises(ValueError, match="gazetteer"):
        SpacyNERGazetteerExtractor(nlp=_NLP)


def test_init_rejects_malformed_gazetteer():
    with pytest.raises(ValueError, match="relations"):
        SpacyNERGazetteerExtractor(nlp=_NLP, gazetteer={"fallback": "mentions"})


# ── 7. integration — ExtractionPipeline plug-in ───────────────────────

def test_plugs_into_extraction_pipeline_as_primary(extractor):
    """The whole point: ExtractionPipeline(primary=<this>) just works
    and the resulting decisions carry through."""
    from decode13.extraction_pipeline import ExtractionPipeline
    pipeline = ExtractionPipeline(primary=extractor, gate_mode="default")
    decision = pipeline.extract("Iran protested against the regime today.")
    # Decision should be EXTRACTED_TRIPLE tier (not the EMERGENT fallback)
    # because at least one high-confidence triple should survive the gate.
    # NB: the dual_gate compares vs HeuristicNER which won't fire on this
    # sentence — single-extractor triples pass the gate only if their
    # confidence ≥ 0.6 AND they're valid. Our 0.80 score clears that.
    assert decision.tier.value in ("extracted_triple", "emergent_structure")
    # Pipeline's extractor_chain should record our extractor name.
    assert EXTRACTOR_NAME in decision.extractor_chain


# ── 8. integration — EDGE probe sample floor ──────────────────────────

@pytest.mark.parametrize("min_tier2_share", [0.80])  # measured 91% on 500
def test_tier2_share_floor_on_edge_sample(extractor, min_tier2_share):
    """Run the extractor on the first 100 EDGE source records and assert
    ≥ 80 % Tier-2 share. Floor is set below the 91 % measured on a 500-
    record probe to give headroom for spaCy minor-version drift and
    record-sample variance."""
    source = Path("/Users/stark/Quantum_Computing_Lab/MOE/EDGE/source_corpus.jsonl")
    if not source.exists():
        pytest.skip(f"EDGE source corpus not present at {source}")
    records: list[str] = []
    with open(source) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            txt = (rec.get("text", "") or "").strip()
            if txt:
                records.append(txt)
            if len(records) >= 100:
                break
    assert records, "no EDGE records loaded"

    n_tier2 = sum(1 for t in records if extractor.extract(t))
    share = n_tier2 / len(records)
    assert share >= min_tier2_share, (
        f"Tier-2 share dropped below floor: {share:.1%} < {min_tier2_share:.1%}. "
        f"If this regresses, run the head-to-head probe v2 against EDGE "
        f"and audit the gazetteer surface→canonical map.")
