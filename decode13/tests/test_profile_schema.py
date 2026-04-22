"""CorpusProfile schema + source_hash tests."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from decode13.profile import (  # noqa: E402
    CorpusProfile, PROFILE_VERSION, ProfileValidationError,
    compute_source_hash, load_profile, resolve_sample_size, save_profile,
)


def test_profile_roundtrip():
    p = CorpusProfile(
        recommended_dim=8192, recommended_k=90,
        structural_scan={"total_records": 1000},
    )
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "corpus_profile.json"
        save_profile(p, path)
        loaded = load_profile(path)
    assert loaded.recommended_dim == 8192
    assert loaded.recommended_k == 90
    assert loaded.profile_version == PROFILE_VERSION


def test_profile_version_mismatch_raises():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "corpus_profile.json"
        with open(path, "w") as f:
            json.dump({"profile_version": "profile-v999"}, f)
        try:
            load_profile(path)
        except ProfileValidationError:
            return
        assert False, "expected ProfileValidationError"


def test_dimensions_axis_format():
    p = CorpusProfile(recommended_dim=16384, recommended_k=128)
    assert p.dimensions_axis() == "D16384:k128"
    p2 = CorpusProfile(recommended_dim=4096, recommended_k=64)
    assert p2.dimensions_axis() == "D4096:k64"


def test_source_hash_stable_unchanged_file():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "corpus.jsonl"
        with open(path, "wb") as f:
            f.write(b'{"a":1}\n' * 1000)
        h1 = compute_source_hash(str(path), 1000)
        h2 = compute_source_hash(str(path), 1000)
    assert h1 == h2


def test_source_hash_detects_content_change():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "corpus.jsonl"
        with open(path, "wb") as f:
            f.write(b'{"a":1}\n' * 1000)
        h1 = compute_source_hash(str(path), 1000)
        # Edit a byte mid-file.
        with open(path, "r+b") as f:
            f.seek(500)
            f.write(b'Z')
        h2 = compute_source_hash(str(path), 1000)
    assert h1 != h2, "source_hash should detect mid-file edit"


def test_source_hash_detects_size_change():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "corpus.jsonl"
        with open(path, "wb") as f:
            f.write(b'{"a":1}\n' * 1000)
        h1 = compute_source_hash(str(path), 1000)
        with open(path, "ab") as f:
            f.write(b'{"a":2}\n')
        h2 = compute_source_hash(str(path), 1001)
    assert h1 != h2


def test_resolve_sample_size_scaling():
    # floor
    assert resolve_sample_size(0) == 10_000
    assert resolve_sample_size(100) == 10_000
    # 1M records → 10K (floor still wins)
    assert resolve_sample_size(1_000_000) == 10_000
    # 2M records → 10K (floor still)
    assert resolve_sample_size(2_000_000) == 10_000
    # 5M → 25K
    assert resolve_sample_size(5_000_000) == 25_000
    # 10M → 50K (cap hit)
    assert resolve_sample_size(10_000_000) == 50_000
    # 21M → 50K (cap)
    assert resolve_sample_size(21_200_000) == 50_000


if __name__ == "__main__":
    tests = [
        test_profile_roundtrip,
        test_profile_version_mismatch_raises,
        test_dimensions_axis_format,
        test_source_hash_stable_unchanged_file,
        test_source_hash_detects_content_change,
        test_source_hash_detects_size_change,
        test_resolve_sample_size_scaling,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
    print(f"\ntest_profile_schema: {'FAIL' if failed else 'PASS'} "
          f"({len(tests) - failed}/{len(tests)})")
    sys.exit(1 if failed else 0)
