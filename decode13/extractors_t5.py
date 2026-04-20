"""T5-based triple extractor — PlanB §6.1's "T5-small-v1.1" slot.

Uses `google/flan-t5-base` (or any instruction-tuned T5) with a structured
prompt that asks the model to emit `(subject, relation, object)` triples
per input sentence. Output is parsed into ExtractedTriple records that
plug into the same dual-extractor gate as `RuleBasedFactSeparator`.

Design:
  - Batched inference (configurable batch size). Default batch=16.
  - MPS / CUDA / CPU auto-selection.
  - Deterministic (temperature=0, beam search 4).
  - Max input 256 tokens / max output 128 tokens per sentence.
  - Encode-side only (per PlanB §6.1). Decode side uses the lightweight
    HeuristicNER surrogate or — once we wire it — a distilled SRL model.

Prompt contract:
    "Extract subject-relation-object triples from the following text.
     Output one triple per line in the format subject | relation | object.
     Text: <sentence>"

Output parsing is tolerant: each line split on "|" must yield ≥ 3 parts;
extras are collapsed into the object. Lines that don't match are dropped.
"""

from __future__ import annotations

import os
import re
import sys
from typing import List, Optional

from .tier_types import ExtractedTriple


VERSION = "t5-flan-base-v1"
DEFAULT_MODEL = "google/flan-t5-base"

# Suppress noisy HF tokenizer warning
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# transformers.generation uses torch.isin which MPS doesn't implement yet.
# Allow CPU fallback for that one op — rest of the graph still runs on MPS.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


def _pick_device(prefer: Optional[str] = None) -> str:
    import torch
    if prefer in {"cpu", "mps", "cuda"}:
        return prefer
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


_PROMPT_TEMPLATE = (
    "Extract factual triples from the text below.\n"
    "Format each triple on its own line as: subject | relation | object\n"
    "Use underscores for multi-word names (e.g., new_york, albert_einstein).\n"
    "Skip questions, commands, opinions, and generic subjects like 'this' or 'it'.\n"
    "\n"
    "Example text: The capital of France is Paris. Paris has a population of 2 million.\n"
    "Example triples:\n"
    "france | capital | paris\n"
    "paris | population | 2000000\n"
    "\n"
    "Example text: Albert Einstein was a physicist born in Ulm.\n"
    "Example triples:\n"
    "albert_einstein | occupation | physicist\n"
    "albert_einstein | place_of_birth | ulm\n"
    "\n"
    "Text: {text}\n"
    "Triples:"
)


def _slug(s: str) -> str:
    s = s.strip().lower()
    # Collapse whitespace and non-word to underscores, strip duplicates.
    s = re.sub(r"[^\w'-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


_BAD_SUBJECT_SLUGS = frozenset({
    "this", "that", "it", "they", "there", "also", "however",
    "but", "and", "who", "what", "where", "when", "why", "how",
})


# flan-t5 often emits "Subject RELATION Object" where RELATION is a
# single UPPER_CASE token (seen: "France CAPITAL Paris",
# "Einstein BIRTH_PLACE Ulm"). Match that as a fallback.
_UPPER_RELATION_RE = re.compile(
    r"(?P<s>[A-Za-z][A-Za-z0-9_'\- ]*?)\s+"
    r"(?P<r>[A-Z][A-Z_]{2,})\s+"
    r"(?P<o>[A-Za-z0-9][\w'\- ]+?)"
    r"(?=\s+[A-Za-z][A-Za-z0-9_'\- ]*?\s+[A-Z][A-Z_]{2,}\s+|$|\n)"
)

# flan-t5 sometimes joins multiple facts into one slug like
# "physicist_albert_einstein_birth_place_ulm". If the slug contains
# a recognizable relation keyword in the middle, split on it.
_MULTI_FACT_SPLITTERS = [
    "birth_place", "place_of_birth", "place_of_death",
    "occupation", "nationality", "citizenship", "residence",
    "located_in", "capital", "population", "language",
    "spouse", "child", "parent", "sibling",
    "founded_by", "founded_in", "author", "director",
    "member_of", "part_of", "subclass_of", "instance_of",
]


def _parse_output(
    text: str,
    source_span: str,
    extractor_name: str,
) -> List[ExtractedTriple]:
    """Parse a T5 response into ExtractedTriple records.

    Accepts two formats per line:
      1. "subject | relation | object"   (preferred, matches our prompt)
      2. "Subject RELATION_LABEL Object" (flan-t5's natural output)
    """
    out: List[ExtractedTriple] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        s = r = o = None

        if "|" in line:
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) >= 3:
                s = parts[0]
                r = parts[1]
                o = " | ".join(parts[2:])
        else:
            m = _UPPER_RELATION_RE.match(line)
            if m:
                s = m.group("s")
                r = m.group("r")
                o = m.group("o")

        if s is None or r is None or o is None:
            continue

        s_slug = _slug(s)
        r_slug = _slug(r)
        o_slug = _slug(o)
        if not (s_slug and r_slug and o_slug):
            continue
        if s_slug in _BAD_SUBJECT_SLUGS:
            continue

        out.append(ExtractedTriple(
            subject=s_slug,
            relation=r_slug,
            obj=o_slug,
            confidence=0.80,
            extractor=extractor_name,
            gate_agreement=False,
            source_span=source_span.strip(),
        ))
    return out


class T5FactSeparator:
    """T5-based (S, R, O) extractor.

    Lazily loads the model on first `extract()` so import cost stays low
    for callers that never reach Tier 2 (e.g., Wikidata-only ingests).

    Usage:
        ext = T5FactSeparator(model_name="google/flan-t5-base")
        triples = ext.extract("The capital of France is Paris.")
        # → [ExtractedTriple(subject='france', relation='capital', obj='paris', ...)]

    Batched:
        batch = ext.extract_batch([
            "The capital of France is Paris.",
            "Einstein was born in Ulm.",
            "Hezbollah warned the US about Iran.",
        ])
        # → List[List[ExtractedTriple]]
    """

    version = VERSION
    extractor_name = "t5_fact_separator"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: Optional[str] = None,
        max_input_tokens: int = 256,
        max_output_tokens: int = 128,
        num_beams: int = 4,
        batch_size: int = 16,
        cache_dir: Optional[str] = None,
    ):
        self.model_name = model_name
        self.device = _pick_device(device)
        self.max_input_tokens = int(max_input_tokens)
        self.max_output_tokens = int(max_output_tokens)
        self.num_beams = int(num_beams)
        self.batch_size = int(batch_size)
        self.cache_dir = cache_dir
        self._tokenizer = None
        self._model = None

    # ── lazy model load ─────────────────────────────────────
    def _ensure_loaded(self):
        if self._model is not None:
            return
        from transformers import AutoTokenizer, T5ForConditionalGeneration
        import torch
        print(f"[T5FactSeparator] Loading {self.model_name} on {self.device} ...",
              file=sys.stderr)
        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model_name, cache_dir=self.cache_dir)
        self._model = T5ForConditionalGeneration.from_pretrained(
            self.model_name, cache_dir=self.cache_dir)
        self._model.to(self.device)
        self._model.eval()
        print(f"[T5FactSeparator] Loaded. "
              f"params={sum(p.numel() for p in self._model.parameters()):,}",
              file=sys.stderr)

    # ── public API ──────────────────────────────────────────
    def extract(
        self,
        sentence: str,
        anchor_subject: Optional[str] = None,
    ) -> List[ExtractedTriple]:
        """Single-sentence extraction. Keeps interface compatible with
        RuleBasedFactSeparator so dual_gate() works unchanged."""
        results = self.extract_batch([sentence], [anchor_subject])
        return results[0] if results else []

    def extract_batch(
        self,
        sentences: List[str],
        anchor_subjects: Optional[List[Optional[str]]] = None,
    ) -> List[List[ExtractedTriple]]:
        """Batched extraction. Returns one list of triples per input."""
        self._ensure_loaded()
        if not sentences:
            return []

        import torch
        anchors = anchor_subjects or [None] * len(sentences)
        all_out: List[List[ExtractedTriple]] = []

        for bs in range(0, len(sentences), self.batch_size):
            be = min(bs + self.batch_size, len(sentences))
            batch_sents = sentences[bs:be]
            prompts = [_PROMPT_TEMPLATE.format(text=s) for s in batch_sents]
            enc = self._tokenizer(
                prompts,
                max_length=self.max_input_tokens,
                truncation=True,
                padding=True,
                return_tensors="pt",
            ).to(self.device)

            with torch.no_grad():
                out = self._model.generate(
                    **enc,
                    max_new_tokens=self.max_output_tokens,
                    num_beams=self.num_beams,
                    do_sample=False,
                    early_stopping=True,
                )
            decoded = self._tokenizer.batch_decode(
                out, skip_special_tokens=True)

            for sent, response in zip(batch_sents, decoded):
                tris = _parse_output(
                    response,
                    source_span=sent,
                    extractor_name=self.extractor_name,
                )
                all_out.append(tris)

        return all_out

    # ── introspection ───────────────────────────────────────
    def info(self) -> dict:
        return {
            "extractor": self.extractor_name,
            "version": self.version,
            "model": self.model_name,
            "device": self.device,
            "batch_size": self.batch_size,
            "num_beams": self.num_beams,
            "loaded": self._model is not None,
        }
