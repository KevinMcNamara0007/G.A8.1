#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════
#  G.A8.1 — Install & Smoke Test
#
#  Builds EHC C++ library for the local OS, installs Python
#  dependencies, and runs a smoke test to verify everything works.
#
#  Expected layout (EHC and G.A8.1 at same level):
#    some_dir/
#      EHC/          ← C++ library (auto-detected)
#      G.A8.1/       ← this directory
#      install.sh    ← this script (or run from G.A8.1/)
#
#  Usage:
#    cd /path/to/G.A8.1 && ./install.sh
#    or: bash /path/to/G.A8.1/install.sh
#
#  Requirements:
#    - Python 3.9+
#    - CMake ≥ 3.18
#    - C++20 compiler (gcc ≥ 10, clang ≥ 12, or Apple Clang)
#    - pip (for Python deps)
# ════════════════════════════════════════════════════════════

set -euo pipefail

# ── Resolve paths (works from any directory) ─────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
A81_DIR="$SCRIPT_DIR"
PARENT_DIR="$(dirname "$A81_DIR")"

# Find EHC — look at same level as G.A8.1
EHC_DIR=""
for candidate in "$PARENT_DIR/EHC" "$A81_DIR/../EHC" "$PARENT_DIR/ehc"; do
    if [ -f "$candidate/CMakeLists.txt" ]; then
        EHC_DIR="$(cd "$candidate" && pwd)"
        break
    fi
done

if [ -z "$EHC_DIR" ]; then
    echo "ERROR: EHC directory not found."
    echo "Expected at: $PARENT_DIR/EHC"
    echo "Make sure EHC/ is at the same level as G.A8.1/"
    exit 1
fi

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
CYAN='\033[0;36m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

PASS="${GREEN}✓${NC}"
FAIL="${RED}✗${NC}"

echo -e "${GREEN}${BOLD}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  G.A8.1 — Install & Smoke Test${NC}"
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════════════${NC}"
echo -e "  G.A8.1:  $A81_DIR"
echo -e "  EHC:     $EHC_DIR"
echo -e "  OS:      $(uname -s) $(uname -m)"
echo -e "  Python:  $(python3 --version 2>&1 | head -1)"
echo -e ""

ERRORS=0

# ── Step 1: Check prerequisites ──────────────────────────
echo -e "${CYAN}[1/5] Checking prerequisites...${NC}"

check_cmd() {
    if command -v "$1" &>/dev/null; then
        echo -e "  $PASS $1: $(command -v "$1")"
    else
        echo -e "  $FAIL $1: NOT FOUND"
        ERRORS=$((ERRORS + 1))
    fi
}

check_cmd python3
check_cmd cmake
check_cmd make

# Check C++ compiler
CXX="${CXX:-}"
if [ -z "$CXX" ]; then
    if command -v g++ &>/dev/null; then
        CXX="g++"
    elif command -v clang++ &>/dev/null; then
        CXX="clang++"
    elif command -v c++ &>/dev/null; then
        CXX="c++"
    fi
fi
if [ -n "$CXX" ]; then
    echo -e "  $PASS C++ compiler: $CXX"
else
    echo -e "  $FAIL C++ compiler: NOT FOUND (need g++ ≥ 10 or clang++ ≥ 12)"
    ERRORS=$((ERRORS + 1))
fi

# Check Python version ≥ 3.9
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 9 ]; then
    echo -e "  $PASS Python $PY_VER"
else
    echo -e "  $FAIL Python $PY_VER (need ≥ 3.9)"
    ERRORS=$((ERRORS + 1))
fi

if [ "$ERRORS" -gt 0 ]; then
    echo -e "\n${RED}Prerequisites failed. Fix the above and re-run.${NC}"
    exit 1
fi

# ── Step 2: Install Python dependencies ──────────────────
echo -e "\n${CYAN}[2/5] Installing Python dependencies...${NC}"

python3 -m pip install --quiet --upgrade pip 2>/dev/null || true

# Core deps (required)
DEPS="numpy"
# Media deps (optional — encode still works without them)
MEDIA_DEPS="Pillow opencv-python"

for dep in $DEPS; do
    if python3 -c "import ${dep}" 2>/dev/null; then
        echo -e "  $PASS $dep (already installed)"
    else
        echo -e "  ${DIM}Installing $dep...${NC}"
        python3 -m pip install --quiet "$dep"
        echo -e "  $PASS $dep"
    fi
done

for dep in $MEDIA_DEPS; do
    mod_name=$(echo "$dep" | tr '-' '_' | tr '[:upper:]' '[:lower:]')
    # opencv-python imports as cv2
    [ "$dep" = "opencv-python" ] && mod_name="cv2"
    [ "$dep" = "Pillow" ] && mod_name="PIL"
    if python3 -c "import ${mod_name}" 2>/dev/null; then
        echo -e "  $PASS $dep (already installed)"
    else
        echo -e "  ${DIM}Installing $dep (optional, for media encoding)...${NC}"
        python3 -m pip install --quiet "$dep" 2>/dev/null && \
            echo -e "  $PASS $dep" || \
            echo -e "  ${DIM}⚠ $dep skipped (media encoding will be disabled)${NC}"
    fi
done

# nanobind (required for EHC build)
if python3 -c "import nanobind" 2>/dev/null; then
    echo -e "  $PASS nanobind (already installed)"
else
    echo -e "  ${DIM}Installing nanobind...${NC}"
    python3 -m pip install --quiet nanobind
    echo -e "  $PASS nanobind"
fi

# ── Step 3: Build EHC ────────────────────────────────────
echo -e "\n${CYAN}[3/5] Building EHC C++ library...${NC}"

EHC_BUILD="$EHC_DIR/build"
EHC_SO=""

# Check if already built and working
EXISTING_SO=$(find "$EHC_BUILD/bindings/python" -name "ehc.cpython-*.so" -o -name "ehc.cpython-*.pyd" 2>/dev/null | head -1)
if [ -n "$EXISTING_SO" ]; then
    # Verify it loads
    if python3 -c "import sys; sys.path.insert(0,'$EHC_BUILD/bindings/python'); import ehc; print(ehc)" 2>/dev/null; then
        echo -e "  $PASS EHC already built and loadable"
        echo -e "  ${DIM}$EXISTING_SO${NC}"
        EHC_SO="$EXISTING_SO"
    else
        echo -e "  ${DIM}Existing build found but won't load — rebuilding...${NC}"
    fi
fi

if [ -z "$EHC_SO" ]; then
    echo -e "  ${DIM}Configuring...${NC}"
    mkdir -p "$EHC_BUILD"
    cd "$EHC_BUILD"

    cmake .. \
        -DCMAKE_BUILD_TYPE=Release \
        -DEHC_BUILD_PYTHON=ON \
        -DCMAKE_CXX_STANDARD=20 \
        ${CXX:+-DCMAKE_CXX_COMPILER=$CXX} \
        > cmake_log.txt 2>&1

    if [ $? -ne 0 ]; then
        echo -e "  $FAIL CMake configuration failed"
        echo -e "  ${DIM}See: $EHC_BUILD/cmake_log.txt${NC}"
        exit 1
    fi

    echo -e "  ${DIM}Compiling ($(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4) cores)...${NC}"
    CORES=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)
    make -j"$CORES" > build_log.txt 2>&1

    if [ $? -ne 0 ]; then
        echo -e "  $FAIL Build failed"
        echo -e "  ${DIM}See: $EHC_BUILD/build_log.txt${NC}"
        exit 1
    fi

    EHC_SO=$(find "$EHC_BUILD/bindings/python" -name "ehc.cpython-*.so" -o -name "ehc.cpython-*.pyd" 2>/dev/null | head -1)
    if [ -z "$EHC_SO" ]; then
        echo -e "  $FAIL Build completed but ehc.so not found"
        exit 1
    fi
    echo -e "  $PASS Built: $EHC_SO"
fi

cd "$A81_DIR"
EHC_PYTHON_DIR="$(dirname "$EHC_SO")"

# ── Step 4: Smoke test EHC ───────────────────────────────
echo -e "\n${CYAN}[4/5] Smoke testing EHC...${NC}"

python3 -c "
import sys
sys.path.insert(0, '$EHC_PYTHON_DIR')
import ehc
errors = 0

# Test 1: SparseVector
try:
    v = ehc.SparseVector(16384, [1, 100, 500], [-1, 1, -1])
    assert v.nnz() == 3
    print('  ✓ SparseVector')
except Exception as e:
    print(f'  ✗ SparseVector: {e}')
    errors += 1

# Test 2: TokenCodebook
try:
    cfg = ehc.CodebookConfig()
    cfg.dim = 16384
    cfg.k = 128
    cfg.seed = 42
    cb = ehc.TokenCodebook(cfg)
    cb.build_from_vocabulary([])
    v = cb.encode_token('test')
    assert v.nnz() == 128
    print('  ✓ TokenCodebook')
except Exception as e:
    print(f'  ✗ TokenCodebook: {e}')
    errors += 1

# Test 3: Superpose
try:
    v1 = cb.encode_token('hello')
    v2 = cb.encode_token('world')
    vs = ehc.superpose([v1, v2])
    assert vs.nnz() > 0
    print('  ✓ superpose')
except Exception as e:
    print(f'  ✗ superpose: {e}')
    errors += 1

# Test 4: BSCCompactIndex
try:
    idx = ehc.BSCCompactIndex(16384, use_sign_scoring=True)
    idx.add_items([v1, v2], [0, 1])
    result = idx.knn_query(v1, k=1)
    assert len(result.ids) > 0
    print('  ✓ BSCCompactIndex')
except Exception as e:
    print(f'  ✗ BSCCompactIndex: {e}')
    errors += 1

# Test 5: BSCLSHIndex
try:
    lsh = ehc.BSCLSHIndex(16384, 128, num_tables=4, hash_size=8, use_multiprobe=True)
    lsh.add_items([v1, v2], [0, 1])
    result = lsh.knn_query(v1, k=1)
    assert len(result.ids) > 0
    print('  ✓ BSCLSHIndex')
except Exception as e:
    print(f'  ✗ BSCLSHIndex: {e}')
    errors += 1

# Test 6: sparse_cosine
try:
    sim = ehc.sparse_cosine(v1, v1)
    assert sim > 0.99
    print('  ✓ sparse_cosine')
except Exception as e:
    print(f'  ✗ sparse_cosine: {e}')
    errors += 1

# Test 7: VisionEncoder (optional)
try:
    if hasattr(ehc, 'VisionEncoder'):
        import numpy as np
        vcfg = ehc.VisionEncoderConfig()
        vcfg.dim = 16384
        ve = ehc.VisionEncoder(vcfg)
        img = np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8)
        vv = ve.encode_rgb(img)
        assert vv.nnz() > 0
        print('  ✓ VisionEncoder')
    else:
        print('  ⚠ VisionEncoder (not available in this build)')
except Exception as e:
    print(f'  ✗ VisionEncoder: {e}')
    errors += 1

# Test 8: LRUCache
try:
    if hasattr(ehc, 'LRUCache'):
        cache = ehc.LRUCache(max_size=100)
        cache.put('key', v1)
        got = cache.get('key')
        assert got is not None
        print('  ✓ LRUCache')
    else:
        print('  ⚠ LRUCache (not available)')
except Exception as e:
    print(f'  ✗ LRUCache: {e}')
    errors += 1

sys.exit(errors)
"
EHC_RESULT=$?

if [ "$EHC_RESULT" -ne 0 ]; then
    echo -e "  ${RED}EHC smoke test failed ($EHC_RESULT errors)${NC}"
    exit 1
fi

# ── Step 5: Smoke test G.A8.1 ────────────────────────────
echo -e "\n${CYAN}[5/5] Smoke testing G.A8.1...${NC}"

python3 -c "
import sys
sys.path.insert(0, '$EHC_PYTHON_DIR')
sys.path.insert(0, '$A81_DIR/decode')
sys.path.insert(0, '$A81_DIR/encode')
sys.path.insert(0, '$A81_DIR')
errors = 0

# Test 1: Config loads
try:
    from config import cfg
    assert cfg.DIM == 16384
    assert cfg.K == 128
    print('  ✓ config.py')
except Exception as e:
    print(f'  ✗ config.py: {e}')
    errors += 1

# Test 2: Hooks load
try:
    from hooks import load_hooks, DEFAULT_HOOKS, HookSet, CleanedQuery
    h = load_hooks()
    assert h.name == 'default'
    assert h.query_cleaner is not None
    print('  ✓ hooks.py')
except Exception as e:
    print(f'  ✗ hooks.py: {e}')
    errors += 1

# Test 3: Default query cleaner works
try:
    cleaned = h.query_cleaner('find all links between Iran and Terror')
    assert 'iran' in cleaned.tokens
    assert 'terror' in cleaned.tokens
    assert 'find' not in cleaned.tokens  # filtered
    print('  ✓ query_cleaner')
except Exception as e:
    print(f'  ✗ query_cleaner: {e}')
    errors += 1

# Test 4: Worker encode imports
try:
    from worker_encode import _tokenize, _select_salient, MAX_SALIENT_TOKENS
    tokens = _tokenize('Iran launched a ballistic missile test')
    assert 'iran' in tokens
    assert 'launched' in tokens
    assert len(tokens) > 0
    print(f'  ✓ worker_encode (MAX_SALIENT_TOKENS={MAX_SALIENT_TOKENS})')
except Exception as e:
    print(f'  ✗ worker_encode: {e}')
    errors += 1

# Test 5: Salience selection
try:
    idf = {'iran': 1.0, 'launched': 2.0, 'ballistic': 5.0, 'missile': 3.0, 'test': 1.5}
    salient = _select_salient(['iran', 'launched', 'ballistic', 'missile', 'test'],
                               idf, max_tokens=3)
    assert 'ballistic' in salient  # highest IDF
    assert len(salient) == 3
    print('  ✓ salience selection')
except Exception as e:
    print(f'  ✗ salience selection: {e}')
    errors += 1

# Test 6: Adaptive gazetteer imports
try:
    from adaptive_gazetteer import AdaptiveGazetteer, Association
    a = Association(term='test', root='query', stability=1.0,
                    last_reinforced=0, reinforcement_count=1, created_at=0)
    assert a.is_alive(now=0)
    print('  ✓ adaptive_gazetteer')
except Exception as e:
    print(f'  ✗ adaptive_gazetteer: {e}')
    errors += 1

# Test 7: QueryService imports (without loading shards)
try:
    from query_service import QueryService, ShardData, QueryResult
    print('  ✓ query_service (imports)')
except Exception as e:
    print(f'  ✗ query_service: {e}')
    errors += 1

sys.exit(errors)
"
A81_RESULT=$?

if [ "$A81_RESULT" -ne 0 ]; then
    echo -e "  ${RED}G.A8.1 smoke test failed ($A81_RESULT errors)${NC}"
    exit 1
fi

# ── Done ─────────────────────────────────────────────────
echo -e ""
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  Install complete${NC}"
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════════════${NC}"
echo -e ""
echo -e "  EHC:     ${GREEN}$EHC_SO${NC}"
echo -e "  G.A8.1:  ${GREEN}$A81_DIR${NC}"
echo -e "  Config:  ${GREEN}$A81_DIR/config.env${NC}"
echo -e ""
echo -e "  ${BOLD}Quick start:${NC}"
echo -e "    ${DIM}# Encode data${NC}"
echo -e "    source $A81_DIR/config.env"
echo -e "    python3 $A81_DIR/encode/encode.py --source data.jsonl --output /encoded --clusters clusters.json"
echo -e ""
echo -e "    ${DIM}# Query from Python${NC}"
echo -e "    from query_service import QueryService"
echo -e "    svc = QueryService('/encoded')"
echo -e "    svc.query('iran missile test', k=10)"
echo -e ""
echo -e "    ${DIM}# With product hooks${NC}"
echo -e "    A81_INDEX_PATH=/encoded ./start.sh"
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════════════${NC}"
