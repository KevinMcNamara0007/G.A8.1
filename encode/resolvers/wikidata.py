"""
Wikidata Label Resolver — Fixes Kensho label artifacts.

Primary:   Kensho item.csv (QID → en_label)
Secondary: Wikipedia titles (fallback for bad labels)

Bad label patterns:
  Q317521 → "elon_musk's_submarine"  → "elon_musk"
  Q142    → "iso_3166-1:fr"          → "france"
  Q12345  → "thing (disambiguation)" → "thing"
"""

import csv
import json
import re
import time
from pathlib import Path

# Patterns that indicate a bad Kensho label
_BAD_LABEL_PATTERNS = [
    re.compile(r"'s_\w+$"),           # possessive compounds
    re.compile(r"^iso_\d{3,}"),       # ISO codes
    re.compile(r"^q\d+$", re.I),      # raw QIDs
    re.compile(r"[:/]\w{2,}$"),       # path/code suffixes
]


def _is_bad_label(label: str) -> bool:
    return any(p.search(label) for p in _BAD_LABEL_PATTERNS)


def _clean_label(label: str) -> str:
    """Basic cleaning applied to all labels."""
    # Remove parenthetical disambiguators: "Paris (city)" → "paris"
    label = re.sub(r'\s*\(.*?\)\s*$', '', label)
    # Collapse whitespace and underscores
    label = re.sub(r'[\s_]+', '_', label.strip()).strip('_')
    return label.lower() if label else ""


def load_kensho_labels(csv_path: str,
                       wikipedia_titles_path: str = None) -> dict:
    """Load QID → canonical English label.

    Primary: Kensho item.csv
    Secondary: Wikipedia titles (fallback for bad labels)
    """
    # Load Wikipedia titles if available
    wiki_titles = {}
    if wikipedia_titles_path and Path(wikipedia_titles_path).exists():
        with open(wikipedia_titles_path) as f:
            wiki_titles = json.load(f)
        print(f"    Wikipedia titles loaded: {len(wiki_titles):,}")

    print(f"  Loading Kensho labels from {csv_path}...")
    t0 = time.perf_counter()
    labels = {}
    bad_count = 0
    wiki_fallback_count = 0

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            qid = f"Q{row['item_id']}"
            raw_label = row.get("en_label", "").strip()
            if not raw_label:
                continue

            label = _clean_label(raw_label)

            if _is_bad_label(label):
                bad_count += 1
                if qid in wiki_titles:
                    label = _clean_label(wiki_titles[qid])
                    wiki_fallback_count += 1
                else:
                    # Strip bad parts: "elon_musk's_submarine" → "elon_musk"
                    label = re.sub(r"'s_\w+$", "", label)
                    label = re.sub(r"^iso_[\d\-:]+", "", label).strip("_")
                    if not label:
                        continue

            if label:
                labels[qid] = label

    elapsed = time.perf_counter() - t0
    print(f"    {len(labels):,} labels loaded in {elapsed:.1f}s")
    print(f"    {bad_count:,} bad labels detected")
    print(f"    {wiki_fallback_count:,} resolved via Wikipedia titles")
    return labels
