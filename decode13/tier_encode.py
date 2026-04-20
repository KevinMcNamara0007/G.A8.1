"""Tier-aware encoder — the v13 equivalent of encode/worker_encode.py.

Per-vector storage is flat numpy (O(12 bytes/vector) excluding the C++
index that owns the vectors). Prior versions kept a Python List of
EncodedVector dataclasses — at 21M records that balloons to tens of GB
before the C++ index even starts. Here the only Python objects retained
past build_index() are:

  - One TierEncoder instance
  - One ManifestRegistry13 instance whose `_manifests` list has a handful
    of interned TierManifest entries (typically 1-3 per corpus)
  - A small list of int-keyed numpy arrays indexed by vec_id

Bind/superpose/indexing flow is identical to worker_encode.py:

    tokens → codebook.encode_token(t)  [C++, LRU-cached]
           → ehc.superpose(vecs)       [C++]
           → BSCCompactIndex.add_items [C++, CSR-backed]
           → BSCLSHIndex.add_items     [C++, multiprobe]

After `build_index()` the Python-side sparse-vector references are
dropped — the C++ CSR index is the sole owner.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

# ── EHC import (same probe as encode/worker_encode.py) ──────
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
from .tier_manifest import (
    ManifestRegistry13,
    TierManifest,
    TIER_PIPELINE_VERSION,
    int_to_tier,
    tier_to_int,
)
from .tier_router import TierRouter
from .tier_types import ExtractedTriple, Tier, TierDecision


@dataclass
class VectorInfo:
    """Lightweight view onto a single encoded vector, materialized on
    demand from the flat arrays. Previously this was a concrete
    per-vector Python object held by the millions; now it's built only
    when code asks for a specific vec_id."""
    vec_id: int
    tier: Tier
    confidence: float
    gate_agreement: bool
    source_record_id: int
    tokens: Optional[List[str]] = None      # only kept when retain_triples
    triple: Optional[ExtractedTriple] = None  # only kept when retain_triples


class TierEncoder:
    """v13 encode entry point, flat-array backed.

    Constructor flags that govern memory:

      retain_triples  — if True, keep per-vector ExtractedTriple + tokens
                        in a Python list (useful for tests and small
                        benchmarks where the driver wants to inspect
                        extracted facts). Default True. Set False for
                        21M-scale runs to drop the triple/token refs.

    Thread-safety: not thread-safe. Partition upstream and run one
    encoder per worker (matches G.A8.1's existing worker model).
    """

    def __init__(
        self,
        dim: int = 4096,
        k: int = 64,
        seed: int = 42,
        tenant_domain: str = "default::default",
        gate_mode: str = "default",
        canonical: Optional[CanonicalizationPipeline] = None,
        retain_triples: bool = True,
        initial_capacity: int = 16384,
    ):
        self.dim = int(dim)
        self.k = int(k)
        self.seed = int(seed)
        self.tenant_domain = tenant_domain
        self.retain_triples = bool(retain_triples)

        self.canonical = canonical or CanonicalizationPipeline()
        self.router = TierRouter()
        self.tier1 = StructuredAtomicPipeline()
        self.tier2 = ExtractionPipeline(canonical=self.canonical, gate_mode=gate_mode)
        self.tier3 = EmergentStructureFallback(canonical=self.canonical)

        # Codebook — hash mode, deterministic.
        cfg = ehc.CodebookConfig()
        cfg.dim = self.dim
        cfg.k = self.k
        cfg.seed = self.seed
        self.codebook = ehc.TokenCodebook(cfg)
        self.codebook.build_from_vocabulary([])

        # Token cache — replicates worker_encode.py's hot-path cache.
        self.cache = ehc.LRUCache(max_size=50000) if hasattr(ehc, "LRUCache") else None

        # Registry owns the interning + per-vector manifest ids.
        decode_m = TierManifest.from_symmetry(
            self.canonical.manifest,
            tier=Tier.STRUCTURED_ATOMIC,
            tenant_domain=self.tenant_domain,
        )
        self.registry = ManifestRegistry13(decode_m)

        # Per-vector flat arrays (grown amortized ×2)
        self._capacity = int(initial_capacity)
        self._tier_id = np.zeros(self._capacity, dtype=np.int8)
        self._confidence = np.zeros(self._capacity, dtype=np.float32)
        self._gate = np.zeros(self._capacity, dtype=np.bool_)
        self._source_rid = np.full(self._capacity, -1, dtype=np.int32)
        self.n_vectors = 0

        # Optional per-vector introspection (flat lists, paired with
        # the numpy arrays above). None when retain_triples=False.
        if self.retain_triples:
            self._triples: Optional[List[Optional[ExtractedTriple]]] = []
            self._tokens: Optional[List[Optional[List[str]]]] = []
        else:
            self._triples = None
            self._tokens = None

        # Pending vectors waiting for build_index(). Dropped immediately
        # after add_items — C++ index takes ownership.
        self._pending_vecs: List = []
        self._pending_ids: List[int] = []

        self._index: Optional[object] = None
        self._lsh: Optional[object] = None

    # ── capacity management ──────────────────────────────────
    def _ensure_capacity(self, required: int) -> None:
        if required <= self._capacity:
            return
        new_cap = max(self._capacity * 2, required)
        self._tier_id = np.resize(self._tier_id, new_cap)
        self._confidence = np.resize(self._confidence, new_cap)
        self._gate = np.resize(self._gate, new_cap)
        self._source_rid = np.resize(self._source_rid, new_cap)
        self._capacity = new_cap

    # ── bind hot path (all C++) ──────────────────────────────
    def _encode_token(self, tok: str):
        if self.cache is not None:
            cached = self.cache.get(tok)
            if cached is not None:
                return cached
        try:
            tv = self.codebook.encode_token(tok)
        except Exception:
            return None
        if self.cache is not None and tv is not None:
            self.cache.put(tok, tv)
        return tv

    def _bind_tokens(self, tokens: List[str]):
        vecs = []
        for t in tokens:
            if not t:
                continue
            tv = self._encode_token(t)
            if tv is not None:
                vecs.append(tv)
        if not vecs:
            return None
        return ehc.superpose(vecs) if len(vecs) > 1 else vecs[0]

    # ── public API ───────────────────────────────────────────
    def encode_record(
        self,
        record_id: int,
        record: Dict,
        explicit_sro: Optional[bool] = None,
    ) -> int:
        """Encode a single record. Returns the count of vectors emitted
        (0, 1, or more for Tier 2 multi-triple records)."""
        tier = self.router.classify(
            subject=record.get("subject", "") or "",
            relation=record.get("relation", "") or "",
            obj=record.get("object", "") or "",
            text=record.get("text", "") or "",
            explicit_sro=explicit_sro,
        )

        if tier == Tier.STRUCTURED_ATOMIC:
            decision = self.tier1.emit(
                subject=record.get("subject", ""),
                relation=record.get("relation", ""),
                obj=record.get("object", ""),
                text=record.get("text", ""),
            )
        elif tier == Tier.EXTRACTED_TRIPLE:
            text = record.get("text", "") or record.get("object", "")
            decision = self.tier2.extract(text, anchor_subject=record.get("subject"))
        else:
            text = record.get("text", "") or record.get("object", "")
            decision = self.tier3.emit(text)

        return self._apply_decision(record_id, decision)

    def _apply_decision(self, record_id: int, decision: TierDecision) -> int:
        emitted = 0

        if decision.tier == Tier.STRUCTURED_ATOMIC:
            for tri in decision.triples:
                tokens = self.tier1.tokens_from_triple(tri)
                if self._emit_vector(
                    record_id=record_id,
                    tier=decision.tier,
                    tokens=tokens,
                    triple=tri,
                    confidence=tri.confidence,
                    gate_agreement=tri.gate_agreement,
                    extractor=tri.extractor,
                    ner_model="none",
                ):
                    emitted += 1

        elif decision.tier == Tier.EXTRACTED_TRIPLE:
            for tri in decision.triples:
                tokens = [tri.subject, tri.relation, tri.obj]
                if self._emit_vector(
                    record_id=record_id,
                    tier=decision.tier,
                    tokens=tokens,
                    triple=tri,
                    confidence=tri.confidence,
                    gate_agreement=tri.gate_agreement,
                    extractor=tri.extractor,
                    ner_model="heuristic-ner-v1",
                ):
                    emitted += 1

        else:  # EMERGENT_STRUCTURE
            tokens = decision.fallback_tokens
            if tokens:
                if self._emit_vector(
                    record_id=record_id,
                    tier=decision.tier,
                    tokens=tokens,
                    triple=None,
                    confidence=decision.confidence,
                    gate_agreement=False,
                    extractor="emergent_fallback",
                    ner_model="none",
                ):
                    emitted += 1

        return emitted

    def _emit_vector(
        self,
        record_id: int,
        tier: Tier,
        tokens: List[str],
        triple: Optional[ExtractedTriple],
        confidence: float,
        gate_agreement: bool,
        extractor: str,
        ner_model: str,
    ) -> bool:
        tokens = [t for t in tokens if t]
        if not tokens:
            return False
        sv = self._bind_tokens(tokens)
        if sv is None:
            return False

        vec_id = self.n_vectors
        self._ensure_capacity(vec_id + 1)

        # Write flat arrays.
        self._tier_id[vec_id] = tier_to_int(tier)
        self._confidence[vec_id] = float(confidence)
        self._gate[vec_id] = bool(gate_agreement)
        self._source_rid[vec_id] = int(record_id)

        # Intern the manifest + register under this vec_id.
        manifest = TierManifest.from_symmetry(
            self.canonical.manifest,
            tier=tier,
            extractor=extractor,
            ner_model=ner_model,
            extraction_confidence=round(float(confidence), 2),
            gate_agreement=gate_agreement,
            tenant_domain=self.tenant_domain,
        )
        self.registry.register(vec_id, manifest)

        # Pending for bulk add_items during build_index.
        self._pending_vecs.append(sv)
        self._pending_ids.append(vec_id)

        # Optional introspection retention.
        if self._triples is not None:
            self._triples.append(triple)
        if self._tokens is not None:
            self._tokens.append(list(tokens))

        self.n_vectors += 1
        return True

    # ── index build ──────────────────────────────────────────
    def build_index(
        self,
        lsh_tables: int = 8,
        lsh_hash_size: int = 16,
        use_lsh: bool = True,
    ) -> None:
        self._index = ehc.BSCCompactIndex(self.dim, use_sign_scoring=True)
        if self._pending_vecs:
            self._index.add_items(self._pending_vecs, self._pending_ids)

        if use_lsh and self._pending_vecs:
            self._lsh = ehc.BSCLSHIndex(
                self.dim, self.k,
                num_tables=lsh_tables, hash_size=lsh_hash_size,
                use_multiprobe=True,
            )
            self._lsh.add_items(self._pending_vecs, self._pending_ids)
        else:
            self._lsh = None

        # C++ index now owns the vectors. Drop Python refs so GC can
        # reclaim the wrappers — this is the big 21M memory win.
        self._pending_vecs = []
        self._pending_ids = []

        # Finalize registry + trim numpy slack.
        self.registry.finalize()
        if self._capacity > self.n_vectors:
            self._tier_id = self._tier_id[:self.n_vectors].copy()
            self._confidence = self._confidence[:self.n_vectors].copy()
            self._gate = self._gate[:self.n_vectors].copy()
            self._source_rid = self._source_rid[:self.n_vectors].copy()
            self._capacity = self.n_vectors

    # ── accessors for the decoder ────────────────────────────
    @property
    def index(self):
        return self._index

    @property
    def lsh(self):
        return self._lsh

    def vector_by_id(self, vec_id: int) -> Optional[VectorInfo]:
        if vec_id < 0 or vec_id >= self.n_vectors:
            return None
        tokens = (self._tokens[vec_id]
                  if self._tokens is not None and vec_id < len(self._tokens)
                  else None)
        triple = (self._triples[vec_id]
                  if self._triples is not None and vec_id < len(self._triples)
                  else None)
        return VectorInfo(
            vec_id=vec_id,
            tier=int_to_tier(int(self._tier_id[vec_id])),
            confidence=float(self._confidence[vec_id]),
            gate_agreement=bool(self._gate[vec_id]),
            source_record_id=int(self._source_rid[vec_id]),
            tokens=tokens,
            triple=triple,
        )

    # Compatibility shim so existing tests that iterate `enc.encoded`
    # keep working at small scale. Do not use on the 21M hot path.
    @property
    def encoded(self) -> List[VectorInfo]:
        return [self.vector_by_id(i) for i in range(self.n_vectors)]

    # Flat accessors for hot path — return numpy views, not copies.
    @property
    def tier_id_array(self) -> np.ndarray:
        return self._tier_id[:self.n_vectors]

    @property
    def source_record_id_array(self) -> np.ndarray:
        return self._source_rid[:self.n_vectors]

    @property
    def gate_array(self) -> np.ndarray:
        return self._gate[:self.n_vectors]

    @property
    def confidence_array(self) -> np.ndarray:
        return self._confidence[:self.n_vectors]

    def manifest_summary(self) -> Dict:
        return self.registry.summary()

    # ── persistence ─────────────────────────────────────────
    def save_manifest(self, path: Path) -> None:
        self.registry.save(Path(path))

    def stats(self) -> Dict:
        tier_counts = {t.value: 0 for t in Tier}
        if self.n_vectors > 0:
            tid = self._tier_id[:self.n_vectors]
            for t, i in [(Tier.STRUCTURED_ATOMIC, tier_to_int(Tier.STRUCTURED_ATOMIC)),
                         (Tier.EXTRACTED_TRIPLE, tier_to_int(Tier.EXTRACTED_TRIPLE)),
                         (Tier.EMERGENT_STRUCTURE, tier_to_int(Tier.EMERGENT_STRUCTURE))]:
                tier_counts[t.value] = int((tid == i).sum())
        gate_passes = int(self._gate[:self.n_vectors].sum()) if self.n_vectors > 0 else 0
        return {
            "n_vectors": int(self.n_vectors),
            "tier_counts": tier_counts,
            "gate_passes": gate_passes,
            "interned_manifests": len(self.registry.interned),
            "dim": self.dim,
            "k": self.k,
            "seed": self.seed,
            "pipeline": TIER_PIPELINE_VERSION,
            "retain_triples": self.retain_triples,
        }


# Legacy-compatibility alias for callers importing EncodedVector from
# earlier versions of this module.
EncodedVector = VectorInfo
