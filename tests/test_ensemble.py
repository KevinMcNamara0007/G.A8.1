"""Ensemble encode + query path — end-to-end smoke pins.

Covers:
  - encode_unstructured.encode_ensemble writes ensemble.json + per-seed
    structural_v13_seedN/ dirs + shared corpus.jsonl
  - decode.query_dispatch.QueryService auto-detects ensemble.json and
    instantiates decode.query_ensemble.EnsembleQueryService
  - All three fusion strategies (merge_top10, max_top1, sum_sim) return
    well-formed result dicts
  - fusion= kwarg overrides the manifest default per call
  - A81_ENSEMBLE_FUSION env override is honored at construction time
  - Layout precedence: ensemble.json wins over a stale structural_v13/

These tests use a 200-record tiny corpus + 2 seeds so each test runs in
seconds. Hit@k quality is *not* asserted (codebook rotation makes single
queries flaky at this scale); we pin contract shape only.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from encode.encode_unstructured import encode_ensemble       # noqa: E402
from encode.encode_triples import encode_ensemble as encode_ensemble_triples  # noqa: E402


SEEDS = [42, 99]   # spread enough to produce different codebooks
DIM, K = 512, 23   # smallest D that still produces meaningful retrieval
MAX_SLOTS_LAW = 10  # round(2·√23) — used when lift_for_p99=False
P99_LIFT = 17       # used when lift_for_p99=True


@pytest.fixture(scope="module")
def tiny_corpus(tmp_path_factory):
    """200 records of distinct short sentences. Returns the source path."""
    d = tmp_path_factory.mktemp("ensemble_src")
    src = d / "source.jsonl"
    sentences = [
        "the cat sat on the mat",
        "iran missile strike attack",
        "the dog ran in the park",
        "khamenei speech tehran square",
        "nuclear program iran sanctions",
        "stocks rallied on the news",
        "trump visits israel meeting",
        "hezbollah statement on lebanon",
        "uranium enrichment monitor report",
        "saudi arabia oil price drop",
    ]
    with open(src, "w") as f:
        for i in range(200):
            f.write(json.dumps({
                "doc_id": i,
                "text": f"record {i:03d}: " + sentences[i % len(sentences)],
            }) + "\n")
    return src


@pytest.fixture(scope="module")
def ensemble_dir(tmp_path_factory, tiny_corpus):
    out = tmp_path_factory.mktemp("ensemble_out")
    encode_ensemble(
        source=tiny_corpus,
        output=out,
        dim=DIM, k=K,
        p99_atoms=10,                    # below the law value at k=23
        workers=2, hebbian=True,
        lift_for_p99=False,
        seeds=SEEDS,
    )
    return out


def _open_qs(path, **kw):
    from decode import QueryService
    return QueryService(str(path), **kw)


# ── ensemble encode contract ─────────────────────────────────────────────

def test_manifest_written(ensemble_dir):
    manifest_path = ensemble_dir / "ensemble.json"
    assert manifest_path.exists(), "ensemble.json must be at the root"
    m = json.loads(manifest_path.read_text())
    assert m["seeds"] == SEEDS
    assert m["dim"] == DIM
    assert m["k"] == K
    assert m["max_slots"] == MAX_SLOTS_LAW
    assert m["fusion"] == "merge_top10"
    assert m["n_records"] == 200
    assert m["lift_for_p99"] is False


def test_per_seed_pipe_dirs_exist(ensemble_dir):
    for s in SEEDS:
        pdir = ensemble_dir / f"structural_v13_seed{s}"
        assert (pdir / "structural_v13.cfg").exists(), \
            f"missing cfg for seed={s}"
        assert (pdir / "lsh.bin").exists(), \
            f"missing lsh.bin for seed={s}"


def test_corpus_jsonl_shared(ensemble_dir):
    # One corpus.jsonl at root, NOT under each seed dir.
    assert (ensemble_dir / "corpus.jsonl").exists()
    for s in SEEDS:
        assert not (ensemble_dir / f"structural_v13_seed{s}" / "corpus.jsonl").exists()


# ── dispatcher layout detection ──────────────────────────────────────────

def test_dispatcher_detects_ensemble(ensemble_dir):
    qs = _open_qs(ensemble_dir)
    try:
        assert qs.layout == "ensemble"
        stats = qs.stats
        assert stats["layout"] == "ensemble"
        assert stats["backend"] == "ensemble"
        assert stats["n_seeds"] == len(SEEDS)
        assert stats["seeds"] == SEEDS
        assert stats["fusion"] == "merge_top10"
    finally:
        qs.close()


def test_ensemble_wins_over_stale_flat(ensemble_dir):
    """A leftover structural_v13/ at the root must NOT trigger flat dispatch."""
    stale = ensemble_dir / "structural_v13"
    stale.mkdir(exist_ok=False)
    # Make it look superficially flat-like but malformed; if we reach the
    # flat backend, it'll error. Ensemble takes precedence → no error.
    (stale / "structural_v13.cfg").write_text("# stale")
    try:
        qs = _open_qs(ensemble_dir)
        try:
            assert qs.layout == "ensemble", \
                "ensemble.json must take precedence over structural_v13/"
        finally:
            qs.close()
    finally:
        shutil.rmtree(stale)


# ── query + fusion contract ──────────────────────────────────────────────

@pytest.mark.parametrize("fusion", ["merge_top10", "max_top1", "sum_sim"])
def test_query_shape_each_fusion(ensemble_dir, fusion):
    qs = _open_qs(ensemble_dir, fusion=fusion)
    try:
        assert qs.stats["fusion"] == fusion
        res = qs.query(text="iran missile", k=5)
        assert isinstance(res, dict)
        assert set(res.keys()) >= {"results", "confidence", "audit"}
        assert isinstance(res["results"], list)
        assert len(res["results"]) <= 5
        for h in res["results"]:
            assert "id" in h
            assert "similarity" in h
        audit = res["audit"]
        assert audit["n_backends"] == len(SEEDS)
        assert audit["seeds"] == SEEDS
        assert audit["strategy"] == f"ensemble.{fusion}"
    finally:
        qs.close()


def test_per_query_fusion_override(ensemble_dir):
    """Pass fusion= to query() without changing the configured default."""
    qs = _open_qs(ensemble_dir)   # default merge_top10
    try:
        r_default = qs.query(text="iran", k=5)
        r_override = qs.query(text="iran", k=5, fusion="sum_sim")
        assert r_default["audit"]["strategy"] == "ensemble.merge_top10"
        assert r_override["audit"]["strategy"] == "ensemble.sum_sim"
        # The configured fusion on the service is unchanged.
        assert qs.stats["fusion"] == "merge_top10"
    finally:
        qs.close()


def test_env_override(monkeypatch, ensemble_dir):
    monkeypatch.setenv("A81_ENSEMBLE_FUSION", "max_top1")
    qs = _open_qs(ensemble_dir)
    try:
        assert qs.stats["fusion"] == "max_top1"
    finally:
        qs.close()


def test_unknown_fusion_rejected(ensemble_dir):
    with pytest.raises(ValueError, match="unknown ensemble fusion"):
        _open_qs(ensemble_dir, fusion="bogus_strategy")


# ── lift_for_p99 plumbing through encode_ensemble ────────────────────────

def test_lift_for_p99_raises_max_slots(tmp_path, tiny_corpus):
    out = tmp_path / "lifted"
    encode_ensemble(
        source=tiny_corpus, output=out,
        dim=DIM, k=K,
        p99_atoms=P99_LIFT,
        workers=2, hebbian=True,
        lift_for_p99=True,
        seeds=SEEDS,
    )
    m = json.loads((out / "ensemble.json").read_text())
    assert m["lift_for_p99"] is True
    # Under lift, max_slots = max(round(2·√k), p99). With p99=17 > 10 (law),
    # the lift wins → max_slots should be 17.
    assert m["max_slots"] == P99_LIFT


# ── encode_triples ensemble path ─────────────────────────────────────────
#
# The SRO encoder shares the encode_unstructured layout (ensemble.json +
# per-seed structural_v13_seedN/ + shared corpus.jsonl) so the same
# EnsembleQueryService backs it. Quick smoke pin: encode + dispatch +
# query shape. Fusion shape is already covered above for the dispatcher
# path — repeating it here would be redundant.

@pytest.fixture(scope="module")
def tiny_triples(tmp_path_factory):
    d = tmp_path_factory.mktemp("triples_src")
    src = d / "triples.jsonl"
    triples = [
        ("paris", "capital_of", "france"),
        ("london", "capital_of", "uk"),
        ("tokyo", "capital_of", "japan"),
        ("nile", "located_in", "egypt"),
        ("amazon", "located_in", "brazil"),
    ]
    with open(src, "w") as f:
        for i in range(200):
            s, r, o = triples[i % len(triples)]
            f.write(json.dumps({
                "subject": f"{s}_{i:03d}",
                "relation": r,
                "object": o,
            }) + "\n")
    return src


@pytest.fixture(scope="module")
def triples_ensemble_dir(tmp_path_factory, tiny_triples):
    out = tmp_path_factory.mktemp("triples_out")
    encode_ensemble_triples(
        source=tiny_triples,
        output=out,
        dim=DIM, k=K,
        p99_atoms=2,             # SRO triples regime
        workers=2,
        lift_for_p99=False,
        seeds=SEEDS,
    )
    return out


def test_triples_manifest_records_encoder(triples_ensemble_dir):
    m = json.loads((triples_ensemble_dir / "ensemble.json").read_text())
    assert m["encoder"] == "encode_triples"
    assert m["seeds"] == SEEDS
    assert m["dim"] == DIM and m["k"] == K
    assert m["n_records"] == 200


def test_triples_per_seed_pipe_dirs_exist(triples_ensemble_dir):
    for s in SEEDS:
        pdir = triples_ensemble_dir / f"structural_v13_seed{s}"
        assert (pdir / "structural_v13.cfg").exists()
        assert (pdir / "lsh.bin").exists()


def test_triples_dispatcher_routes_to_ensemble(triples_ensemble_dir):
    qs = _open_qs(triples_ensemble_dir)
    try:
        assert qs.layout == "ensemble"
        res = qs.query(text="paris capital_of", k=3)
        assert isinstance(res, dict)
        assert "results" in res
        assert res["audit"]["n_backends"] == len(SEEDS)
    finally:
        qs.close()
