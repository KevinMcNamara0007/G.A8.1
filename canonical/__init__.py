"""
G.A8.1 — Canonicalization Layer (Closed-Loop Encode/Decode Pairing)

Implements the architecture from Closed_Loop_Encode_Decode_Plan.docx:
encode and decode operate on the same canonical token stream, produced by
the same normalization pipeline, versioned by the same manifest.

Public surface:
    from canonical import (
        CanonicalizationPipeline,   # shared encode+decode normalizer
        CanonicalStream,            # output of pipeline.canonicalize()
        SymmetryManifest,           # versioned record of rules applied
        ManifestVersionRegistry,    # encode/decode compatibility check
        VariantGenerator,           # decode-time query fan-out
        QueryInstrumentation,       # per-query convergence telemetry
    )

Encode and decode MUST import the pipeline from this module — not duplicate
it — or the symmetry contract is silently broken.
"""

from .pipeline import CanonicalizationPipeline, CanonicalStream
from .manifest import SymmetryManifest, ManifestVersionRegistry, PIPELINE_VERSION
from .variants import VariantGenerator, Variant
from .instrumentation import QueryInstrumentation, QueryTrace

__all__ = [
    "CanonicalizationPipeline",
    "CanonicalStream",
    "SymmetryManifest",
    "ManifestVersionRegistry",
    "PIPELINE_VERSION",
    "VariantGenerator",
    "Variant",
    "QueryInstrumentation",
    "QueryTrace",
]
