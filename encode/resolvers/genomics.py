"""
HGNC Gene Symbol Resolver

Maps gene identifiers to canonical HGNC approved symbols.

Handles:
  - Approved symbols:  BRCA1, TP53           → unchanged
  - Previous symbols:  BRCC1 → BRCA1         (renamed)
  - Aliases:           FANCS → BRCA1         (common alias)
  - Ensembl IDs:       ENSG00000012048       → BRCA1
  - Entrez IDs:        672                   → BRCA1
  - Case variants:     brca1, Brca1          → brca1
"""

import csv
import re
from pathlib import Path
from typing import Optional


def load_hgnc_labels(hgnc_path: str) -> dict:
    """Load HGNC complete set into canonical symbol lookup.

    Returns dict mapping any recognized identifier → canonical symbol.
    All symbols lowercase_underscored.
    """
    hgnc_path = Path(hgnc_path)
    if not hgnc_path.exists():
        raise FileNotFoundError(f"HGNC file not found: {hgnc_path}")

    labels = {}
    aliases = {}

    print(f"  Loading HGNC gene symbols from {hgnc_path}...")

    with open(hgnc_path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            hgnc_id = row.get("hgnc_id", "").strip()
            symbol = row.get("symbol", "").strip()
            status = row.get("status", "").strip()
            prev_syms = row.get("prev_symbol", "").strip()
            alias_syms = row.get("alias_symbol", "").strip()
            ensembl = row.get("ensembl_gene_id", "").strip()
            entrez = row.get("entrez_id", "").strip()

            if not symbol or status != "Approved":
                continue

            canonical = symbol.lower().replace("-", "_")
            labels[hgnc_id] = canonical

            for variant in [symbol, hgnc_id]:
                if variant:
                    aliases[variant.lower().replace("-", "_")] = canonical

            for prev in prev_syms.split("|"):
                prev = prev.strip().lower().replace("-", "_")
                if prev:
                    aliases[prev] = canonical

            for alias in alias_syms.split("|"):
                alias = alias.strip().lower().replace("-", "_")
                if alias:
                    aliases[alias] = canonical

            if ensembl:
                aliases[ensembl.lower()] = canonical
            if entrez:
                aliases[f"entrez_{entrez}"] = canonical

    full_lookup = {**labels, **aliases}
    print(f"    {len(labels):,} approved gene symbols")
    print(f"    {len(full_lookup):,} total mappings")
    return full_lookup


def normalize_gene_entity(entity: str, hgnc_lookup: dict) -> Optional[str]:
    """Normalize a gene entity to HGNC canonical form."""
    if not entity:
        return None

    key = entity.strip().lower().replace(" ", "_").replace("-", "_")

    if key in hgnc_lookup:
        return hgnc_lookup[key]

    # Strip common suffixes
    base = re.sub(r'_human$|_mouse$|_protein$|_gene$', '', key)
    if base in hgnc_lookup:
        return hgnc_lookup[base]

    return entity.lower().replace(" ", "_")
