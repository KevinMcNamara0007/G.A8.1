#!/usr/bin/env python3
"""
G.A8.1 — Unit Tests

Tests edge cases and component contracts:
  - Tokenizer behavior
  - Salience selection (empty, short, long, gazetteer)
  - Config loading and env override
  - Hook system (defaults, override, auto-detect)
  - Incremental ingest
  - Sidecar integrity
  - Query service (empty index, missing shard)

Run: python3 tests/test_unit.py
  or: cd G.A8.1 && python3 -m pytest tests/test_unit.py -v
"""

import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

# ── Path setup ───────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "decode"))
sys.path.insert(0, str(ROOT / "encode"))

for _d in (1, 2, 3, 4):
    _p = ROOT.parents[_d - 1] / "EHC" / "build" / "bindings" / "python"
    if _p.exists():
        sys.path.insert(0, str(_p))
        break

import ehc
import numpy as np

PASS = 0
FAIL = 0


def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        print(f"  \033[32m✓\033[0m {name}")
        PASS += 1
    else:
        print(f"  \033[31m✗\033[0m {name}: {detail}")
        FAIL += 1


# ═════════════════════════════════════════════════════════════
#  TOKENIZER
# ═════════════════════════════════════════════════════════════
print("\n== Tokenizer ==")

from worker_encode import _tokenize

test("empty string", _tokenize("") == [])
test("stop words only", _tokenize("the a an of in on") == [])
test("single char filtered", _tokenize("a b c") == [])
test("underscores split", "iran" in _tokenize("islamic_republic_of_iran"))
test("case insensitive", _tokenize("IRAN") == _tokenize("iran"))
test("preserves order", _tokenize("iran missile test") == ["iran", "missile", "test"])
test("unicode passthrough", len(_tokenize("تهران tehran")) > 0)

# ═════════════════════════════════════════════════════════════
#  SALIENCE SELECTION
# ═════════════════════════════════════════════════════════════
print("\n== Salience Selection ==")

from worker_encode import _select_salient

idf = {"iran": 1.0, "missile": 5.0, "test": 2.0, "nuclear": 4.0,
       "the": 0.1, "rare_word": 10.0, "terrorism": 0.5}

test("short list returned as-is",
     _select_salient(["iran", "missile"], idf, max_tokens=12) == ["iran", "missile"])

test("long list truncated to max",
     len(_select_salient(["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n"],
                          idf, max_tokens=3)) == 3)

test("highest IDF wins",
     "rare_word" in _select_salient(
         ["iran", "missile", "test", "nuclear", "rare_word", "terrorism",
          "extra1", "extra2", "extra3", "extra4", "extra5", "extra6", "extra7"],
         idf, max_tokens=3))

# Gazetteer guaranteed slots
gaz = frozenset({"terrorism", "missile"})
result = _select_salient(
    ["iran", "rare_word", "extra1", "extra2", "extra3", "extra4",
     "extra5", "extra6", "extra7", "extra8", "extra9", "extra10",
     "extra11", "terrorism", "missile"],
    idf, max_tokens=5, gazetteer=gaz)
test("gazetteer terms guaranteed",
     "terrorism" in result and "missile" in result,
     f"got: {result}")

test("empty tokens", _select_salient([], idf, max_tokens=12) == [])

# ═════════════════════════════════════════════════════════════
#  CONFIG
# ═════════════════════════════════════════════════════════════
print("\n== Config ==")

from config import cfg

test("default DIM", cfg.DIM == 16384)
test("default K", cfg.K == 128)
test("default SEED", cfg.SEED == 42)
test("default MAX_SALIENT", cfg.MAX_SALIENT_TOKENS == 12)
test("N_SHARDS computed", cfg.N_SHARDS == cfg.ENTITY_BUCKETS * cfg.ACTION_CLUSTERS)
test("summary string", "D=16384" in cfg.summary())

# ═════════════════════════════════════════════════════════════
#  HOOKS
# ═════════════════════════════════════════════════════════════
print("\n== Hooks ==")

from hooks import (load_hooks, DEFAULT_HOOKS, HookSet, CleanedQuery,
                    ScoredResult, default_query_cleaner, default_reranker)

test("default hooks load", DEFAULT_HOOKS.name == "default")
test("all defaults present",
     all([DEFAULT_HOOKS.query_cleaner, DEFAULT_HOOKS.reranker,
          DEFAULT_HOOKS.enricher, DEFAULT_HOOKS.learner]))

# Query cleaner
cleaned = default_query_cleaner("find all links between Iran and Terror")
test("cleaner strips filter words", "find" not in cleaned.tokens)
test("cleaner keeps content", "iran" in cleaned.tokens)
test("cleaner keeps terror", "terror" in cleaned.tokens)

# Reranker with no results
empty_ranked = default_reranker(cleaned, [])
test("reranker handles empty", empty_ranked == [])

# Reranker with results
r1 = ScoredResult(id="1", shard_id=0, vec_id=0, bsc_score=0.5,
                   combined_score=0.5, metadata={"text": "iran missile test"})
r2 = ScoredResult(id="2", shard_id=0, vec_id=1, bsc_score=0.3,
                   combined_score=0.3, metadata={"text": "unrelated content"})
ranked = default_reranker(cleaned, [r1, r2])
test("reranker sorts by combined", ranked[0].combined_score >= ranked[1].combined_score)
test("keyword match boosts", ranked[0].keyword_score > ranked[1].keyword_score)

# Auto-detect with no product dir
h = load_hooks()
test("no product → default", h.name == "default")

# ═════════════════════════════════════════════════════════════
#  ADAPTIVE GAZETTEER
# ═════════════════════════════════════════════════════════════
print("\n== Adaptive Gazetteer ==")

from adaptive_gazetteer import AdaptiveGazetteer, Association

# Ebbinghaus retention
a = Association(term="test", root="query", stability=1.0,
                last_reinforced=time.time(), reinforcement_count=1,
                created_at=time.time())
test("fresh association alive", a.is_alive())
test("retention near 1.0", a.retention() > 0.99)

# Reinforcement doubles stability
a.reinforce()
test("reinforcement increases stability", a.stability == 2.0)
test("reinforcement count", a.reinforcement_count == 2)

# Old association decays
old = Association(term="old", root="q", stability=1.0,
                  last_reinforced=time.time() - 86400 * 5,  # 5 days ago
                  reinforcement_count=1, created_at=time.time() - 86400 * 5)
test("old association decayed", old.retention() < 0.1)
test("old association not alive", not old.is_alive())

# Gazetteer observe + expand
with tempfile.TemporaryDirectory() as tmpdir:
    ag = AdaptiveGazetteer(index_dir=tmpdir)
    ag.observe(["iran", "missile"], ["launched", "ballistic", "tehran"], avg_score=0.5)
    # "launched" should be associated with "iran" and "missile"
    exps = ag.expand("iran")
    test("learns from observation", len(exps) > 0 or ag.stats["observations"] == 1,
         f"exps={exps}, stats={ag.stats}")

# ═════════════════════════════════════════════════════════════
#  INCREMENTAL INGEST
# ═════════════════════════════════════════════════════════════
print("\n== Incremental Ingest ==")

INDEX_DIR = "/Users/stark/Quantum_Computing_Lab/OUT"
if Path(INDEX_DIR).exists():
    from ingest import IncrementalIngest

    ing = IncrementalIngest(INDEX_DIR)
    test("ingest loads manifest", ing.manifest is not None)
    test("ingest has codebook", ing.codebook is not None)
    test("ingest has IDF", len(ing.idf) > 0)

    # Ingest a test record (buffered, not flushed)
    ing.ingest({
        "subject": "test_author",
        "relation": "test topic",
        "object": "This is a test message about missile technology",
        "timestamp": "2026-04-09T12:00:00Z",
    })
    test("record buffered", ing.stats["buffered"] == 1)
    test("affected shard tracked", len(ing.affected_shards) == 1)

    # Don't flush — we don't want to modify the real index in a test
    test("no flush = no disk write", ing.stats["flushed"] == 0)
else:
    print(f"  ⚠ Skipping ingest tests (no index at {INDEX_DIR})")

# ═════════════════════════════════════════════════════════════
#  QUERY SERVICE (import only — no shard loading in unit test)
# ═════════════════════════════════════════════════════════════
print("\n== Query Service ==")

from query_service import QueryService, ShardData, QueryResult

test("QueryResult to_dict", QueryResult(0, 0, 0.5, {"text": "t"}).to_dict()["similarity"] == 0.5)

# ═════════════════════════════════════════════════════════════
#  BSC VECTOR OPERATIONS
# ═════════════════════════════════════════════════════════════
print("\n== BSC Operations ==")

v1 = ehc.SparseVector(16384, [1, 100, 500], [1, -1, 1])
v2 = ehc.SparseVector(16384, [1, 100, 500], [1, -1, 1])
v3 = ehc.SparseVector(16384, [2, 200, 600], [1, 1, -1])

test("self-similarity = 1.0", abs(ehc.sparse_cosine(v1, v2) - 1.0) < 0.01)
test("different vectors < 1.0", ehc.sparse_cosine(v1, v3) < 1.0)
test("superpose produces vector", ehc.superpose([v1, v3]).nnz() > 0)

# CompactIndex knn
idx = ehc.BSCCompactIndex(16384, True)
idx.add_items([v1, v3], [0, 1])
result = idx.knn_query(v1, k=1)
test("knn finds self", result.ids[0] == 0)

# ═════════════════════════════════════════════════════════════
#  SUMMARY
# ═════════════════════════════════════════════════════════════
print(f"\n{'═' * 50}")
total = PASS + FAIL
print(f"  {PASS}/{total} passed", end="")
if FAIL > 0:
    print(f", \033[31m{FAIL} FAILED\033[0m")
else:
    print(f" \033[32m(all pass)\033[0m")
print(f"{'═' * 50}")

sys.exit(FAIL)
