"""G.A8.1 decode — predictable single-entry query API.

CANONICAL IMPORT (recommended for all new code):

    from decode import QueryService

    qs = QueryService("/path/to/encoded")
    qs.query(subject="france", relation="capital", k=10)
    qs.query(text="who built the bridge?", k=10)

`QueryService` auto-detects whether the encoded directory is flat
(single-machine, `structural_v13/` + `corpus.jsonl`) or sharded
(billions-scale, `shard_NNNN/` + `manifest.json`) and instantiates
the matching backend.

LEGACY IMPORT PATHS (still work, kept for back-compat):

    from decode.query import QueryService     # flat-only legacy class
    from decode13 import QueryServiceV13      # sharded-only direct access

These remain available so existing edge_service / RESTWRAPPER imports
don't break, but new code should prefer the unified entry point.

See `G.A8.1/how_to_use_decode.md` for the full encode-to-decode contract,
end-to-end use cases, and validated benchmark numbers.
"""
from decode.query_dispatch import QueryService

__all__ = ["QueryService"]
