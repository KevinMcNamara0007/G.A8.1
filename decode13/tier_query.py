"""Tier-aware query service — the v13 equivalent of decode2/query_service.py.

All retrieval math is C++ (CSR-backed BSCCompactIndex, BSCLSHIndex,
sparse_cosine, superpose). Per-vector metadata lookups use the
encoder's flat numpy arrays + the registry's interned manifest list,
so the per-candidate Python overhead is a handful of array indexings.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

for _d in (2, 3, 4):
    _p = Path(__file__).resolve().parents[_d] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
import ehc  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from canonical.pipeline import CanonicalizationPipeline  # noqa: E402

from .emergent_pipeline import EmergentStructureFallback
from .extraction_pipeline import ExtractionPipeline
from .structured_pipeline import StructuredAtomicPipeline
from .tier_encode import TierEncoder, VectorInfo
from .tier_manifest import ManifestRegistry13, TierManifest, int_to_tier
from .tier_router import TierRouter
from .tier_types import ExtractedTriple, Tier, TierDecision


TIER_WEIGHT = {
    Tier.STRUCTURED_ATOMIC: 1.00,
    Tier.EXTRACTED_TRIPLE: 0.70,
    Tier.EMERGENT_STRUCTURE: 0.40,
}
GATE_BONUS = 0.20


@dataclass
class QueryHit:
    vec_id: int
    tier: Tier
    raw_score: float
    tier_weight: float
    ranking_score: float
    confidence: float
    gate_agreement: bool
    triple: Optional[ExtractedTriple]
    source_record_id: int
    matched_via: str = ""


@dataclass
class QueryTrace:
    query_tier: Tier
    decode_triples: List[ExtractedTriple] = field(default_factory=list)
    decode_tokens: List[str] = field(default_factory=list)
    axes_used: Set[str] = field(default_factory=set)
    per_subquery_hits: List[Dict] = field(default_factory=list)
    n_candidates: int = 0
    n_manifest_filtered: int = 0

    def as_dict(self) -> Dict:
        return {
            "query_tier": self.query_tier.value,
            "decode_triples": [
                {"s": t.subject, "r": t.relation, "o": t.obj,
                 "conf": t.confidence, "gate": t.gate_agreement}
                for t in self.decode_triples
            ],
            "decode_tokens": self.decode_tokens,
            "axes_used": sorted(self.axes_used),
            "per_subquery": self.per_subquery_hits,
            "n_candidates": self.n_candidates,
            "n_manifest_filtered": self.n_manifest_filtered,
        }


class QueryService13:
    """Tier-aware query service.

    Hot-path optimizations over the reference impl:

      - `precompute_compat(axes_used)` runs ONCE per subquery, producing
        a boolean np.ndarray sized = number of interned manifests
        (typically 1-10). Per-candidate compat is then a single array
        index — no dict lookups, no per-candidate dataclass creation.

      - Per-candidate tier/weight/score come from the encoder's flat
        numpy arrays + a small lookup table keyed by manifest-id.

      - QueryHit is still a dataclass (<50 items/query), but it's
        created only for candidates that pass the manifest filter.
    """

    def __init__(
        self,
        encoder: TierEncoder,
        gate_mode: str = "default",
    ):
        self.encoder = encoder
        self.dim = encoder.dim
        self.k = encoder.k
        self.codebook = encoder.codebook
        self.registry: ManifestRegistry13 = encoder.registry
        self.canonical = encoder.canonical

        self.router = TierRouter()
        self.tier1 = StructuredAtomicPipeline()
        self.tier2 = ExtractionPipeline(canonical=self.canonical, gate_mode=gate_mode)
        self.tier3 = EmergentStructureFallback(canonical=self.canonical)

        self.index = encoder.index
        self.lsh = encoder.lsh
        if self.index is None:
            raise RuntimeError("Encoder index not built; call build_index() first")

        # Pre-compute small per-manifest lookup tables (weights, tier,
        # gate). Sized to number of interned manifests (~1-10).
        self._rebuild_manifest_tables()

    def _rebuild_manifest_tables(self) -> None:
        manifests = self.registry.interned
        self._tier_per_mid = np.zeros(len(manifests), dtype=np.int8)
        self._weight_per_mid = np.zeros(len(manifests), dtype=np.float32)
        for i, m in enumerate(manifests):
            self._tier_per_mid[i] = 1 if m.tier == Tier.STRUCTURED_ATOMIC else \
                                     2 if m.tier == Tier.EXTRACTED_TRIPLE else 3
            w = TIER_WEIGHT.get(m.tier, 0.4)
            if m.tier == Tier.EXTRACTED_TRIPLE and m.gate_agreement:
                w = min(1.0, w + GATE_BONUS)
            self._weight_per_mid[i] = w

    # ── public API ───────────────────────────────────────────
    def query(
        self,
        text: str = "",
        subject: str = "",
        relation: str = "",
        obj: str = "",
        k: int = 10,
        fetch_k: Optional[int] = None,
        explicit_sro: Optional[bool] = None,
        tier_filter: Optional[Set[Tier]] = None,
    ) -> Dict:
        fetch_k = fetch_k or max(k * 5, 20)

        q_tier = self.router.classify(
            subject=subject, relation=relation, obj=obj, text=text,
            explicit_sro=explicit_sro,
        )
        trace = QueryTrace(query_tier=q_tier)

        subqueries: List[Tuple[str, List[str], Optional[Set[str]]]] = []

        if q_tier == Tier.STRUCTURED_ATOMIC:
            decision = self.tier1.emit_query(
                subject=subject, relation=relation, obj=obj, text=text)
            for i, tri in enumerate(decision.triples):
                toks = self.tier1.tokens_from_triple(tri)
                subqueries.append((f"tier1_direct[{i}]", toks, {"escape"}))
                trace.decode_triples.append(tri)

        elif q_tier == Tier.EXTRACTED_TRIPLE:
            decision = self.tier2.extract(text or obj, anchor_subject=subject or None)
            if decision.tier == Tier.EXTRACTED_TRIPLE and decision.triples:
                for i, tri in enumerate(decision.triples):
                    toks = [tri.subject, tri.relation, tri.obj]
                    subqueries.append((f"tier2_triple[{i}]", toks, {"escape"}))
                    trace.decode_triples.append(tri)
                fb = self.tier3.emit(text or obj)
                if fb.fallback_tokens:
                    subqueries.append(("tier2_fallback_bag",
                                       fb.fallback_tokens, {"escape"}))
                    trace.decode_tokens = fb.fallback_tokens
            else:
                decision = self.tier3.emit(text or obj)
                subqueries.append(("tier3_fallback",
                                   decision.fallback_tokens, {"escape"}))
                trace.decode_tokens = decision.fallback_tokens

        else:  # EMERGENT_STRUCTURE query
            decision = self.tier3.emit(text or obj)
            subqueries.append(("tier3_fallback",
                               decision.fallback_tokens, {"escape"}))
            trace.decode_tokens = decision.fallback_tokens

        for _, _, axes in subqueries:
            if axes:
                trace.axes_used.update(axes)

        merged: Dict[int, QueryHit] = {}
        for label, tokens, axes in subqueries:
            hits = self._run_subquery(
                tokens=tokens, fetch_k=fetch_k, axes_used=axes, label=label)
            trace.per_subquery_hits.append({
                "label": label,
                "n_tokens": len([t for t in tokens if t]),
                "n_hits": len(hits),
            })
            for h in hits:
                prev = merged.get(h.vec_id)
                if prev is None or h.ranking_score > prev.ranking_score:
                    merged[h.vec_id] = h

        if tier_filter is not None:
            merged = {vid: h for vid, h in merged.items() if h.tier in tier_filter}

        trace.n_candidates = len(merged)
        ordered = sorted(merged.values(),
                         key=lambda h: -h.ranking_score)[:k]
        return {
            "results": [self._hit_to_dict(h) for h in ordered],
            "trace": trace.as_dict(),
        }

    # ── hot-path sub-query ───────────────────────────────────
    def _run_subquery(
        self,
        tokens: List[str],
        fetch_k: int,
        axes_used: Optional[Set[str]],
        label: str,
    ) -> List[QueryHit]:
        tokens = [t for t in tokens if t]
        if not tokens:
            return []
        qvec = self._encode_tokens(tokens)
        if qvec is None:
            return []
        if self.lsh is not None:
            result = self.lsh.knn_query(qvec, k=fetch_k)
        else:
            result = self.index.knn_query(qvec, k=fetch_k)

        ids = np.asarray(result.ids, dtype=np.int64)
        scores = np.asarray(result.scores, dtype=np.float32)
        if ids.size == 0:
            return []

        # Compat filter — one array indexing per candidate, no dict probes.
        compat_per_mid = self.registry.precompute_compat(axes_used)
        mids_all = self.registry.manifest_ids_for(ids)
        mask = compat_per_mid[mids_all] if compat_per_mid.size else \
               np.zeros(ids.size, dtype=bool)
        if not mask.any():
            return []

        kept_ids = ids[mask]
        kept_scores = scores[mask]
        kept_mids = mids_all[mask]
        kept_tiers = self._tier_per_mid[kept_mids]
        kept_weights = self._weight_per_mid[kept_mids]
        kept_ranking = kept_scores * kept_weights

        # Encoder flat-array pulls for display fields.
        enc = self.encoder
        src = enc.source_record_id_array[kept_ids]
        gates = enc.gate_array[kept_ids]
        confs = enc.confidence_array[kept_ids]

        # Triple lookup is optional — only when retain_triples=True.
        triples_ref = enc._triples
        hits: List[QueryHit] = []
        for i in range(kept_ids.size):
            vid = int(kept_ids[i])
            tier = int_to_tier(int(kept_tiers[i]))
            triple = triples_ref[vid] if triples_ref is not None and vid < len(triples_ref) else None
            hits.append(QueryHit(
                vec_id=vid,
                tier=tier,
                raw_score=float(kept_scores[i]),
                tier_weight=float(kept_weights[i]),
                ranking_score=float(kept_ranking[i]),
                confidence=float(confs[i]),
                gate_agreement=bool(gates[i]),
                triple=triple,
                source_record_id=int(src[i]),
                matched_via=label,
            ))
        return hits

    def _encode_tokens(self, tokens: List[str]):
        vecs = []
        for t in tokens:
            try:
                vecs.append(self.codebook.encode_token(t))
            except Exception:
                continue
        if not vecs:
            return None
        return ehc.superpose(vecs) if len(vecs) > 1 else vecs[0]

    def _hit_to_dict(self, h: QueryHit) -> Dict:
        d = {
            "vec_id": h.vec_id,
            "tier": h.tier.value,
            "raw_score": round(h.raw_score, 4),
            "tier_weight": round(h.tier_weight, 3),
            "ranking_score": round(h.ranking_score, 4),
            "confidence": round(h.confidence, 3),
            "gate_agreement": h.gate_agreement,
            "source_record_id": h.source_record_id,
            "matched_via": h.matched_via,
        }
        if h.triple:
            d["triple"] = {
                "s": h.triple.subject,
                "r": h.triple.relation,
                "o": h.triple.obj,
            }
        return d
