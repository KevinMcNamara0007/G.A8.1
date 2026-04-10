"""
G.A8.1 — Adaptive Gazetteer (Hebbian + Ebbinghaus)

Learns query term → result term associations from the scoring pipeline.
No PMI. No corpus scanning. No separate learning system.

The multi-factor score IS the relevance signal:
  Query "humanitarian" → top results contain "displaced", "relief"
  → strengthen(humanitarian → displaced)
  → Ebbinghaus: reinforced terms persist, unreinforced terms decay

One mechanism:
  - Observe: extract terms from high-scoring results
  - Reinforce: strengthen associations that recur across queries
  - Forget: Ebbinghaus decay prunes noise automatically
  - Expand: return alive associations for query expansion

Works from the first query. No cold start. No corpus pre-processing.

Usage:
    ag = AdaptiveGazetteer(index_dir="/path/to/encoded")

    # After each query (in the hot path):
    ag.observe(query_tokens=["humanitarian", "crisis"],
               result_terms=["displaced", "lebanon", "shelter", "aid"],
               avg_score=0.45)

    # Before encoding a query:
    expansions = ag.expand("humanitarian")  # → ["displaced", "aid"]
"""

import json
import math
import threading
import time
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


STOP_WORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "is", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "may", "might",
    "can", "shall", "must", "and", "but", "or", "not", "no", "so",
    "if", "then", "than", "that", "this", "it", "its", "with", "from",
    "by", "about", "as", "into", "through", "during",
})


# ═════════════════════════════════════════════════════════════
#  EBBINGHAUS MEMORY
# ═════════════════════════════════════════════════════════════

@dataclass
class Association:
    """A learned term→term association with Ebbinghaus dynamics."""
    term: str                      # expansion term
    root: str                      # query term it expands
    stability: float = 1.0         # S: days until ~37% retention, doubles per reinforcement
    last_reinforced: float = 0.0   # timestamp
    reinforcement_count: int = 1   # times reinforced
    created_at: float = 0.0

    def retention(self, now: float = None) -> float:
        """e^(-t/S) where t = days since last reinforcement."""
        if now is None:
            now = time.time()
        t_days = (now - self.last_reinforced) / 86400.0
        if t_days <= 0:
            return 1.0
        return math.exp(-t_days / max(self.stability, 0.01))

    def reinforce(self, now: float = None):
        """Stability doubles. Retention resets."""
        if now is None:
            now = time.time()
        self.stability = min(self.stability * 2.0, 365.0)
        self.last_reinforced = now
        self.reinforcement_count += 1

    def is_alive(self, now: float = None, threshold: float = 0.1) -> bool:
        return self.retention(now) >= threshold


# ═════════════════════════════════════════════════════════════
#  ADAPTIVE GAZETTEER
# ═════════════════════════════════════════════════════════════

class AdaptiveGazetteer:
    """Learns query→result term associations from scoring pipeline results.

    Thread-safe. Zero query latency overhead for observation.
    Expansion is O(1) dict lookup.
    """

    def __init__(self, index_dir: str = None,
                 max_expansions_per_term: int = 5,
                 min_score_to_learn: float = 0.15,
                 retention_threshold: float = 0.1,
                 min_term_length: int = 4,
                 save_interval: int = 50,
                 **kwargs):
        """
        Args:
            max_expansions_per_term: cap alive expansions per root
            min_score_to_learn: minimum result score to extract terms from
            retention_threshold: prune associations below this
            min_term_length: minimum chars for a term to be learned
            save_interval: save to disk every N observations
        """
        self.max_expansions = max_expansions_per_term
        self.min_score = min_score_to_learn
        self.retention_threshold = retention_threshold
        self.min_term_length = min_term_length
        self.save_interval = save_interval

        # Association store: root_term → {expansion_term → Association}
        self.memories: Dict[str, Dict[str, Association]] = {}
        self._lock = threading.Lock()
        self._observation_count = 0

        # Persistence
        self._save_path = (Path(index_dir) / "_adaptive_gazetteer.json"
                           if index_dir else None)
        self._load()

    # ── Core API ─────────────────────────────────────────────

    def observe(self, query_tokens: List[str], result_terms: List[str],
                avg_score: float):
        """Observe a query→result pair. Learn associations from high-scoring results.

        Called in the hot path after reranking. Extracts terms from top results
        and strengthens associations with query tokens.

        Args:
            query_tokens: cleaned query tokens (from query_cleaner)
            result_terms: terms extracted from top-scoring result texts
            avg_score: average multi-factor score of top results
        """
        if avg_score < self.min_score:
            return  # results too weak to learn from

        now = time.time()

        # Filter result terms: clean, non-stop, sufficient length
        good_terms = set()
        for t in result_terms:
            t_clean = t.lower().strip()
            if (len(t_clean) >= self.min_term_length
                    and t_clean.isalpha()
                    and t_clean not in STOP_WORDS):
                good_terms.add(t_clean)

        # Query tokens (cleaned)
        q_set = set(t.lower() for t in query_tokens
                    if len(t) >= self.min_term_length)

        # Learn: for each query token, strengthen associations with result terms
        # that are NOT already in the query (those are new associations)
        with self._lock:
            for q_term in q_set:
                for r_term in good_terms:
                    if r_term == q_term:
                        continue  # don't associate a term with itself
                    if r_term in q_set:
                        continue  # don't associate query terms with each other

                    if q_term not in self.memories:
                        self.memories[q_term] = {}

                    entries = self.memories[q_term]
                    if r_term in entries:
                        # Reinforce existing association
                        entries[r_term].reinforce(now)
                    elif len([e for e in entries.values()
                             if e.is_alive(now, self.retention_threshold)]) < self.max_expansions:
                        # Learn new association (if under cap)
                        entries[r_term] = Association(
                            term=r_term,
                            root=q_term,
                            stability=1.0,
                            last_reinforced=now,
                            reinforcement_count=1,
                            created_at=now,
                        )

        self._observation_count += 1
        if self._observation_count % self.save_interval == 0:
            self._prune()
            self._save()

    def expand(self, term: str) -> List[str]:
        """Get learned expansions for a term. O(1). Thread-safe."""
        with self._lock:
            entries = self.memories.get(term.lower(), {})
            now = time.time()
            alive = [(e.term, e.reinforcement_count)
                     for e in entries.values()
                     if e.is_alive(now, self.retention_threshold)]
            # Return sorted by reinforcement count (strongest first)
            alive.sort(key=lambda x: -x[1])
            return [t for t, _ in alive]

    def expand_tokens(self, tokens: List[str]) -> List[str]:
        """Expand a list of tokens with learned associations."""
        expanded = list(tokens)
        seen = set(t.lower() for t in tokens)
        for t in tokens:
            for exp in self.expand(t):
                if exp not in seen:
                    expanded.append(exp)
                    seen.add(exp)
        return expanded

    def start(self):
        """No background thread needed — learning happens in observe()."""
        logger.info(f"[AdaptiveGaz] Ready (Hebbian+Ebbinghaus, "
                    f"{self.stats['alive_entries']} alive associations)")

    def stop(self):
        """Save state on shutdown."""
        self._prune()
        self._save()
        logger.info(f"[AdaptiveGaz] Saved ({self.stats['alive_entries']} alive)")

    @property
    def stats(self) -> dict:
        with self._lock:
            now = time.time()
            alive = sum(1 for entries in self.memories.values()
                       for e in entries.values()
                       if e.is_alive(now, self.retention_threshold))
            total = sum(len(entries) for entries in self.memories.values())
            roots = len(self.memories)

            # Top associations by reinforcement
            top = []
            for root, entries in self.memories.items():
                for e in entries.values():
                    if e.is_alive(now):
                        top.append((root, e.term, e.reinforcement_count, e.stability))
            top.sort(key=lambda x: -x[2])

        return {
            "roots": roots,
            "total_entries": total,
            "alive_entries": alive,
            "observations": self._observation_count,
            "top_associations": [
                {"root": r, "term": t, "reinforcements": n, "stability_days": round(s, 1)}
                for r, t, n, s in top[:10]
            ],
        }

    # ── Helpers ──────────────────────────────────────────────

    def _prune(self):
        """Remove dead associations."""
        now = time.time()
        pruned = 0
        with self._lock:
            for root in list(self.memories.keys()):
                entries = self.memories[root]
                dead = [k for k, v in entries.items()
                       if not v.is_alive(now, self.retention_threshold)]
                for k in dead:
                    del entries[k]
                    pruned += 1
                if not entries:
                    del self.memories[root]
        if pruned > 0:
            logger.info(f"[AdaptiveGaz] Pruned {pruned} forgotten associations")

    def _save(self):
        if not self._save_path:
            return
        with self._lock:
            data = {}
            for root, entries in self.memories.items():
                data[root] = {
                    k: {
                        "term": v.term, "root": v.root,
                        "stability": v.stability,
                        "last_reinforced": v.last_reinforced,
                        "reinforcement_count": v.reinforcement_count,
                        "created_at": v.created_at,
                    }
                    for k, v in entries.items()
                }
        try:
            with open(self._save_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"[AdaptiveGaz] Save failed: {e}")

    def _load(self):
        if not self._save_path or not self._save_path.exists():
            return
        try:
            with open(self._save_path) as f:
                data = json.load(f)
            now = time.time()
            loaded = 0
            for root, entries in data.items():
                self.memories[root] = {}
                for k, v in entries.items():
                    entry = Association(
                        term=v["term"], root=v["root"],
                        stability=v["stability"],
                        last_reinforced=v["last_reinforced"],
                        reinforcement_count=v["reinforcement_count"],
                        created_at=v["created_at"],
                    )
                    if entry.is_alive(now, self.retention_threshold):
                        self.memories[root][k] = entry
                        loaded += 1
                if not self.memories[root]:
                    del self.memories[root]
            if loaded > 0:
                logger.info(f"[AdaptiveGaz] Loaded {loaded} alive associations")
        except Exception as e:
            logger.warning(f"[AdaptiveGaz] Load failed: {e}")
