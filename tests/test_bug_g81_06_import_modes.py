"""BUG-G81-06 — encode_triples.py must work in both invocation forms.

Pre-patch state:
    python -m encode.encode_triples ...   # WORKED (relative imports OK)
    python encode/encode_triples.py ...   # FAILED at line 156:
        ImportError: attempted relative import with no known parent package

Patch: switch the in-function imports to absolute (`from encode._autotune`
/ `from encode._io`). `sys.path.insert(0, _HERE.parent)` at the top of
the file makes the `encode` package importable in either form.

These tests are subprocess-based — they spawn a real Python with each
invocation form and confirm the import phase doesn't raise. We pass a
no-op argument set that fails at argparse (which only happens AFTER all
top-level imports execute), so an ImportError regression would be the
visible failure mode, distinct from the expected argparse exit.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]   # G.A8.1/
ENCODE_DIR = REPO / "encode"


def _env_no_overlays():
    """Return an env minus the overlay-loading vars so the subprocess
    doesn't read /etc/A8.1 or modality overlays — keeps tests hermetic
    and prevents accidental memory blow-ups via large overlay loads."""
    env = dict(os.environ)
    for k in list(env.keys()):
        if k.startswith("A81_MODALITY") or k.startswith("A81_ROLE"):
            env.pop(k, None)
    return env


def _run(cmd, cwd):
    """Subprocess helper — short timeout, no stdin, capture output.

    The subprocess is short-lived (just argparse to failure). We do NOT
    inherit the parent's stdin and we time out at 30s so a stuck import
    can't OOM the test runner.
    """
    return subprocess.run(
        cmd, cwd=str(cwd),
        env=_env_no_overlays(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )


def test_encode_triples_module_mode_imports():
    """`python -m encode.encode_triples --help` must reach argparse, not
    raise ImportError. The relative→absolute import patch keeps this
    invocation form working unchanged."""
    r = _run([sys.executable, "-m", "encode.encode_triples", "--help"],
             cwd=REPO)
    combined = r.stdout.decode("utf-8", "replace") + \
               r.stderr.decode("utf-8", "replace")
    assert "ImportError" not in combined, combined
    assert "ModuleNotFoundError" not in combined, combined
    # argparse --help exits 0 after printing usage.
    assert r.returncode == 0, combined


def test_encode_triples_script_mode_imports():
    """`python encode/encode_triples.py --help` previously died at the
    in-function `from ._autotune import …` line with
        ImportError: attempted relative import with no known parent package
    Post-patch the import resolves via `encode._autotune`."""
    r = _run([sys.executable, str(ENCODE_DIR / "encode_triples.py"), "--help"],
             cwd=REPO)
    combined = r.stdout.decode("utf-8", "replace") + \
               r.stderr.decode("utf-8", "replace")
    assert "ImportError" not in combined, combined
    assert "ModuleNotFoundError" not in combined, combined
    assert "attempted relative import" not in combined, combined
    assert r.returncode == 0, combined


def test_encode_triples_in_function_imports_resolve():
    """Force the lazy imports inside _stream_triples / _count_records /
    _quick_p99_atoms_sro / encode_full to actually evaluate.

    Importing the module is not enough: the patched `from encode._io` /
    `from encode._autotune` lines live inside function bodies and only
    bind when the function is called. We invoke each in a context that
    fails *after* the import (path doesn't exist), so an ImportError
    regression surfaces distinctly from a FileNotFoundError.
    """
    import importlib

    sys.path.insert(0, str(REPO))
    try:
        mod = importlib.import_module("encode.encode_triples")
        # _stream_triples needs the body to run; iterate one record.
        with pytest.raises((FileNotFoundError, OSError)):
            next(iter(mod._stream_triples(Path("/nonexistent.jsonl"))))
        with pytest.raises((FileNotFoundError, OSError)):
            mod._count_records(Path("/nonexistent.jsonl"))
        with pytest.raises((FileNotFoundError, OSError)):
            mod._quick_p99_atoms_sro(Path("/nonexistent.jsonl"))
    finally:
        # Don't leak sys.path modifications between tests.
        try:
            sys.path.remove(str(REPO))
        except ValueError:
            pass


@pytest.mark.parametrize("invocation", ["module", "script"])
def test_no_orphaned_relative_imports(invocation):
    """Guard test — scan the source for remaining `from ._…` lines that
    would re-break the script-mode invocation.

    Pure file read (~30 KB), no allocations retained.
    """
    src = (ENCODE_DIR / "encode_triples.py").read_text(encoding="utf-8")
    # Allow `from ._x import` only inside comments/docstrings.
    offending = []
    for ln, line in enumerate(src.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if "from ._" in stripped and "import" in stripped:
            offending.append((ln, line))
    assert not offending, (
        f"Relative imports re-introduced in encode_triples.py "
        f"({invocation} mode would fail):\n" +
        "\n".join(f"  L{ln}: {line}" for ln, line in offending)
    )
