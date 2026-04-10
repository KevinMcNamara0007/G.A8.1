"""
MeSH Term Resolver for PubMed / Biomedical Text

Maps medical concepts to canonical MeSH preferred terms.

Handles:
  - Preferred terms:   "Neoplasms"           → "neoplasms"
  - Entry terms:       "Tumors" → "neoplasms" (synonym)
  - Common variants:   "cancer", "tumor"      → "neoplasms"
  - Abbreviations:     "MI" → "myocardial_infarction"
"""

import re
import gzip
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional


def load_mesh_labels(mesh_xml_path: str) -> dict:
    """Load MeSH descriptor XML into canonical term lookup.

    Returns dict mapping any recognized surface form → MeSH preferred term.
    All terms lowercase_underscored.
    """
    mesh_path = Path(mesh_xml_path)
    if not mesh_path.exists():
        raise FileNotFoundError(f"MeSH file not found: {mesh_path}")

    print(f"  Loading MeSH terms from {mesh_path}...")

    lookup = {}
    n_descriptors = 0

    opener = gzip.open if str(mesh_path).endswith(".gz") else open
    with opener(str(mesh_path), "rb") as f:
        tree = ET.parse(f)

    root = tree.getroot()

    for descriptor in root.findall(".//DescriptorRecord"):
        name_elem = descriptor.find("DescriptorName/String")
        if name_elem is None or not name_elem.text:
            continue

        preferred = name_elem.text.strip().lower().replace(" ", "_")\
                                              .replace(",", "")
        preferred = re.sub(r'[^\w_]', '', preferred)

        lookup[preferred] = preferred
        n_descriptors += 1

        for concept in descriptor.findall(".//Concept"):
            for term in concept.findall(".//Term/String"):
                if term.text:
                    variant = term.text.strip().lower()\
                                  .replace(" ", "_")\
                                  .replace(",", "")
                    variant = re.sub(r'[^\w_]', '', variant)
                    if variant and variant != preferred:
                        lookup[variant] = preferred

    print(f"    {n_descriptors:,} MeSH descriptors")
    print(f"    {len(lookup):,} total mappings")
    return lookup


def normalize_medical_entity(entity: str,
                              mesh_lookup: dict) -> Optional[str]:
    """Normalize a medical entity to MeSH preferred term."""
    if not entity:
        return None

    key = entity.strip().lower().replace(" ", "_")\
                .replace(",", "").replace("-", "_")
    key = re.sub(r'[^\w_]', '', key)

    if key in mesh_lookup:
        return mesh_lookup[key]

    if key.endswith("s") and key[:-1] in mesh_lookup:
        return mesh_lookup[key[:-1]]

    return key if key else None
