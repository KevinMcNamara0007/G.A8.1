"""Edge-compat shim package.

Historically `G.A8.1/decode/` held the production query service that
frontends (edge_service, etc.) imported via `from query_service import
QueryService`. The decoder implementation has since moved to
`G.A8.1/decode13/` and the Python-orchestrated path was retired.

This package exists so existing frontends can keep the import shape
`from query_service import QueryService` (resolved by
`sys.path.insert(0, G.A8.1/decode)`) while the underlying engine is the
new `ehc.StructuralPipelineV13` loaded from disk. Adding new code here is
not recommended — put it in `decode13/`.
"""
