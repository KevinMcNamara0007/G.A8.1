"""Auto-detecting QueryService dispatcher.

The canonical import for new G.A8.1 callers:

    from decode import QueryService
    qs = QueryService("/path/to/encoded")
    qs.query(subject="france", relation="capital", k=10)

Inspects the encoded directory at construction time and instantiates
the matching backend:

  - ensemble layout (ensemble.json + structural_v13_seedN/) → decode.query_ensemble.EnsembleQueryService
                                                              (N codebook-seeded flat
                                                              backends, query fan-out
                                                              + result fusion)
  - flat layout    (structural_v13/ + corpus.jsonl)   → decode.query.QueryService
                                                         (legacy edge-shim wrapping
                                                         a single ehc.StructuralPipelineV13)
  - sharded layout (shard_NNNN/ + manifest.json)      → decode13.QueryServiceV13
                                                         (multi-shard, tier-routed,
                                                         deterministic-route capable)

Why this exists: the two backends serve genuinely different on-disk
shapes (single-machine flat encode vs two-tier sharded encode) and
the v13 implementation lives in `decode13/` for historical reasons.
This dispatcher gives developers, AI agents, and architects ONE
predictable import path so they don't have to know which encoder
produced the directory before they can query it.

See `G.A8.1/how_to_use_decode.md` for the full mapping between
encode CLIs and decode layouts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


class QueryService:
    """Layout-agnostic query interface for G.A8.1 encoded corpora.

    Public API (works on all three backends):
        qs = QueryService(path, dim=None, k=None, fusion=None)
        qs.query(text="", subject="", relation="", obj="", k=10, **kwargs)
        qs.stats   → dict
        qs.layout  → "flat", "sharded", or "ensemble"
        qs.backend → underlying backend object for layout-specific features
        qs.close()

    Ensemble-only kwargs:
        fusion — "merge_top10" (default), "max_top1", or "sum_sim".
                 Resolution order on the ensemble backend:
                 kwarg > A81_ENSEMBLE_FUSION env > ensemble.json default.
    """

    def __init__(
        self,
        path: str,
        dim: Optional[int] = None,
        k: Optional[int] = None,
        **kwargs,
    ):
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"path does not exist: {path}")

        has_ensemble = (p / "ensemble.json").exists()
        has_shards = any(p.glob("shard_*"))
        has_flat = (p / "structural_v13").exists()

        if has_ensemble:
            # Ensemble layout (encode_unstructured --ensemble-seeds output).
            from decode.query_ensemble import EnsembleQueryService
            self._backend = EnsembleQueryService(
                str(p), fusion=kwargs.pop("fusion", None))
            self.layout = "ensemble"
        elif has_shards:
            # Sharded layout (encode.py output).
            from decode13 import QueryServiceV13
            self._backend = QueryServiceV13(str(p), dim=dim, k=k)
            self.layout = "sharded"
        elif has_flat:
            # Flat layout (encode_triples.py / encode_unstructured.py output).
            # The legacy class lives at decode.query.QueryService and takes a
            # different constructor signature (a81_path, product_dir, context).
            from decode.query import QueryService as _FlatQS
            self._backend = _FlatQS(
                a81_path=str(p),
                product_dir=kwargs.pop("product_dir", None),
                context=kwargs.pop("context", None),
                hebbian_topk=kwargs.pop("hebbian_topk", 3),
            )
            self.layout = "flat"
        else:
            raise ValueError(
                f"{path} is not a recognized G.A8.1 encoded directory.\n"
                f"  Expected one of:\n"
                f"    ensemble layout — contains ensemble.json + structural_v13_seedN/ dirs\n"
                f"                      (built by `encode_unstructured --ensemble-seeds N,M,...`)\n"
                f"    sharded layout  — contains shard_NNNN/ subfolders + manifest.json\n"
                f"                      (built by `python -m encode.encode`)\n"
                f"    flat layout     — contains structural_v13/ + corpus.jsonl\n"
                f"                      (built by `python -m encode.encode_triples`\n"
                f"                       or `python -m encode.encode_unstructured`)"
            )

    def query(
        self,
        text: str = "",
        subject: str = "",
        relation: str = "",
        obj: str = "",
        k: int = 10,
        **kwargs,
    ) -> Dict[str, Any]:
        """Run a query.

        Both backends accept ``text`` for free-text queries.
        Sharded backend additionally accepts ``subject`` / ``relation``
        / ``obj`` (Tier-1 SRO) plus routing options
        (``n_shards``, ``fetch_k``, ``route_mode``).

        For the flat backend, if ``subject`` and ``relation`` are
        supplied without ``text``, they're concatenated to form the
        query text — this preserves the SRO contract on the flat path.
        """
        if self.layout == "sharded":
            return self._backend.query(
                text=text, subject=subject, relation=relation, obj=obj,
                k=k, **kwargs)
        # Flat backend: synthesize SRO text if needed.
        if (subject or relation) and not text:
            text = f"{subject} {relation}".strip()
        return self._backend.query(text=text, k=k, **kwargs)

    @property
    def stats(self) -> Dict[str, Any]:
        if hasattr(self._backend, "stats"):
            base = dict(self._backend.stats) if isinstance(
                self._backend.stats, dict) else {}
        else:
            base = {
                "shards": len(getattr(self._backend, "shards", {})),
                "dim": getattr(self._backend, "dim", None),
                "k": getattr(self._backend, "k", None),
            }
        base["layout"] = self.layout
        return base

    @property
    def backend(self):
        """The underlying backend object. Use only when you need a feature
        that isn't exposed through the unified API (e.g. ``route_mode``
        flags on the sharded backend, or ``query_images`` on the flat
        backend)."""
        return self._backend

    def close(self):
        if hasattr(self._backend, "close"):
            self._backend.close()
