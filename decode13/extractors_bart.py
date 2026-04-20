"""BART-based (REBEL) triple extractor — PlanB §6.1 encode-side role.

Uses `Babelscape/rebel-large`, a BART-large model fine-tuned on the
REBEL dataset (220K Wikipedia-OpenIE sentence+triples pairs). Purpose-
built for subject/relation/object extraction. Output is a constrained
sequence of special tokens that parses deterministically — no prompt
engineering, no regex gymnastics.

Why BART here instead of T5:
  - REBEL is BART-based because BART's denoising pretraining transfers
    well to structured sequence generation.
  - At 400M params it's smaller + faster than flan-t5-large (780M).
  - Purpose-built for OpenIE: no zero-shot prompting needed.
  - Special-token output (`<triplet>`, `<subj>`, `<obj>`) parses
    unambiguously into (S, R, O).

Design:
  - Lazy model load.
  - MPS / CUDA / CPU auto-select.
  - Batched inference, greedy default (num_beams=1).
  - Decoder parse follows the REBEL paper + Babelscape reference impl.
  - Emits ExtractedTriple records with source_span + tolerant slugging,
    compatible with the existing dual-extractor gate.
"""

from __future__ import annotations

import os
import re
import sys
from typing import List, Optional, Tuple

from .tier_types import ExtractedTriple


VERSION = "bart-rebel-large-v1"
DEFAULT_MODEL = "Babelscape/rebel-large"

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# transformers.generation on MPS hits an unsupported op during beam
# search init; allow CPU fallback so inference completes.
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


# ─── slugging shared with the T5 extractor ───────────────
def _slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^\w'-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


_BAD_SUBJECT_SLUGS = frozenset({
    "this", "that", "it", "they", "there", "also", "however",
    "but", "and", "who", "what", "where", "when", "why", "how",
})


# ─── REBEL output parser ─────────────────────────────────
# Official parsing logic adapted from Babelscape/rebel readme:
#   https://huggingface.co/Babelscape/rebel-large
#
# Output structure, produced by the decoder:
#
#   <triplet> subject_1 <subj> object_1 <obj> relation_1 <triplet> ...
#
# Where each <triplet> delimiter introduces a new triple. Everything
# between <triplet> and <subj> is the subject; between <subj> and <obj>
# is the object; and between <obj> and the next <triplet> (or EOS) is
# the relation.

def _extract_triplets_from_text(
    decoded: str,
    source_span: str,
    extractor_name: str,
) -> List[ExtractedTriple]:
    """Parse one decoder output string into ExtractedTriple records."""
    triples: List[ExtractedTriple] = []
    subject = relation = object_ = ""
    text = (decoded
            .replace("<s>", "")
            .replace("</s>", "")
            .replace("<pad>", ""))
    current = ""
    state = "x"  # 'x' = before any triplet, 's' = in subject, 'o' = in object, 'r' = in relation

    for token in text.split():
        if token == "<triplet>":
            current = "t"  # collecting subject next
            if subject and relation and object_:
                triples.append(_build_triple(
                    subject, relation, object_, source_span, extractor_name))
            subject = relation = object_ = ""
            continue
        if token == "<subj>":
            current = "s"  # collecting object next (REBEL labels flipped)
            if relation:
                triples.append(_build_triple(
                    subject, relation, object_, source_span, extractor_name))
            object_ = ""
            continue
        if token == "<obj>":
            current = "o"  # collecting relation next
            continue

        if current == "t":
            subject += " " + token
        elif current == "s":
            object_ += " " + token
        elif current == "o":
            relation += " " + token

    if subject and relation and object_:
        triples.append(_build_triple(
            subject, relation, object_, source_span, extractor_name))

    return [t for t in triples if t is not None]


def _build_triple(
    subject: str,
    relation: str,
    object_: str,
    source_span: str,
    extractor_name: str,
) -> Optional[ExtractedTriple]:
    s = _slug(subject)
    r = _slug(relation)
    o = _slug(object_)
    if not (s and r and o):
        return None
    if s in _BAD_SUBJECT_SLUGS:
        return None
    return ExtractedTriple(
        subject=s,
        relation=r,
        obj=o,
        confidence=0.85,
        extractor=extractor_name,
        gate_agreement=False,
        source_span=source_span.strip(),
    )


# ─── main extractor ─────────────────────────────────────
class REBELFactSeparator:
    """BART-based OpenIE triple extractor using Babelscape/rebel-large.

    Interface mirrors RuleBasedFactSeparator and T5FactSeparator so the
    dual-extractor gate and the ExtractionPipeline don't need to know
    which backend is live.
    """

    version = VERSION
    extractor_name = "rebel_fact_separator"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: Optional[str] = None,
        max_input_tokens: int = 256,
        max_output_tokens: int = 200,
        num_beams: int = 3,
        num_return_sequences: int = 1,
        batch_size: int = 8,
        cache_dir: Optional[str] = None,
    ):
        self.model_name = model_name
        self.device = _pick_device(device)
        self.max_input_tokens = int(max_input_tokens)
        self.max_output_tokens = int(max_output_tokens)
        self.num_beams = int(num_beams)
        self.num_return_sequences = int(num_return_sequences)
        self.batch_size = int(batch_size)
        self.cache_dir = cache_dir
        self._tokenizer = None
        self._model = None

    # ── lazy load ───────────────────────────────────────
    def _ensure_loaded(self):
        if self._model is not None:
            return
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
        print(f"[REBELFactSeparator] Loading {self.model_name} on {self.device} ...",
              file=sys.stderr)
        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model_name, cache_dir=self.cache_dir)
        self._model = AutoModelForSeq2SeqLM.from_pretrained(
            self.model_name, cache_dir=self.cache_dir)
        self._model.to(self.device)
        self._model.eval()
        n = sum(p.numel() for p in self._model.parameters())
        print(f"[REBELFactSeparator] Loaded. params={n:,}", file=sys.stderr)

    # ── public API ──────────────────────────────────────
    def extract(
        self,
        sentence: str,
        anchor_subject: Optional[str] = None,
    ) -> List[ExtractedTriple]:
        """Single-sentence extraction. Matches the rule-based interface
        so dual_gate() works unchanged."""
        results = self.extract_batch([sentence])
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
        all_out: List[List[ExtractedTriple]] = []

        for bs in range(0, len(sentences), self.batch_size):
            be = min(bs + self.batch_size, len(sentences))
            batch = sentences[bs:be]
            enc = self._tokenizer(
                batch,
                max_length=self.max_input_tokens,
                truncation=True,
                padding=True,
                return_tensors="pt",
            ).to(self.device)
            gen_kwargs = {
                "max_new_tokens": self.max_output_tokens,
                "num_beams": self.num_beams,
                "num_return_sequences": self.num_return_sequences,
                "length_penalty": 0.0,
            }
            with torch.no_grad():
                out = self._model.generate(**enc, **gen_kwargs)
            decoded = self._tokenizer.batch_decode(
                out,
                skip_special_tokens=False,  # keep <triplet>, <subj>, <obj>
                clean_up_tokenization_spaces=False,
            )

            # If num_return_sequences > 1, flatten groups back per-input.
            per_input = self.num_return_sequences
            for i, src in enumerate(batch):
                collect: List[ExtractedTriple] = []
                for j in range(per_input):
                    idx = i * per_input + j
                    collect.extend(_extract_triplets_from_text(
                        decoded[idx], source_span=src,
                        extractor_name=self.extractor_name,
                    ))
                # dedupe within this input
                seen = set()
                unique: List[ExtractedTriple] = []
                for t in collect:
                    key = (t.subject, t.relation, t.obj)
                    if key in seen:
                        continue
                    seen.add(key)
                    unique.append(t)
                all_out.append(unique)
        return all_out

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
