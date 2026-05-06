#!/usr/bin/env bash
# ============================================================================
# build_eh.sh — Build EHC (Entangled Halo C++) for the local OS / arch.
#
#   Usage:
#     ./build_eh.sh                     # release build, install bindings
#     ./build_eh.sh --debug             # debug build (asserts on, -O0 -g)
#     ./build_eh.sh --no-bindings       # skip pip install of nanobind wheel
#     ./build_eh.sh --tests             # also build EHC unit/parity tests
#     ./build_eh.sh --clean             # rm -rf the per-platform build dir first
#
#   Environment overrides:
#     EHC_DIR=/path/to/EHC              # default: ../EHC relative to G.A8.1
#     CMAKE_GENERATOR=Ninja|Unix\ Makefiles
#     CMAKE_INSTALL_PREFIX=/some/path   # default: $EHC_DIR/install
#
# Why this script and not just plain CMake:
#   - One command for the common case (release + bindings).
#   - Per-platform build dirs (build-darwin-arm64, build-linux-x86_64) so
#     macOS dev and Linux CI/edge builds don't clobber each other on a
#     shared filesystem (NFS, syncthing, etc.).
#   - Picks Ninja when available (faster, cleaner output), falls back to
#     Unix Makefiles. CMake's generator default differs by platform.
#   - SIMD detection is intentionally NOT done here — EHC's CompilerFlags.cmake
#     already runs check_cxx_compiler_flag for AVX2 / AVX-512 / NEON. Adding
#     a second detection layer would lie about what the compiler actually
#     accepts.
# ============================================================================

set -euo pipefail

# ── Args ────────────────────────────────────────────────────────
BUILD_TYPE="Release"
WITH_BINDINGS=1
WITH_TESTS=0
DO_CLEAN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --debug)        BUILD_TYPE="Debug"; shift ;;
    --no-bindings)  WITH_BINDINGS=0; shift ;;
    --tests)        WITH_TESTS=1; shift ;;
    --clean)        DO_CLEAN=1; shift ;;
    -h|--help)
      sed -n '4,25p' "$0"; exit 0 ;;
    *)              echo "unknown arg: $1" >&2; exit 64 ;;
  esac
done

# ── Locate EHC ──────────────────────────────────────────────────
G_A81_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EHC_DIR="${EHC_DIR:-$G_A81_DIR/../EHC}"
if [[ ! -f "$EHC_DIR/CMakeLists.txt" ]]; then
  echo "error: EHC not found at $EHC_DIR (override with EHC_DIR=...)" >&2
  exit 1
fi
EHC_DIR="$(cd "$EHC_DIR" && pwd)"

# ── Detect OS / arch ────────────────────────────────────────────
OS_RAW="$(uname -s)"
ARCH_RAW="$(uname -m)"
case "$OS_RAW" in
  Darwin)  OS="darwin" ;;
  Linux)   OS="linux"  ;;
  *)       echo "warning: unsupported OS $OS_RAW; proceeding" >&2; OS="$OS_RAW" ;;
esac
case "$ARCH_RAW" in
  x86_64|amd64)  ARCH="x86_64" ;;
  arm64|aarch64) ARCH="arm64"  ;;
  *)             echo "warning: unsupported arch $ARCH_RAW; proceeding" >&2; ARCH="$ARCH_RAW" ;;
esac

BUILD_DIR="$EHC_DIR/build-${OS}-${ARCH}"
INSTALL_PREFIX="${CMAKE_INSTALL_PREFIX:-$EHC_DIR/install/${OS}-${ARCH}}"

# ── Pick generator ──────────────────────────────────────────────
if [[ -n "${CMAKE_GENERATOR:-}" ]]; then
  GEN="$CMAKE_GENERATOR"
elif command -v ninja >/dev/null 2>&1; then
  GEN="Ninja"
else
  GEN="Unix Makefiles"
fi

# ── Plan ────────────────────────────────────────────────────────
echo "[plan] EHC      = $EHC_DIR"
echo "       build    = $BUILD_DIR"
echo "       install  = $INSTALL_PREFIX"
echo "       host     = ${OS}/${ARCH}"
echo "       type     = $BUILD_TYPE"
echo "       generator= $GEN"
echo "       bindings = $([[ $WITH_BINDINGS == 1 ]] && echo yes || echo no)"
echo "       tests    = $([[ $WITH_TESTS    == 1 ]] && echo yes || echo no)"

# ── Optional clean ──────────────────────────────────────────────
if [[ $DO_CLEAN == 1 && -d "$BUILD_DIR" ]]; then
  echo "[clean] removing $BUILD_DIR"
  rm -rf "$BUILD_DIR"
fi

# ── Configure ───────────────────────────────────────────────────
mkdir -p "$BUILD_DIR"
CMAKE_FLAGS=(
  -S "$EHC_DIR"
  -B "$BUILD_DIR"
  -G "$GEN"
  -DCMAKE_BUILD_TYPE="$BUILD_TYPE"
  -DCMAKE_INSTALL_PREFIX="$INSTALL_PREFIX"
)
if [[ $WITH_BINDINGS == 1 ]]; then
  CMAKE_FLAGS+=( -DEHC_BUILD_PYTHON=ON )
fi
if [[ $WITH_TESTS == 1 ]]; then
  CMAKE_FLAGS+=( -DEHC_BUILD_TESTS=ON )
fi

# Apple Silicon: pin arch so universal-binary toolchains don't go fat-binary.
if [[ "$OS" == "darwin" ]]; then
  case "$ARCH" in
    arm64)  CMAKE_FLAGS+=( -DCMAKE_OSX_ARCHITECTURES=arm64 ) ;;
    x86_64) CMAKE_FLAGS+=( -DCMAKE_OSX_ARCHITECTURES=x86_64 ) ;;
  esac
fi

echo "[configure] cmake ${CMAKE_FLAGS[*]}"
cmake "${CMAKE_FLAGS[@]}"

# ── Build ───────────────────────────────────────────────────────
JOBS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"
echo "[build] cmake --build $BUILD_DIR -j $JOBS"
cmake --build "$BUILD_DIR" -j "$JOBS"

# ── Install (CMake target — installs headers + static libs) ─────
if cmake --build "$BUILD_DIR" --target install -j "$JOBS" 2>/dev/null; then
  echo "[install] $INSTALL_PREFIX"
else
  echo "[install] skipped (no install target or EHC_INSTALL=OFF)"
fi

# ── Python bindings via pip (nanobind wheel) ────────────────────
if [[ $WITH_BINDINGS == 1 ]]; then
  PY_BINDINGS="$EHC_DIR/bindings/python"
  if [[ -f "$PY_BINDINGS/pyproject.toml" ]]; then
    echo "[pip] installing $PY_BINDINGS"
    python3 -m pip install --upgrade --user "$PY_BINDINGS"
  else
    echo "[pip] skipped (no pyproject.toml at $PY_BINDINGS)"
  fi
fi

echo "✓ build_eh: ${OS}/${ARCH} ${BUILD_TYPE} build complete"
