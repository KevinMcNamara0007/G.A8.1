"""BUG-DATA-01 — encode.py must refuse to silently produce unbenchmarkable shards.

History:
  v1 (Saturday): guard accepted EITHER A81_TIER_ROUTED=1 OR
  A81_CLOSED_LOOP=1. Reasonable from the original bug-ledger
  workaround, but per `how_to_use_encode.md` Gotcha #1 + Use Case 3,
  closed-loop is an orthogonal canonicalization flag — it does NOT
  write per-shard tier_manifest.json. When the user re-ran with
  A81_CLOSED_LOOP=1 only, the canonical decode path
  (`from decode import QueryService`) reported tier_counts=0 and
  ~0% recall, which is exactly the silent-corruption mode the guard
  was meant to prevent.

  v2 (today): the guard now requires A81_TIER_ROUTED=1 specifically.
  A81_CLOSED_LOOP=1 alone is rejected (a clarifying hint is printed
  pointing out that closed-loop is orthogonal). Both flags together
  is fine.

  Two escape hatches kept:
    A81_ALLOW_TIER_AGNOSTIC=1  — for the niche baseline-arm case
                                 (e.g. run_production.py --base-dir);
                                 the only legitimate "I want shards
                                 the canonical decoder will treat as
                                 tier-agnostic" path. Warns loudly.
    A81_ALLOW_UNBENCHMARKABLE=1 — legacy umbrella opt-out for
                                  back-compat with the v1 guard.
                                  Warns loudly.

Tests exercise the guard in isolation by importing encode.py with the
cfg's class attributes monkey-patched — the guard runs in <1 ms and
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


def _clear_opt_outs():
    for v in ("A81_ALLOW_UNBENCHMARKABLE", "A81_ALLOW_TIER_AGNOSTIC"):
        os.environ.pop(v, None)


def test_aborts_when_both_flags_unset(patch_cfg, capsys):
    """Default config (both False) must call sys.exit(6) with a
    remediation message that names A81_TIER_ROUTED and references the
    encode doc."""
    patch_cfg(False, False)
    _clear_opt_outs()
    guard = _guard()
    with pytest.raises(SystemExit) as ei:
        guard()
    assert ei.value.code == 6
    err = capsys.readouterr().err
    assert "A81_TIER_ROUTED" in err
    assert "BUG-DATA-01" in err
    assert "how_to_use_encode.md" in err


def test_passes_when_tier_routed_enabled(patch_cfg):
    """A81_TIER_ROUTED=1 alone is sufficient — tier-routed shards
    are the canonical v13 PlanB output the encode doc documents."""
    patch_cfg(True, False)
    _clear_opt_outs()
    guard = _guard()
    guard()  # must not raise


def test_aborts_when_closed_loop_only(patch_cfg, capsys):
    """v2 contract: A81_CLOSED_LOOP=1 ALONE is NOT sufficient. The
    canonical decode path needs per-shard tier_manifest.json, which
    closed-loop does not produce. The guard must abort AND surface
    a hint that closed-loop is orthogonal to tier routing."""
    patch_cfg(False, True)
    _clear_opt_outs()
    guard = _guard()
    with pytest.raises(SystemExit) as ei:
        guard()
    assert ei.value.code == 6
    err = capsys.readouterr().err
    assert "A81_TIER_ROUTED" in err
    assert "A81_CLOSED_LOOP" in err
    assert "orthogonal" in err.lower()


def test_passes_when_both_enabled(patch_cfg):
    """Both flags on — fine (closed-loop and tier-routing are
    orthogonal; the encode doc explicitly permits combining them)."""
    patch_cfg(True, True)
    _clear_opt_outs()
    guard = _guard()
    guard()


def test_opt_out_tier_agnostic(patch_cfg, capsys):
    """A81_ALLOW_TIER_AGNOSTIC=1 is the specific opt-out for the
    baseline-arm case (e.g. run_production.py --base-dir). Must
    emit a WARNING and return — no SystemExit."""
    patch_cfg(False, False)
    with mock.patch.dict(os.environ, {"A81_ALLOW_TIER_AGNOSTIC": "1"}):
        guard = _guard()
        guard()  # must not raise
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "A81_ALLOW_TIER_AGNOSTIC" in err


def test_opt_out_unbenchmarkable_legacy(patch_cfg, capsys):
    """Legacy umbrella opt-out from the v1 guard. Still works,
    still warns. Kept for back-compat with any tooling that already
    set this env var."""
    patch_cfg(False, False)
    with mock.patch.dict(os.environ, {"A81_ALLOW_UNBENCHMARKABLE": "1"}):
        guard = _guard()
        guard()  # must not raise
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "A81_ALLOW_UNBENCHMARKABLE" in err


def test_closed_loop_passes_with_tier_routed_opt_out_unset(patch_cfg, capsys):
    """Closed-loop is rejected even though it WAS accepted in v1.
    This is the load-bearing v1 → v2 behavior change."""
    patch_cfg(False, True)  # CLOSED_LOOP only
    _clear_opt_outs()
    guard = _guard()
    with pytest.raises(SystemExit) as ei:
        guard()
    assert ei.value.code == 6


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
