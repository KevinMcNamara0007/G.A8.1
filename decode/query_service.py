"""Back-compat shim: legacy import path for QueryService.

The real module moved to `query.py`. This file exists so callers that
do `from query_service import QueryService` continue to work for one
release cycle. New callers should import from `query` directly.

To migrate:
    OLD:  from query_service import QueryService
    NEW:  from query import QueryService
"""
from query import *  # noqa: F401, F403
from query import QueryService  # noqa: F401  — explicit re-export
