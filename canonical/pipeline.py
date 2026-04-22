"""
G.A8.1 — CanonicalizationPipeline

Stateless normalizer applied identically on the encode and decode paths.
Same code, same configuration, same version — any drift between the two
paths is what the SymmetryManifest exists to detect.

Pipeline stages (§2.1 of the plan):
  1. Structural extraction       — SRL/NER pulls S, R, O (or partial)
  2. Stop-word removal           — applied to each role independently
  3. Possession normalization    — "user's" -> canonical "user"; variant kept
  4. Acronym expansion           — "ML" -> "machine learning"; variant kept
  5. Canonical emission          — canonical token stream + variant set

The decoder consumes the canonical stream; the encoder consumes the
canonical stream. The variant set is used only by the decode-side
VariantGenerator (see variants.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .manifest import SymmetryManifest


_RESOURCE_DIR = Path(__file__).resolve().parent / "resources"
_STOPWORDS_PATH = _RESOURCE_DIR / "stopwords_v1.txt"
_ACRONYMS_PATH = _RESOURCE_DIR / "acronyms_v1.tsv"
_POSSESSIVES_PATH = _RESOURCE_DIR / "possessive_v1.tsv"


def _load_stopwords(path: Path) -> frozenset:
    words = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            words.add(line.lower())
    return frozenset(words)


def _load_acronyms(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 2:
                continue
            out[parts[0].strip().lower()] = parts[1].strip().lower()
    return out


def _load_possessive_rules(path: Path) -> List[Tuple[str, re.Pattern, str]]:
    rules: List[Tuple[str, re.Pattern, str]] = []
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            rule_id, pattern, replacement = parts
            rules.append((rule_id, re.compile(pattern), replacement))
    return rules


# Word-character split — matches existing encode tokenizer semantics
# (split on whitespace after underscore -> space substitution, lowercase).
def _tokenize_role(text: str) -> List[str]:
    return [w for w in text.replace("_", " ").lower().split() if w]


@dataclass
class CanonicalStream:
    """Output of the canonicalization pipeline.

    - tokens: the canonical token stream, consumed by both encode and decode
    - variants: per-axis alternate surface forms (used only by decode-side
      VariantGenerator; encode-side pass ignores them)
    - roles: per-role token lists (S/R/O), for downstream routers that still
      care about the structural split (e.g., two-tier sharding)
    - manifest: SymmetryManifest recording which rules were applied
    - partial: set of role names actually extracted ("s", "r", "o") — the
      plan permits SR / RO / SO / S / O partials
    """
    tokens: List[str] = field(default_factory=list)
    variants: Dict[str, List[str]] = field(default_factory=dict)
    roles: Dict[str, List[str]] = field(default_factory=dict)
    manifest: Optional[SymmetryManifest] = None
    partial: frozenset = field(default_factory=frozenset)


class CanonicalizationPipeline:
    """Shared encode/decode canonicalizer.

    Construction loads versioned resource files; the resulting instance is
    stateless w.r.t. inputs and safe to share across threads / forks.
    """

    def __init__(
        self,
        stopwords_path: Path = _STOPWORDS_PATH,
        acronyms_path: Path = _ACRONYMS_PATH,
        possessives_path: Path = _POSSESSIVES_PATH,
        extraction_confidence: float = 1.0,
    ):
        self.stopwords = _load_stopwords(stopwords_path)
        self.acronyms = _load_acronyms(acronyms_path)
        self.possessive_rules = _load_possessive_rules(possessives_path)
        self._stopwords_path = stopwords_path
        self._acronyms_path = acronyms_path
        self._possessives_path = possessives_path
        self.manifest = SymmetryManifest.from_resources(
            stopword_path=stopwords_path,
            acronym_path=acronyms_path,
            extraction_confidence=extraction_confidence,
        )

    # ── stage 1: structural extraction ──────────────────────
    def extract(
        self,
        subject: str = "",
        relation: str = "",
        obj: str = "",
        text: str = "",
    ) -> Tuple[Dict[str, List[str]], frozenset]:
        """Return (roles, partial). `text` is a fallback free-text field
        that gets dumped into the object role when no explicit SRO was
        supplied — matching the current v12.5 behavior for JSONL messages."""
        roles: Dict[str, List[str]] = {"s": [], "r": [], "o": []}
        partial: set = set()
        if subject:
            roles["s"] = _tokenize_role(subject)
            if roles["s"]:
                partial.add("s")
        if relation:
            roles["r"] = _tokenize_role(relation)
            if roles["r"]:
                partial.add("r")
        if obj:
            roles["o"] = _tokenize_role(obj)
            if roles["o"]:
                partial.add("o")
        elif text:
            roles["o"] = _tokenize_role(text)
            if roles["o"]:
                partial.add("o")
        return roles, frozenset(partial)

    # ── stage 2: stop-word removal (per role) ───────────────
    def _strip_stopwords(self, tokens: Iterable[str]) -> List[str]:
        return [t for t in tokens if t not in self.stopwords and len(t) > 1]

    # ── stage 3: possession normalization ───────────────────
    def _normalize_possessive(self, token: str) -> Tuple[str, Optional[str]]:
        """Return (canonical, alt). alt is the other surface form if this
        rule fired, else None. "user's" -> ("user", "user's")."""
        for _rid, pattern, repl in self.possessive_rules:
            m = pattern.match(token)
            if m:
                canonical = pattern.sub(repl, token)
                if canonical != token:
                    return canonical, token
        return token, None

    # ── stage 4: acronym expansion ──────────────────────────
    def _expand_acronym(self, token: str) -> Tuple[str, Optional[List[str]]]:
        """If `token` is a known acronym, return (expansion_first_word, full_expansion_tokens).
        The canonical form picks the expansion (e.g. "machine learning"), and
        the original acronym is retained as a variant. Caller flattens the
        expansion into the canonical stream.
        """
        exp = self.acronyms.get(token)
        if exp is None:
            return token, None
        expansion_tokens = exp.split()
        return expansion_tokens[0], expansion_tokens

    # ── stage 5: canonical emission ─────────────────────────
    def canonicalize(
        self,
        subject: str = "",
        relation: str = "",
        obj: str = "",
        text: str = "",
    ) -> CanonicalStream:
        roles_raw, partial = self.extract(subject, relation, obj, text)

        # stage 2: stop-word strip per role
        roles_stripped = {r: self._strip_stopwords(toks)
                          for r, toks in roles_raw.items()}

        # stage 3+4: possession + acronym normalization, collecting variants
        canonical_roles: Dict[str, List[str]] = {"s": [], "r": [], "o": []}
        possessive_variants: List[str] = []
        acronym_variants: List[str] = []

        for role, toks in roles_stripped.items():
            out: List[str] = []
            for tok in toks:
                # possession
                canon, alt = self._normalize_possessive(tok)
                if alt is not None:
                    possessive_variants.append(alt)
                # acronym expansion (after possession to catch "ML's" -> "ml" -> "machine")
                expanded_head, full = self._expand_acronym(canon)
                if full is not None:
                    out.extend(full)
                    acronym_variants.append(canon)  # retain the acronym form
                else:
                    out.append(canon)
            canonical_roles[role] = out

        # stage 5: flat canonical stream (dedup-preserving order)
        seen: set = set()
        tokens: List[str] = []
        for role in ("s", "r", "o"):
            for tok in canonical_roles[role]:
                if tok not in seen:
                    seen.add(tok)
                    tokens.append(tok)

        variants = {
            "possessive": possessive_variants,
            "acronym": acronym_variants,
        }

        return CanonicalStream(
            tokens=tokens,
            variants=variants,
            roles=canonical_roles,
            manifest=self.manifest,
            partial=partial,
        )

    # ── Convenience: canonicalize a plain query string ──────
    def canonicalize_query(self, text: str) -> CanonicalStream:
        """Decode-side entry point. No explicit SRO — text goes into `o`
        (matches how v12.5 decode tokenizes queries today)."""
        return self.canonicalize(text=text)
