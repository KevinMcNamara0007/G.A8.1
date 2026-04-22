"""decode13 test runner.

Runs each test module in sequence, reports per-module pass/fail totals,
and exits non-zero on any failure. No external test framework dependency
(pytest etc.) — each test file is its own runner.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
TESTS = [
    HERE / "tests" / "test_tier_router.py",
    HERE / "tests" / "test_tier_manifest.py",
    HERE / "tests" / "test_structured_atomic.py",
    HERE / "tests" / "test_extracted_triple.py",
    HERE / "tests" / "test_end_to_end.py",
    # v13.1 corpus profiler (PlanC)
    HERE / "tests" / "test_profile_schema.py",
    HERE / "tests" / "test_profile_elbow.py",
    HERE / "tests" / "test_profile_manifest.py",
]


def main() -> int:
    overall_fail = 0
    t0 = time.perf_counter()
    for path in TESTS:
        print(f"\n═══ {path.name} ═══")
        r = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(HERE),
            capture_output=True, text=True,
        )
        sys.stdout.write(r.stdout)
        if r.stderr:
            sys.stderr.write(r.stderr)
        if r.returncode != 0:
            overall_fail += 1
    elapsed = time.perf_counter() - t0
    print(f"\n{'═' * 60}")
    status = "FAIL" if overall_fail else "PASS"
    print(f"decode13 tests: {status} ({len(TESTS) - overall_fail}/{len(TESTS)} files) "
          f"in {elapsed:.1f}s")
    return 1 if overall_fail else 0


if __name__ == "__main__":
    sys.exit(main())
