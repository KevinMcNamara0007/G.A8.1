"""
G.A8.1 — Hook Architecture

Seven hooks, one engine. Products override via hooks.py.
Convention over configuration: auto-detect what's available.

ENCODE HOOKS (run at ingest time):
  resolver         — normalize tokens (BRCC1→brca1, Q142→france)
  salience_scorer  — IDF × gazetteer boost
  media_encoder    — vision/video/audio modality encoding

QUERY HOOKS (run at query time):
  query_cleaner    — NER, gazetteers, intent classification
  reranker         — multi-factor scoring (Hebbian, recency, keyword, etc.)
  enricher         — "Why this matched", context, previews

FEEDBACK HOOK:
  learner          — Hebbian correlation, query log, click-through

Usage:
    from hooks import HookSet, DefaultHooks, load_hooks

    # Auto-detect from product directory
    hooks = load_hooks("/path/to/product")

    # Or explicit
    hooks = HookSet(
        query_cleaner=my_cleaner,
        reranker=my_reranker,
    )

    svc = QueryService(run_dir, hooks=hooks)
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, List, Dict, Any


# ═════════════════════════════════════════════════════════════
#  TYPE DEFINITIONS
# ═════════════════════════════════════════════════════════════

@dataclass
class CleanedQuery:
    """Output of query_cleaner hook."""
    original: str                          # raw user query
    cleaned: str                           # filtered query for encoding
    tokens: List[str]                      # tokenized search terms
    intent: str = ""                       # classified intent
    locations: List[str] = field(default_factory=list)
    organizations: List[str] = field(default_factory=list)
    concepts: List[str] = field(default_factory=list)
    other_keywords: List[str] = field(default_factory=list)


@dataclass
class ScoredResult:
    """A result with scores and metadata, passed through reranker."""
    id: str
    shard_id: int
    vec_id: int
    bsc_score: float
    combined_score: float
    metadata: Dict[str, Any]
    keyword_score: float = 0.0
    proximity_score: float = 0.0
    hebbian_boost: float = 0.0
    recency_score: float = 0.0
    explanation: str = ""


# ═════════════════════════════════════════════════════════════
#  HOOK TYPE SIGNATURES
# ═════════════════════════════════════════════════════════════

# query_cleaner(raw_text) → CleanedQuery
QueryCleanerFn = Callable[[str], CleanedQuery]

# reranker(query: CleanedQuery, results: List[ScoredResult], context: dict) → List[ScoredResult]
RerankerFn = Callable[[CleanedQuery, List['ScoredResult'], dict], List['ScoredResult']]

# enricher(query: CleanedQuery, results: List[ScoredResult]) → List[ScoredResult]
# Adds explanation, context, previews to each result
EnricherFn = Callable[[CleanedQuery, List['ScoredResult']], List['ScoredResult']]

# learner(query: CleanedQuery, results: List[ScoredResult]) → None
# Post-query feedback (Hebbian, click-through, etc.)
LearnerFn = Callable[[CleanedQuery, List['ScoredResult']], None]

# resolver(token: str) → str
# Token normalization at encode time
ResolverFn = Callable[[str], str]

# salience_scorer(token: str, idf_score: float) → float
# Boost score at encode time
SalienceScorerFn = Callable[[str, float], float]


# ═════════════════════════════════════════════════════════════
#  HOOK SET
# ═════════════════════════════════════════════════════════════

@dataclass
class HookSet:
    """Complete set of hooks for a product/domain.

    Any hook left as None uses the default implementation.
    """
    # Query-time hooks
    query_cleaner: Optional[QueryCleanerFn] = None
    reranker: Optional[RerankerFn] = None
    enricher: Optional[EnricherFn] = None
    learner: Optional[LearnerFn] = None

    # Encode-time hooks (used by worker_encode)
    resolver: Optional[ResolverFn] = None
    salience_scorer: Optional[SalienceScorerFn] = None

    # Name for logging
    name: str = "default"


# ═════════════════════════════════════════════════════════════
#  DEFAULT IMPLEMENTATIONS
# ═════════════════════════════════════════════════════════════

STOP_WORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "is", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "may", "might",
    "can", "shall", "must", "and", "but", "or", "not", "no", "so",
    "if", "then", "than", "that", "this", "it", "its", "with", "from",
    "by", "about", "as", "into", "through", "during",
})

QUERY_FILTER_WORDS = frozenset({
    "find", "search", "show", "list", "get", "give", "tell", "display",
    "retrieve", "fetch", "lookup", "look", "query",
    "all", "any", "some", "every", "each",
    "documents", "document", "docs", "doc",
    "articles", "article", "posts", "post", "messages", "message",
    "records", "record", "entries", "entry", "items", "item",
    "results", "result", "matches", "match",
    "information", "info", "data", "details",
    "about", "regarding", "concerning", "involving", "related",
    "mentioning", "references", "discussing",
    "what", "where", "when", "how", "why", "which", "who", "whom",
    "me", "you", "us", "them", "it",
})


def default_query_cleaner(text: str) -> CleanedQuery:
    """Default: tokenize, strip stops + filter words."""
    tokens = [w for w in text.replace("_", " ").lower().split()
              if w not in STOP_WORDS and w not in QUERY_FILTER_WORDS and len(w) > 1]
    return CleanedQuery(
        original=text,
        cleaned=" ".join(tokens),
        tokens=tokens,
    )


def default_reranker(query: CleanedQuery, results: List[ScoredResult],
                     context: dict = None) -> List[ScoredResult]:
    """Default reranker: BSC + keyword + proximity with configurable weights."""
    # Read weights from config or use defaults
    try:
        from config import cfg
        w_bsc = cfg.WEIGHT_BSC
        w_kw = cfg.WEIGHT_KEYWORD
        w_prox = cfg.WEIGHT_PROXIMITY
    except ImportError:
        w_bsc, w_kw, w_prox = 50, 40, 10

    for r in results:
        text = r.metadata.get("text", "") or r.metadata.get("message_text_translated", "")
        text_lower = text.lower()

        # Keyword score
        if query.tokens:
            matches = sum(1 for t in query.tokens if t in text_lower)
            r.keyword_score = (matches * 100.0) / len(query.tokens)
        else:
            r.keyword_score = 0.0

        # Proximity score
        if len(query.tokens) >= 2:
            phrase = " ".join(query.tokens)
            if phrase in text_lower:
                r.proximity_score = 100.0
            else:
                total_pairs = len(query.tokens) - 1
                pairs_found = sum(1 for i in range(total_pairs)
                                 if f"{query.tokens[i]} {query.tokens[i+1]}" in text_lower)
                r.proximity_score = (pairs_found * 100.0) / total_pairs if total_pairs > 0 else 0.0
        else:
            r.proximity_score = 0.0

        # Combined with configurable weights
        bsc = r.bsc_score * 100.0
        if r.keyword_score > 0:
            r.combined_score = (w_bsc * bsc + w_kw * r.keyword_score + w_prox * r.proximity_score) / 10000.0
        else:
            r.combined_score = (30 * bsc) / 10000.0

    results.sort(key=lambda r: -r.combined_score)
    return results


def default_enricher(query: CleanedQuery, results: List[ScoredResult]) -> List[ScoredResult]:
    """Default: generate basic match explanation from keyword overlap."""
    for r in results:
        text = r.metadata.get("text", "") or r.metadata.get("message_text_translated", "")
        text_lower = text.lower()
        matched = [t for t in query.tokens if t in text_lower]
        missed = [t for t in query.tokens if t not in text_lower]

        if matched:
            r.explanation = f"Matched terms: {', '.join(matched)}"
            if missed:
                r.explanation += f" | Missing: {', '.join(missed)}"
        else:
            r.explanation = f"BSC vector similarity ({r.bsc_score:.3f})"

    return results


def default_learner(query: CleanedQuery, results: List[ScoredResult]) -> None:
    """Default: no-op. Override for Hebbian, click-through, etc."""
    pass


def default_resolver(token: str) -> str:
    """Default: identity (no normalization)."""
    return token


def default_salience_scorer(token: str, idf_score: float) -> float:
    """Default: pure IDF (no boost)."""
    return idf_score


# ═════════════════════════════════════════════════════════════
#  DEFAULT HOOKSET
# ═════════════════════════════════════════════════════════════

DEFAULT_HOOKS = HookSet(
    query_cleaner=default_query_cleaner,
    reranker=default_reranker,
    enricher=default_enricher,
    learner=default_learner,
    resolver=default_resolver,
    salience_scorer=default_salience_scorer,
    name="default",
)


# ═════════════════════════════════════════════════════════════
#  AUTO-DETECTION & LOADING
# ═════════════════════════════════════════════════════════════

def load_hooks(product_dir: str = None, index_dir: str = None) -> HookSet:
    """Auto-detect and load hooks for a product.

    Convention:
      1. If product_dir/hooks.py exists → import and call get_hooks()
      2. If index_dir has _gazetteer.json → auto-enable gazetteer boost
      3. Otherwise → default hooks

    Products override by providing hooks.py with:
        def get_hooks(index_dir: str = None) -> HookSet:
            return HookSet(query_cleaner=my_cleaner, ...)
    """
    hooks = HookSet(
        query_cleaner=default_query_cleaner,
        reranker=default_reranker,
        enricher=default_enricher,
        learner=default_learner,
        resolver=default_resolver,
        salience_scorer=default_salience_scorer,
        name="default",
    )

    # Try loading product-specific hooks
    if product_dir:
        hooks_file = Path(product_dir) / "hooks.py"
        if hooks_file.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("product_hooks", str(hooks_file))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "get_hooks"):
                product_hooks = mod.get_hooks(index_dir=index_dir)
                # Merge: product overrides take precedence
                for field_name in ("query_cleaner", "reranker", "enricher", "learner",
                                   "resolver", "salience_scorer", "name"):
                    val = getattr(product_hooks, field_name, None)
                    if val is not None:
                        setattr(hooks, field_name, val)
                print(f"[hooks] Loaded product hooks: {hooks.name}")
                return hooks

    # Auto-detect gazetteer boost (check output root first, then _chunks/)
    if index_dir:
        gaz_path = Path(index_dir) / "_gazetteer.json"
        if not gaz_path.exists():
            gaz_path = Path(index_dir) / "_chunks" / "_gazetteer.json"
        if gaz_path.exists():
            import json
            with open(gaz_path) as f:
                gaz_terms = frozenset(json.load(f))
            boost = 3.0

            def gazetteer_scorer(token: str, idf_score: float) -> float:
                return idf_score * (boost if token in gaz_terms else 1.0)

            hooks.salience_scorer = gazetteer_scorer
            hooks.name = "default+gazetteer"
            print(f"[hooks] Auto-detected gazetteer: {len(gaz_terms)} terms")

    return hooks
