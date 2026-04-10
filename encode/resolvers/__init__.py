"""
G.A8.1 — Domain Resolvers

Thin normalization layer at the data ingestion boundary.
Runs before SRL, before encoding, before any part of A8.1.
Clean string in → clean string throughout.

One resolver per domain. All follow the same pattern:
    load_<domain>_labels(path) → dict[id → canonical_string]
    normalize_entity(entity, domain) → canonical_string
"""

RESOLVERS = {
    "wikidata": None,
    "genomics": None,
    "pubmed": None,
    "arxiv": None,
    "code": None,
    "logs": None,
}


def init_resolver(domain: str, path: str):
    """Load the appropriate resolver for a domain."""
    if domain == "genomics":
        from .genomics import load_hgnc_labels
        RESOLVERS[domain] = load_hgnc_labels(path)
    elif domain == "pubmed":
        from .pubmed import load_mesh_labels
        RESOLVERS[domain] = load_mesh_labels(path)
    elif domain == "wikidata":
        from .wikidata import load_kensho_labels
        RESOLVERS[domain] = load_kensho_labels(path)


def normalize_entity(entity: str, domain: str) -> str:
    """Normalize entity string for the given domain."""
    lookup = RESOLVERS.get(domain)
    if lookup is None:
        return entity.lower().replace(" ", "_")
    if domain == "genomics":
        from .genomics import normalize_gene_entity
        return normalize_gene_entity(entity, lookup) or entity
    elif domain == "pubmed":
        from .pubmed import normalize_medical_entity
        return normalize_medical_entity(entity, lookup) or entity
    # Wikidata: direct lookup
    key = entity.strip()
    return lookup.get(key, entity.lower().replace(" ", "_"))
