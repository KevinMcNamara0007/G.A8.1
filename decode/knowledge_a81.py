"""
G.A8.1 — Knowledge Manager (Two-Tier Emergent Routing)

Drop-in replacement for knowledge_goldc.py KnowledgeManager.
Same interface: query(), learn(), stats().

Architecture:
  - 1,800 shards (36 entity × 50 action) pre-loaded at startup
  - Two-tier routing: hash(subject) × nearest_cluster(relation)
  - MmapCompactIndex per shard (OS-managed pages)
  - Sub-millisecond knn (0.9ms p50 on 12K vectors per shard)
  - Schema-free: any relation phrase, no predefined vocabulary
"""

import gc
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

# ── EHC import ──────────────────────────────────────────────
for _depth in (3, 4, 2, 5):
    _ehc = Path(__file__).resolve().parents[_depth] / "EHC" / "build" / "bindings" / "python"
    if _ehc.exists():
        sys.path.insert(0, str(_ehc))
        break
import ehc

STOP_WORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "is", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "may", "might",
    "can", "shall", "must", "and", "but", "or", "not", "no", "so",
    "if", "then", "than", "that", "this", "it", "its", "with", "from",
    "by", "about", "as", "into", "through", "during",
    "what", "who", "where", "when", "how", "why", "which",
    "tell", "me", "us", "please", "know", "about",
})

# Acronym expansions (universal, not domain-specific)
_ACRONYMS = {
    "ceo": "chief executive officer",
    "cto": "chief technology officer",
    "cfo": "chief financial officer",
    "coo": "chief operating officer",
    "vp": "vice president",
    "pm": "prime minister",
    "usa": "united states america",
    "us": "united states",
    "uk": "united kingdom",
    "eu": "european union",
    "un": "united nations",
    "nato": "north atlantic treaty organization",
    "fbi": "federal bureau investigation",
    "cia": "central intelligence agency",
}

# Possessive patterns
import re
_POSSESSIVE = re.compile(r"(.+?)(?:'s?)\s+(.+)")
# Contraction expansions
_CONTRACTIONS = [
    (r"\bwhat'?s\b", "what is"), (r"\bwho'?s\b", "who is"),
    (r"\bwhere'?s\b", "where is"), (r"\bdon'?t\b", "do not"),
    (r"\bdoesn'?t\b", "does not"), (r"\bisn'?t\b", "is not"),
    (r"\bcan'?t\b", "cannot"), (r"\bit'?s\b", "it is"),
]


def _hash_entity(entity: str, n_buckets: int) -> int:
    h = hashlib.blake2b(entity.encode(), digest_size=8).digest()
    return int.from_bytes(h, "little") % n_buckets


def _tokenize(text: str) -> list:
    return [w for w in text.replace("_", " ").lower().split()
            if w not in STOP_WORDS and len(w) > 1]


def _load_index(npz_path, dim=16384):
    """Load MmapCompactIndex (OS pages) with BSCCompactIndex fallback."""
    d = np.load(str(npz_path), allow_pickle=True)
    sign_scoring = int(d["use_sign_scoring"][0]) if "use_sign_scoring" in d else 1

    if hasattr(ehc, "MmapCompactIndex"):
        idx = ehc.MmapCompactIndex()
        ok = idx.load_from_arrays(
            int(d["dim"][0]), int(d["n_vectors"][0]), sign_scoring,
            np.ascontiguousarray(d["ids"], dtype=np.int32),
            np.ascontiguousarray(d["plus_data"], dtype=np.int32),
            np.ascontiguousarray(d["plus_offsets"], dtype=np.int64),
            np.ascontiguousarray(d["minus_data"], dtype=np.int32),
            np.ascontiguousarray(d["minus_offsets"], dtype=np.int64),
            np.ascontiguousarray(d["vec_indices"], dtype=np.int32),
            np.ascontiguousarray(d["vec_signs"], dtype=np.int8),
            np.ascontiguousarray(d["vec_offsets"], dtype=np.int64),
        )
        if ok:
            return idx

    idx = ehc.BSCCompactIndex(dim, True)
    idx.load_arrays(
        int(d["dim"][0]), int(d["n_vectors"][0]), sign_scoring,
        np.ascontiguousarray(d["ids"], dtype=np.int32),
        np.ascontiguousarray(d["plus_data"], dtype=np.int32),
        np.ascontiguousarray(d["plus_offsets"], dtype=np.int64),
        np.ascontiguousarray(d["minus_data"], dtype=np.int32),
        np.ascontiguousarray(d["minus_offsets"], dtype=np.int64),
        np.ascontiguousarray(d["vec_indices"], dtype=np.int32),
        np.ascontiguousarray(d["vec_signs"], dtype=np.int8),
        np.ascontiguousarray(d["vec_offsets"], dtype=np.int64),
    )
    return idx


class KnowledgeManager:
    """A8.1 Knowledge Manager — schema-free, two-tier emergent routing."""

    def __init__(
        self,
        dim: int = 16384,
        save_path: str = "./data/knowledge.ehkb",
        goldc_path: str = None,
    ):
        self.dim = dim
        self.save_path = save_path
        self._k = int(math.sqrt(dim))
        self._bootstrapped = False
        self._known_relations = set()
        self._corpus_relations = set()
        self._relation_vectors = {}

        # Codebook (hash mode — encodes anything)
        cfg = ehc.CodebookConfig()
        cfg.dim = dim
        cfg.k = self._k
        cfg.seed = 42
        self._cb = ehc.TokenCodebook(cfg)
        self._cb.build_from_vocabulary([])

        # Phrase cache
        self._phrase_cache = ehc.LRUCache(max_size=10000) \
            if hasattr(ehc, "LRUCache") else None

        # Two-tier routing state
        self._n_entity_buckets = 36
        self._n_action_clusters = 50
        self._cluster_centroids = []
        self._shards = {}
        self._shard_texts = {}

        # Local learned triples
        self._all_triples = []

        if goldc_path:
            self._init_a81(goldc_path)

    def _init_a81(self, run_dir: str):
        """Load A8.1 encoded data."""
        t0 = time.perf_counter()
        run_dir = Path(run_dir)

        # Load action clusters
        clusters_path = run_dir / "action_clusters.json"
        if not clusters_path.exists():
            clusters_path = run_dir / "clusters.json"
        if clusters_path.exists():
            with open(clusters_path) as f:
                cluster_data = json.load(f)
            self._n_action_clusters = len(cluster_data)
            for cd in cluster_data:
                ci = cd.get("centroid_indices", [])
                cs = cd.get("centroid_signs", [])
                if ci:
                    self._cluster_centroids.append(ehc.SparseVector(
                        self.dim,
                        np.array(ci, dtype=np.int32),
                        np.array(cs, dtype=np.int8)))
                else:
                    self._cluster_centroids.append(None)
            # Build corpus relations from cluster labels
            for cd in cluster_data:
                self._known_relations.add(cd.get("label", ""))
                for ex in cd.get("examples", []):
                    self._corpus_relations.add(ex.replace(" ", "_"))

        # Load manifest for entity bucket count
        manifest_path = run_dir / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path) as f:
                manifest = json.load(f)
            self._n_entity_buckets = manifest.get("n_entity_buckets", 36)

        # Pre-load all shard indices (MmapCompactIndex — OS-managed pages)
        # Texts are lazy-loaded on first query to save RAM
        self._shard_dirs = {}
        print(f"  [A8.1] Loading shard indices from {run_dir}...")
        for sd in sorted(run_dir.glob("shard_*")):
            npz = sd / "index" / "chunk_index.npz"
            if not npz.exists():
                continue
            sid = int(sd.name.split("_")[1])
            self._shards[sid] = _load_index(npz, self.dim)
            self._shard_dirs[sid] = sd

        elapsed = time.perf_counter() - t0
        self._bootstrapped = True
        print(f"  [A8.1] Ready: {len(self._shards)} shards, "
              f"{self._n_entity_buckets}×{self._n_action_clusters} routing, "
              f"{elapsed:.1f}s")

    def _encode_phrase(self, text: str):
        """Encode text as superpose of tokens."""
        if not text:
            return None
        words = _tokenize(text)
        if not words:
            return None
        vecs = []
        for w in words:
            tv = self._phrase_cache.get(w) if self._phrase_cache else None
            if tv is None:
                try:
                    tv = self._cb.encode_token(w)
                    if self._phrase_cache:
                        self._phrase_cache.put(w, tv)
                except Exception:
                    continue
            vecs.append(tv)
        if not vecs:
            return None
        return ehc.superpose(vecs) if len(vecs) > 1 else vecs[0]

    def _route(self, subject: str, relation: str = None):
        """Two-tier routing → list of shard IDs to search."""
        # Normalize to underscore format — must match encode-time hashing
        subject_key = subject.lower().strip().replace(" ", "_")
        entity_bucket = _hash_entity(subject_key, self._n_entity_buckets)

        # Find top-3 action clusters
        if relation and self._cluster_centroids:
            r_vec = self._encode_phrase(relation)
            if r_vec:
                scores = []
                for ci, cent in enumerate(self._cluster_centroids):
                    if cent is None:
                        continue
                    sim = ehc.sparse_cosine(r_vec, cent)
                    scores.append((ci, sim))
                scores.sort(key=lambda x: -x[1])
                return [entity_bucket * self._n_action_clusters + ci
                        for ci, _ in scores[:3]]

        # No relation or no clusters — search cluster 0
        return [entity_bucket * self._n_action_clusters]

    def _tok(self, val):
        """Normalize entity for lookup."""
        if val is None:
            return None
        return val.lower().strip().replace(" ", "_")

    def _expand_query(self, raw_query: str) -> list:
        """Generate multiple query formulations from raw input.

        Returns list of dicts: {text, subject, relation, method}
        All formulations are queried in parallel, deduped at the end.
        """
        q = raw_query.lower().strip().rstrip("?.,;!:")

        # Expand contractions
        for pattern, replacement in _CONTRACTIONS:
            q = re.sub(pattern, replacement, q)

        formulations = []

        # ── 1. Raw (stop words stripped) ──────────────────────
        raw_tokens = _tokenize(q)
        if raw_tokens:
            formulations.append({
                "text": " ".join(raw_tokens),
                "subject": None,
                "relation": None,
                "method": "raw",
            })

        # Note: auto-split was tested and found to hurt accuracy (67.8% vs 77.2%)
        # by generating wrong S/R splits that pollute results. Removed.

        # ── 2. Possessive expansion: "Tesla's CEO" → "CEO of Tesla"
        poss = _POSSESSIVE.match(q)
        if poss:
            owner = poss.group(1).strip()
            prop = poss.group(2).strip()
            expanded = f"{prop} {owner}"
            formulations.append({
                "text": " ".join(_tokenize(expanded)),
                "subject": _tokenize(owner)[0] if _tokenize(owner) else None,
                "relation": " ".join(_tokenize(prop)),
                "method": "possessive",
            })

        # ── 3. Acronym expansion ──────────────────────────────
        expanded_q = q
        for acr, expansion in _ACRONYMS.items():
            expanded_q = re.sub(r"\b" + acr + r"\b", expansion, expanded_q)
        if expanded_q != q:
            acr_tokens = _tokenize(expanded_q)
            if acr_tokens:
                formulations.append({
                    "text": " ".join(acr_tokens),
                    "subject": None,
                    "relation": None,
                    "method": "acronym",
                })

        # ── 4. "X of Y" pattern → S=Y, R=X ──────────────────
        m = re.search(r"(?:the\s+)?(\w+(?:\s+\w+)?)\s+of\s+(.+)", q)
        if m:
            prop = m.group(1).strip()
            entity = m.group(2).strip()
            # Also with acronym expansion
            prop_expanded = prop
            for acr, expansion in _ACRONYMS.items():
                prop_expanded = re.sub(r"\b" + acr + r"\b", expansion, prop_expanded)
            formulations.append({
                "text": " ".join(_tokenize(f"{entity} {prop_expanded}")),
                "subject": " ".join(_tokenize(entity)) or None,
                "relation": " ".join(_tokenize(prop_expanded)),
                "method": "x_of_y",
            })

        # ── 5. "tell me about X" / "who/what is X" → entity profile ──
        # Because encode uses bind(S, R), a superpose-only query won't match.
        # Fan out with common relation probes to produce bind queries.
        _PROFILE_RELATIONS = [
            "occupation", "employer", "country_of_citizenship",
            "place_of_birth", "educated_at", "instance_of",
            "capital", "country", "continent", "official_language",
            "founded_by", "headquarters_location", "member_of",
            "spouse", "child", "award_received",
            "genre", "author", "director",
        ]
        m = re.match(r"(?:tell\s+(?:me|us)\s+about|who|what)\s+(?:is\s+|are\s+|was\s+|were\s+)?(.+)", q)
        if m:
            entity = m.group(1).strip()
            entity_exp = entity
            for acr, expansion in _ACRONYMS.items():
                entity_exp = re.sub(r"\b" + acr + r"\b", expansion, entity_exp)
            entity_tokens = " ".join(_tokenize(entity_exp))
            # Probe with each common relation
            for rel in _PROFILE_RELATIONS:
                formulations.append({
                    "text": f"{entity_tokens} {rel}",
                    "subject": entity_tokens or None,
                    "relation": rel,
                    "method": "entity_profile",
                })

        # ── 6. "who VERB X" → reverse: R=verb, O=X ──────────
        m = re.match(r"who\s+(\w+(?:ed|s)?)\s+(.+)", q)
        if m:
            verb = m.group(1).strip()
            entity = m.group(2).strip()
            formulations.append({
                "text": " ".join(_tokenize(f"{entity} {verb}")),
                "subject": " ".join(_tokenize(entity)) or None,
                "relation": " ".join(_tokenize(verb)),
                "method": "who_verb",
            })

        # Deduplicate formulations by (text, subject, relation)
        seen = set()
        unique = []
        for f in formulations:
            key = (f["text"], f.get("subject"), f.get("relation"))
            if f["text"] and key not in seen:
                seen.add(key)
                unique.append(f)

        return unique

    def _get_shard_texts(self, sid):
        """Lazy-load texts for a shard on first access."""
        if sid not in self._shard_texts:
            sd = self._shard_dirs.get(sid)
            if sd:
                tp = sd / "texts.json"
                if tp.exists():
                    with open(tp) as f:
                        self._shard_texts[sid] = json.load(f)
                else:
                    self._shard_texts[sid] = []
            else:
                self._shard_texts[sid] = []
        return self._shard_texts[sid]

    def _query_shard(self, qvec, sid, top_k=10):
        """Query a single shard, return parsed results."""
        idx = self._shards.get(sid)
        if idx is None:
            return []
        result = idx.knn_query(qvec, k=top_k)
        texts = self._get_shard_texts(sid)
        results = []
        for vid, score in zip(result.ids, result.scores):
            if vid < len(texts) and score > 0.05:
                raw = texts[vid]
                parts = raw.split()
                if len(parts) >= 2:
                    results.append({
                        "subject": parts[0],
                        "relation": " ".join(parts[1:-1]) if len(parts) > 2 else "",
                        "object": parts[-1],
                        "score": float(score),
                        "triple": {
                            "subject": parts[0],
                            "relation": " ".join(parts[1:-1]) if len(parts) > 2 else "",
                            "object": parts[-1],
                        },
                        "_rank_score": float(score),
                        "source": "a81_corpus",
                    })
        return results

    def query(
        self,
        subject: Optional[str] = None,
        relation: Optional[str] = None,
        obj: Optional[str] = None,
        top_k: int = 5,
        intent: Optional[str] = None,
        raw_query: str = None,
    ) -> List[Dict[str, Any]]:
        """Fan-out query: multiple formulations, parallel knn, dedup.

        If raw_query is provided, expands into multiple formulations.
        Otherwise falls back to subject/relation direct query.
        """
        all_results = []
        all_query_vecs = []  # Collect all formulation vectors for consensus attention
        # Track which (shard, vec_id) we've already fetched to avoid redundant work
        # and to enable re-scoring via get_vector_by_id

        if raw_query:
            # Fan-out: generate all formulations, query each
            formulations = self._expand_query(raw_query)

            for f in formulations:
                text = f["text"]
                subj = f.get("subject")
                rel = f.get("relation")

                # Build query vector(s)
                queries_to_run = []

                # A: superpose all tokens (broad)
                all_vec = self._encode_phrase(text)
                if all_vec:
                    entity_guess = subj or text if text else ""
                    entity_guess = "_".join(entity_guess.split())
                    shards = self._route(entity_guess, rel)
                    queries_to_run.append((all_vec, shards))
                    all_query_vecs.append(all_vec)

                # B: bind(S, R) if we have both (precise)
                if subj and rel:
                    s_vec = self._encode_phrase(subj)
                    r_vec = self._encode_phrase(rel)
                    if s_vec and r_vec:
                        bind_vec = ehc.bind_bsc(s_vec, r_vec)
                        shards = self._route(subj, rel)
                        queries_to_run.append((bind_vec, shards))
                        all_query_vecs.append(bind_vec)

                # Execute all queries
                for qvec, shard_ids in queries_to_run:
                    for sid in shard_ids:
                        results = self._query_shard(qvec, sid, top_k=top_k * 2)
                        # Tag results with their source shard for later re-scoring
                        for r in results:
                            r["_shard_id"] = sid
                        all_results.extend(results)

        else:
            # Direct query (backward compat)
            s = self._tok(subject) if subject else None
            if not s:
                return []

            s_vec = self._encode_phrase(s)
            r_vec = self._encode_phrase(relation) if relation else None

            if s_vec and r_vec:
                qvec = ehc.bind_bsc(s_vec, r_vec)
            elif s_vec:
                qvec = s_vec
            else:
                return []

            target_shards = self._route(s, relation)
            for sid in target_shards:
                results = self._query_shard(qvec, sid, top_k=top_k * 2)
                all_results.extend(results)

        # Also check locally learned triples
        if self._all_triples:
            query_tokens = set(_tokenize(raw_query or subject or ""))
            for t in self._all_triples:
                t_tokens = set(_tokenize(f"{t.get('subject','')} {t.get('relation','')}"))
                if query_tokens & t_tokens:
                    all_results.append({
                        "subject": t["subject"],
                        "relation": t.get("relation", ""),
                        "object": t["object"],
                        "score": 0.75,
                        "triple": t,
                        "_rank_score": 0.75,
                        "source": "local_learned",
                    })

        # ── Consensus Attention ──────────────────────────────────
        # Build canonical attention vector = superpose of all formulation vectors.
        # Use for re-ranking: candidates that match multiple formulations rise.
        # Raw score is preserved — attention is a tiebreaker, not an override.
        if all_query_vecs and all_results:
            consensus_vec = ehc.superpose(all_query_vecs) if len(all_query_vecs) > 1 \
                else all_query_vecs[0]

            # Consensus attention: rescore candidates against the consensus vector.
            # Raw score gates (threshold), consensus cosine ranks (ordering).
            # Fan-out handles coverage. Consensus handles Hit@1.
            from collections import Counter
            answer_votes = Counter()
            for r in all_results:
                key = (r.get("subject", ""), r.get("object", ""))
                answer_votes[key] += 1

            for r in all_results:
                key = (r.get("subject", ""), r.get("object", ""))
                raw_score = r.get("score", 0)
                votes = answer_votes[key]

                # Re-encode result's SR and score against consensus
                s_text = r.get("subject", "")
                r_text = r.get("relation", "")
                s_vec = self._encode_phrase(s_text)
                r_vec = self._encode_phrase(r_text) if r_text else None

                attention = 0.0
                if s_vec and r_vec:
                    result_vec = ehc.bind_bsc(s_vec, r_vec)
                    attention = ehc.sparse_cosine(consensus_vec, result_vec)
                elif s_vec:
                    attention = ehc.sparse_cosine(consensus_vec, s_vec)

                # Preserve raw score for threshold gating
                # Rank by: consensus attention (primary) + vote bonus (tiebreaker)
                vote_bonus = min(votes * 0.02, 0.10)
                r["_raw_score"] = raw_score
                r["_attention"] = float(attention)
                r["_votes"] = votes
                # score used for threshold: keep raw
                # _rank_score used for ordering: consensus + votes
                r["_rank_score"] = attention + vote_bonus

        # ── Query intent detection (who/what/where → instance_of filter)
        _query_lower = (raw_query or "").lower().strip()
        intent_type = None
        if _query_lower.startswith("who "):
            intent_type = "person"
        elif _query_lower.startswith("where "):
            intent_type = "place"

        _PERSON_TYPES = frozenset({
            "human", "person", "fictional_character",
        })
        _PLACE_TYPES = frozenset({
            "city", "country", "state", "village", "town",
            "administrative_territorial_entity", "capital",
        })

        # Extract query entity tokens for relevance filtering
        query_entity_tokens = set()
        if raw_query:
            forms = self._expand_query(raw_query)
            for f in forms:
                if f.get("subject"):
                    query_entity_tokens.update(f["subject"].split())
                    break
            if not query_entity_tokens:
                query_entity_tokens = set(_tokenize(raw_query))
        elif subject:
            query_entity_tokens = set(_tokenize(subject))

        # Filter: keep only results whose subject shares tokens with query entity
        # Score floor: discard low-similarity noise
        SCORE_FLOOR = 0.15
        filtered = []
        for r in all_results:
            # Use raw score for threshold gating (not consensus-modified score)
            if r.get("_raw_score", r.get("score", 0)) < SCORE_FLOOR:
                continue
            # Skip trivially short subjects (single char artifacts)
            if len(r.get("subject", "")) < 2:
                continue
            # Subject relevance: require meaningful overlap with query entity
            result_subj_tokens = set(_tokenize(r.get("subject", "")))
            if query_entity_tokens and result_subj_tokens:
                overlap = query_entity_tokens & result_subj_tokens
                # Need at least 1 overlapping token, AND
                # overlap must cover majority of query entity (not just "a" matching)
                min_overlap = max(1, len(query_entity_tokens) // 2)
                if len(overlap) < min_overlap:
                    continue
            filtered.append(r)

        # ── Intent disambiguation: "who" → prefer person entities
        if intent_type and filtered:
            # Group results by subject entity
            from collections import defaultdict
            by_subject = defaultdict(list)
            for r in filtered:
                by_subject[r.get("subject", "")].append(r)

            # Score each subject by intent match
            # Check instance_of values for each subject
            subject_scores = {}
            for subj, results in by_subject.items():
                instance_types = set()
                for r in results:
                    if r.get("relation", "") == "instance_of":
                        instance_types.add(r.get("object", "").lower())

                if intent_type == "person":
                    is_match = bool(instance_types & _PERSON_TYPES)
                elif intent_type == "place":
                    is_match = bool(instance_types & _PLACE_TYPES)
                else:
                    is_match = True

                # Also use triple count as tiebreaker (more triples = more notable)
                subject_scores[subj] = (is_match, len(results))

            # Keep only results from intent-matching subjects
            # If no subjects match intent, keep all (don't over-filter)
            matching_subjects = {s for s, (match, _) in subject_scores.items() if match}
            if matching_subjects:
                # Pick the best matching subject (most triples)
                best_subject = max(matching_subjects,
                                   key=lambda s: subject_scores[s][1])
                filtered = [r for r in filtered if r.get("subject") == best_subject]

        # Dedup by (subject, relation, object) — sort by consensus rank score
        seen = set()
        merged = []
        for r in sorted(filtered, key=lambda x: -x.get("_rank_score", x.get("score", 0))):
            key = (r.get("subject", ""), r.get("relation", ""), r.get("object", ""))
            if key[2] and key not in seen:
                seen.add(key)
                merged.append(r)

        return merged

    def learn(self, triples: List[Dict[str, str]]) -> int:
        """Learn new triples (stored locally, not re-indexed)."""
        if not triples:
            return 0
        count = 0
        for t in triples:
            s = t.get("subject", "").strip()
            r = t.get("relation", "").strip()
            o = t.get("object", "").strip()
            if s and o:
                self._all_triples.append({
                    "subject": s.lower().replace(" ", "_"),
                    "relation": r.lower().replace(" ", "_"),
                    "object": o.lower().replace(" ", "_"),
                })
                self._known_relations.add(r.lower().replace(" ", "_"))
                count += 1
        return count

    def learn_query_mapping(self, query_text, subject, relation):
        """Compatibility stub — A8.1 doesn't use query mappings."""
        pass

    def lookup_query_mapping(self, query_text):
        """Compatibility stub."""
        return None

    @property
    def known_relations(self):
        return frozenset(self._known_relations)

    def stats(self) -> Dict[str, Any]:
        return {
            "triple_count": sum(
                idx.size() if hasattr(idx, 'size') and callable(idx.size) else 0
                for idx in self._shards.values()
            ) + len(self._all_triples),
            "goldc_triples": sum(
                idx.size() if hasattr(idx, 'size') and callable(idx.size) else 0
                for idx in self._shards.values()
            ),
            "local_triples": len(self._all_triples),
            "vocab_size": 0,
            "relation_count": len(self._known_relations),
            "goldc_shards": len(self._shards),
            "backend": "a81_two_tier",
        }

    def save(self):
        """Save locally learned triples."""
        if self._all_triples:
            os.makedirs(os.path.dirname(self.save_path), exist_ok=True)
            with open(self.save_path + ".a81_local.json", "w") as f:
                json.dump(self._all_triples, f)
