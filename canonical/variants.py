"""
G.A8.1 — VariantGenerator (decode-time query fan-out, §2.3 of the plan)

Starts with three axes only:
    - possession   (applied / stripped)
    - acronym      (expanded / compact)
    - stop-word    (always stripped — not fanned out)

Combined fan-out cap: 4 variants per query. Additional axes must earn
their slot via corpus-frequency analysis (plan §2.3 guidance).

The generator is decode-only. At encode time the pipeline emits one
canonical form per record; at decode time the VariantGenerator emits the
2^n canonical forms the query author might have intended.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .pipeline import CanonicalStream, CanonicalizationPipeline


@dataclass
class Variant:
    """One decode-time variant.

    `axes` records which axes were toggled "off" (i.e., kept in alternate
    form). `tokens` is what hits the encoder. `is_canonical` marks the
    primary variant — the one whose form matches encode-time canonical.
    """
    tokens: List[str]
    axes: frozenset = field(default_factory=frozenset)
    is_canonical: bool = False

    @property
    def label(self) -> str:
        if self.is_canonical:
            return "canonical"
        return "+".join(sorted(self.axes)) if self.axes else "canonical"


class VariantGenerator:
    """Generates fan-out variants along enabled axes.

    Cost: 2^(len(enabled_axes)) variants per query. With the default three
    axes (possession + acronym + stopword-stripped-always), cost is 4.
    """

    SUPPORTED_AXES = frozenset({"possessive", "acronym"})

    def __init__(self, pipeline: CanonicalizationPipeline,
                 enabled_axes: Optional[frozenset] = None):
        self.pipeline = pipeline
        if enabled_axes is None:
            enabled_axes = self.SUPPORTED_AXES
        unknown = enabled_axes - self.SUPPORTED_AXES
        if unknown:
            raise ValueError(f"Unsupported variant axes: {unknown}")
        self.enabled_axes = frozenset(enabled_axes)

    def generate(self, query_text: str) -> List[Variant]:
        """Return the variant set for `query_text`.

        Always includes the canonical form as `variants[0]`. Remaining
        variants toggle one or more axes off (i.e., inject the alternate
        surface form). The canonical form is the one the encoder produced
        on its side — so if the query already matches encoder geometry,
        the canonical variant lands in Hit@1 and the rest are redundant.
        """
        stream = self.pipeline.canonicalize_query(query_text)
        variants: List[Variant] = [Variant(
            tokens=list(stream.tokens),
            axes=frozenset(),
            is_canonical=True,
        )]

        # For each axis, if alternates were captured, emit a variant that
        # swaps the canonical token for the alternate form.
        axis_alternates = {
            "possessive": stream.variants.get("possessive", []),
            "acronym": stream.variants.get("acronym", []),
        }

        # Build an alt-form stream per axis by substituting the alternates
        # back in. Each alt is a single-axis toggle; combined toggles are
        # the Cartesian product.
        def tokens_with_axis(axis: str) -> Optional[List[str]]:
            alts = axis_alternates.get(axis) or []
            if not alts:
                return None
            if axis == "possessive":
                # Rebuild by re-running stage 2 (stop-word strip) and skipping
                # stage 3 — the alternates are the original surface forms.
                return self._regen_skip("possessive", query_text)
            if axis == "acronym":
                return self._regen_skip("acronym", query_text)
            return None

        axes_to_toggle = [a for a in ("possessive", "acronym")
                          if a in self.enabled_axes and axis_alternates.get(a)]

        # Single-axis toggles
        single_forms: List[tuple] = []
        for axis in axes_to_toggle:
            alt_tokens = tokens_with_axis(axis)
            if alt_tokens is None:
                continue
            variants.append(Variant(
                tokens=alt_tokens,
                axes=frozenset({axis}),
                is_canonical=False,
            ))
            single_forms.append((axis, alt_tokens))

        # Combined-axis toggle (only if both fire)
        if len(single_forms) == 2:
            combo_tokens = self._regen_skip_many(
                ("possessive", "acronym"), query_text,
            )
            if combo_tokens is not None:
                variants.append(Variant(
                    tokens=combo_tokens,
                    axes=frozenset({"possessive", "acronym"}),
                    is_canonical=False,
                ))

        return variants

    # ── internal: rebuild with selected stages disabled ─────
    def _regen_skip(self, skip_axis: str, query_text: str) -> List[str]:
        """Re-run canonicalization but skip `skip_axis` stage. Shares the
        pipeline's other stages so stop-word stripping and SRL are
        identical — only the toggled axis differs."""
        p = self.pipeline
        roles, _ = p.extract(text=query_text)
        stripped = {r: p._strip_stopwords(toks) for r, toks in roles.items()}
        out_tokens: List[str] = []
        seen: set = set()
        for role in ("s", "r", "o"):
            for tok in stripped[role]:
                if skip_axis == "possessive":
                    # keep original surface form
                    canon = tok
                else:
                    canon, _ = p._normalize_possessive(tok)
                if skip_axis == "acronym":
                    # keep acronym form, do not expand
                    final = [canon]
                else:
                    expanded_head, full = p._expand_acronym(canon)
                    final = full if full is not None else [canon]
                for f in final:
                    if f not in seen:
                        seen.add(f)
                        out_tokens.append(f)
        return out_tokens

    def _regen_skip_many(self, skip_axes, query_text: str) -> List[str]:
        skip = set(skip_axes)
        p = self.pipeline
        roles, _ = p.extract(text=query_text)
        stripped = {r: p._strip_stopwords(toks) for r, toks in roles.items()}
        out_tokens: List[str] = []
        seen: set = set()
        for role in ("s", "r", "o"):
            for tok in stripped[role]:
                canon = tok if "possessive" in skip else p._normalize_possessive(tok)[0]
                if "acronym" in skip:
                    final = [canon]
                else:
                    _, full = p._expand_acronym(canon)
                    final = full if full is not None else [canon]
                for f in final:
                    if f not in seen:
                        seen.add(f)
                        out_tokens.append(f)
        return out_tokens
