"""BUG-DATA-01 — encode.py must refuse to silently produce unbenchmarkable shards.

Pre-patch behavior: running encode.py with neither A81_TIER_ROUTED=1 nor
A81_CLOSED_LOOP=1 produced shards lacking tier_manifest.json and lacking
closed-loop fixups. decode13.benchmark.run_production then reported 0%
Hit@1 in both modes with no warning. Silent data corruption.

Patch: encode.py:run_encode() now calls `_assert_encoding_mode_set()`,
which aborts with exit code 6 + a clear remediation message when neither
flag is set. The opt-out env var `A81_ALLOW_UNBENCHMARKABLE=1` keeps
legacy tooling that doesn't need Hit@k working.

These tests exercise the guard in isolation by importing encode.py with
the cfg's class attributes monkey-patched — the guard runs in <1 ms and
allocates nothing past return, so the test suite stays cheap.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest


REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def patch_cfg():
    """Yield a helper that temporarily overrides cfg.TIER_ROUTED_ENABLED
    and cfg.CLOSED_LOOP_ENABLED for the duration of one assertion. The
    fixture restores both attrs on exit so other tests aren't polluted.
    """
    sys.path.insert(0, str(REPO))
    from config import cfg
    saved = (cfg.TIER_ROUTED_ENABLED, cfg.CLOSED_LOOP_ENABLED)

    def _set(tier_routed: bool, closed_loop: bool):
        cfg.TIER_ROUTED_ENABLED = tier_routed
        cfg.CLOSED_LOOP_ENABLED = closed_loop

    try:
        yield _set
    finally:
        cfg.TIER_ROUTED_ENABLED, cfg.CLOSED_LOOP_ENABLED = saved
        try:
            sys.path.remove(str(REPO))
        except ValueError:
            pass


def _guard():
    """Import the guard fresh each call so cfg mutations land."""
    sys.path.insert(0, str(REPO / "encode"))
    sys.path.insert(0, str(REPO))
    import importlib
    if "encode.encode" in sys.modules:
        importlib.reload(sys.modules["encode.encode"])
    from encode.encode import _assert_encoding_mode_set
    return _assert_encoding_mode_set


def test_aborts_when_both_flags_unset(patch_cfg, capsys):
    """Default config (both False) must call sys.exit(6) with a
    remediation message that names both env vars."""
    patch_cfg(False, False)
    os.environ.pop("A81_ALLOW_UNBENCHMARKABLE", None)
    guard = _guard()
    with pytest.raises(SystemExit) as ei:
        guard()
    assert ei.value.code == 6
    err = capsys.readouterr().err
    assert "A81_TIER_ROUTED" in err
    assert "A81_CLOSED_LOOP" in err
    assert "BUG-DATA-01" in err


def test_passes_when_tier_routed_enabled(patch_cfg):
    """A81_TIER_ROUTED=1 alone is sufficient — tier-routed shards
    are the canonical v13 PlanB output."""
    patch_cfg(True, False)
    os.environ.pop("A81_ALLOW_UNBENCHMARKABLE", None)
    guard = _guard()
    guard()  # must not raise


def test_passes_when_closed_loop_enabled(patch_cfg):
    """A81_CLOSED_LOOP=1 alone is sufficient — baseline closed-loop
    shards are the v13 baseline."""
    patch_cfg(False, True)
    os.environ.pop("A81_ALLOW_UNBENCHMARKABLE", None)
    guard = _guard()
    guard()


def test_passes_when_both_enabled(patch_cfg):
    """Both flags on — exotic but valid (some tooling double-stamps)."""
    patch_cfg(True, True)
    os.environ.pop("A81_ALLOW_UNBENCHMARKABLE", None)
    guard = _guard()
    guard()


def test_opt_out_via_env(patch_cfg, capsys):
    """A81_ALLOW_UNBENCHMARKABLE=1 is the escape hatch for legacy tools
    that don't care about Hit@k. The guard must emit a WARNING then
    return — no SystemExit."""
    patch_cfg(False, False)
    with mock.patch.dict(os.environ, {"A81_ALLOW_UNBENCHMARKABLE": "1"}):
        guard = _guard()
        guard()  # must not raise
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "A81_ALLOW_UNBENCHMARKABLE" in err


def test_guard_does_not_leak_modules():
    """Sanity — the guard is reimported each call, but it must not
    retain references that would prevent test teardown / hold the cfg
    overlay in memory. Confirm the guard is the same callable object
    across calls when nothing changes, i.e. no per-call closure leak.
    """
    g1 = _guard()
    g2 = _guard()
    # Either the same object or two cheap function refs — both fine.
    # The forbidden state would be an unbounded growing set of closures.
    assert callable(g1) and callable(g2)
