"""Product hooks for the hydraulic fault-diagnosis corpus.

Plugs into G.A8.1's hook architecture (README §"Hook Architecture"):
edge_service calls `load_hooks(product_dir=...)` and picks up `get_hooks()`
from this file. Today we customize `query_cleaner` only — domain reranker
is left as default; that work is tracked separately.

Standalone use (no hooks module on PYTHONPATH) is also supported: import
`rewrite` directly. The probe scripts use that path so this file works
in dev environments without the edge_service installed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple, Any


# ─── Domain dictionary ────────────────────────────────────────────────
CODE_CATALOG = {
    'HYD_COOL_FAIL':      {'aliases': ['cooler','cooling','coolant','heat','exchanger','thermal','radiator'],
                           'severity':['fail','failure','dead','broken','critical','total']},
    'HYD_COOL_DEGRADED':  {'aliases': ['cooler','cooling','coolant'],
                           'severity':['degraded','reduced','poor','weak','low','partial']},
    'HYD_VALVE_FAIL':     {'aliases': ['valve','solenoid','proportional','spool'],
                           'severity':['fail','failure','dead','broken','stuck','critical']},
    'HYD_VALVE_LAG_SEV':  {'aliases': ['valve','solenoid','spool','response','switching','lag','delay','slow'],
                           'severity':['severe','bad','heavy','major']},
    'HYD_VALVE_LAG_SML':  {'aliases': ['valve','solenoid','spool','lag','delay','sticky'],
                           'severity':['small','slight','minor','little','occasional']},
    'HYD_PUMP_LEAK_SEV':  {'aliases': ['pump','leak','leakage','seal','drain','case'],
                           'severity':['severe','bad','heavy','gushing','major','critical']},
    'HYD_PUMP_LEAK_WEAK': {'aliases': ['pump','leak','leakage','seal','weep','drip'],
                           'severity':['weak','small','slight','minor','seeping']},
    'HYD_ACCUM_FAIL':     {'aliases': ['accumulator','bladder','nitrogen','n2','pressure','pre-charge','precharge'],
                           'severity':['fail','failure','dead','broken','critical','total']},
    'HYD_ACCUM_LOW_SEV':  {'aliases': ['accumulator','bladder','nitrogen','n2','pressure','pre-charge','precharge'],
                           'severity':['severely','very','reduced','bad','heavily']},
    'HYD_ACCUM_LOW_SLT':  {'aliases': ['accumulator','bladder','nitrogen','n2','pressure','pre-charge','precharge'],
                           'severity':['slight','slightly','small','minor','little','low']},
    'HYD_UNSTABLE':       {'aliases': ['unstable','warm-up','warmup','startup','transient','settling'],
                           'severity':[]},
}

ALIAS_WEIGHT       = 2.0
SEVERITY_WEIGHT    = 1.5
DEFAULT_RELATION   = 'resolved_by'
CANONICAL_CODE_RE  = re.compile(r'\b([A-Z]+_[A-Z0-9_]+)\b')
TOKEN_RE           = re.compile(r"[a-z0-9_-]+")
KNOWN_RELATIONS    = {'resolved_by', 'requires_part', 'occurs_on', 'reported', 'co_occurs_with'}


# ─── Core rewrite (standalone API, preserved from lexical_filter.py) ──
@dataclass
class Rewrite:
    canonical_query: str
    code: str
    relation: str
    score: float
    candidates: List[Tuple[str, float]] = field(default_factory=list)


def _tokenize(text: str) -> List[str]:
    return TOKEN_RE.findall(text.lower())


def rewrite(query: str, default_relation: str = DEFAULT_RELATION) -> Rewrite:
    """Return canonical (subject relation) form for an NL fault query."""
    m = CANONICAL_CODE_RE.search(query)
    if m and m.group(1) in CODE_CATALOG:
        words = query.split()
        relation = next((w for w in words if w in KNOWN_RELATIONS), default_relation)
        return Rewrite(f"{m.group(1)} {relation}", m.group(1), relation, 1.0,
                       [(m.group(1), 1.0)])

    tokens = set(_tokenize(query))
    relation = default_relation
    for r in KNOWN_RELATIONS:
        if r in tokens:
            relation = r
            tokens.discard(r)

    scores: List[Tuple[str, float]] = []
    for code, spec in CODE_CATALOG.items():
        alias_hits    = sum(1 for a in spec['aliases']  if a in tokens)
        severity_hits = sum(1 for s in spec['severity'] if s in tokens)
        if alias_hits == 0:
            continue
        raw = ALIAS_WEIGHT * alias_hits + SEVERITY_WEIGHT * severity_hits
        norm = ALIAS_WEIGHT * len(spec['aliases']) + SEVERITY_WEIGHT * len(spec['severity'])
        scores.append((code, raw / norm if norm else 0.0))

    scores.sort(key=lambda x: -x[1])
    if not scores:
        return Rewrite(query, '<unknown>', relation, 0.0, [])
    best_code, best_score = scores[0]
    return Rewrite(f"{best_code} {relation}", best_code, relation, best_score, scores[:5])


# ─── Hook contract adapter ────────────────────────────────────────────
def _make_cleaned_query(rw: Rewrite, original: str) -> Any:
    """Wrap a Rewrite as the CleanedQuery shape expected by edge_service.

    Lazy-import the real CleanedQuery if the hooks module is available;
    fall back to a duck-typed local object otherwise so this file is
    standalone-safe.
    """
    try:
        from hooks import CleanedQuery  # type: ignore
        return CleanedQuery(original=original, cleaned=rw.canonical_query,
                            tokens=rw.canonical_query.split())
    except ImportError:
        @dataclass
        class _LocalCleanedQuery:
            original: str
            cleaned: str
            tokens: List[str]
        return _LocalCleanedQuery(original=original, cleaned=rw.canonical_query,
                                  tokens=rw.canonical_query.split())


def query_cleaner(text: str):
    """Hook entry-point. Maps free-form NL → canonical (subject relation)."""
    return _make_cleaned_query(rewrite(text), text)


def get_hooks(index_dir=None):
    """Auto-discovered by load_hooks(product_dir='/opt/G.A8.1/data/fault_diag')."""
    try:
        from hooks import HookSet  # type: ignore
        return HookSet(query_cleaner=query_cleaner, name="fault_diag")
    except ImportError:
        # Edge module not installed — return None so callers detect & default.
        return None
