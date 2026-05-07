#!/usr/bin/env bash
#
# G.A8.1 modality-3 thin-client setup
# ===================================
# Installs prerequisites (with consent), clones EHC + G.A8.1 at known
# good refs, builds EHC's Python module against the local toolchain,
# and writes a sourceable env file the operator can use to invoke
# decode13.QueryService against a corpus pulled from an encoding
# server.
#
# Supported platforms: Linux (apt|dnf|pacman), macOS (brew). Windows
# (MSYS2) is stubbed — see scripts/INSTALL.md for the manual path.
#
# Usage:
#   ./client.sh [build|check|help] [--prefix DIR] [--ref SHA] [--force]
#               [--no-install] [--ehc-repo URL] [--g81-repo URL]

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────
DEFAULT_PREFIX="${HOME}/letthegamesbegin"
DEFAULT_EHC_REPO="https://github.com/KevinMcNamara0007/EHC.git"
DEFAULT_G81_REPO="https://github.com/KevinMcNamara0007/G.A8.1.git"
DEFAULT_REF="main"
PYTHON_MIN="3.10"
PYTHON_MAX="3.14"

PREFIX="$DEFAULT_PREFIX"
EHC_REPO="$DEFAULT_EHC_REPO"
G81_REPO="$DEFAULT_G81_REPO"
REF="$DEFAULT_REF"
FORCE=0
NO_INSTALL=0
SUBCOMMAND="build"

# ── Pretty output ───────────────────────────────────────────────────
if [[ -t 1 ]]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'
    GRN=$'\033[32m'; YLW=$'\033[33m'; CYA=$'\033[36m'; OFF=$'\033[0m'
else
    BOLD=""; DIM=""; RED=""; GRN=""; YLW=""; CYA=""; OFF=""
fi
log()   { printf "%s[client.sh]%s %s\n" "$CYA" "$OFF" "$*"; }
ok()    { printf "%s[ok]%s       %s\n" "$GRN" "$OFF" "$*"; }
warn()  { printf "%s[warn]%s     %s\n" "$YLW" "$OFF" "$*"; }
err()   { printf "%s[error]%s    %s\n" "$RED" "$OFF" "$*" >&2; }
die()   { err "$*"; exit 1; }

usage() {
    cat <<EOF
${BOLD}G.A8.1 modality-3 thin-client setup${OFF}

  ./client.sh [SUBCOMMAND] [OPTIONS]

${BOLD}Subcommands:${OFF}
  build              clone repos, install deps, build EHC, write env file (default)
  check              detect platform + tools without modifying anything
  help               show this message

${BOLD}Options:${OFF}
  --prefix DIR       install location (default: ${DEFAULT_PREFIX})
  --ref SHA          git ref to pin EHC and G.A8.1 to (default: main)
  --ehc-repo URL     override EHC remote
  --g81-repo URL     override G.A8.1 remote
  --force            wipe build dir and rebuild
  --no-install       skip system-package installation; fail if deps missing

${BOLD}Notes:${OFF}
  - Will print exact package commands and ask before invoking sudo.
  - Supported Python: ${PYTHON_MIN}–${PYTHON_MAX} (3.12 recommended).
  - Windows: stubbed; see scripts/INSTALL.md for manual instructions.
  - After build, source the printed env file before running decode13.
EOF
}

# ── Args ────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        build|check|help) SUBCOMMAND="$1"; shift ;;
        --prefix)         PREFIX="$2"; shift 2 ;;
        --ref)            REF="$2"; shift 2 ;;
        --ehc-repo)       EHC_REPO="$2"; shift 2 ;;
        --g81-repo)       G81_REPO="$2"; shift 2 ;;
        --force)          FORCE=1; shift ;;
        --no-install)     NO_INSTALL=1; shift ;;
        -h|--help)        usage; exit 0 ;;
        *)                err "unknown arg: $1"; usage; exit 2 ;;
    esac
done

if [[ "$SUBCOMMAND" == "help" ]]; then usage; exit 0; fi

# ── Platform + package manager detection ────────────────────────────
detect_platform() {
    local uname_s; uname_s="$(uname -s)"
    case "$uname_s" in
        Linux)              PLATFORM="linux" ;;
        Darwin)             PLATFORM="macos" ;;
        MINGW*|MSYS*|CYGWIN*) PLATFORM="windows" ;;
        *)                  PLATFORM="unknown" ;;
    esac
    ARCH="$(uname -m)"
    INSTALL_TAG="${PLATFORM}-${ARCH}"
}

detect_pkg_manager() {
    PKG_MGR="none"
    PKG_INSTALL_CMD=""
    PKG_LIST_CMD=""
    case "$PLATFORM" in
        linux)
            if   command -v apt-get >/dev/null 2>&1; then
                PKG_MGR="apt"
                PKG_INSTALL_CMD="sudo apt-get update && sudo apt-get install -y"
                PKG_LIST_CMD="dpkg -s"
            elif command -v dnf >/dev/null 2>&1; then
                PKG_MGR="dnf"
                PKG_INSTALL_CMD="sudo dnf install -y"
                PKG_LIST_CMD="rpm -q"
            elif command -v pacman >/dev/null 2>&1; then
                PKG_MGR="pacman"
                PKG_INSTALL_CMD="sudo pacman -S --needed --noconfirm"
                PKG_LIST_CMD="pacman -Q"
            fi
            ;;
        macos)
            if command -v brew >/dev/null 2>&1; then
                PKG_MGR="brew"
                PKG_INSTALL_CMD="brew install"
                PKG_LIST_CMD="brew list --versions"
            fi
            ;;
    esac
}

# Map our generic dep names → package names per platform
pkg_name_for() {
    local dep="$1"
    case "$PKG_MGR:$dep" in
        apt:cmake)         echo "cmake" ;;
        apt:cxx)           echo "build-essential" ;;
        apt:python-dev)    echo "python3-dev" ;;
        apt:pip)           echo "python3-pip" ;;
        apt:venv)          echo "python3-venv" ;;
        apt:git)           echo "git" ;;
        apt:rsync)         echo "rsync" ;;
        dnf:cmake)         echo "cmake" ;;
        dnf:cxx)           echo "gcc-c++" ;;
        dnf:python-dev)    echo "python3-devel" ;;
        dnf:pip)           echo "python3-pip" ;;
        dnf:venv)          echo "" ;;  # bundled in python3
        dnf:git)           echo "git" ;;
        dnf:rsync)         echo "rsync" ;;
        pacman:cmake)      echo "cmake" ;;
        pacman:cxx)        echo "base-devel" ;;
        pacman:python-dev) echo "" ;;  # bundled in python
        pacman:pip)        echo "python-pip" ;;
        pacman:venv)       echo "" ;;
        pacman:git)        echo "git" ;;
        pacman:rsync)      echo "rsync" ;;
        brew:cmake)        echo "cmake" ;;
        brew:cxx)          echo "" ;;  # Xcode CLI tools, handled separately
        brew:python-dev)   echo "python@3.12" ;;
        brew:pip)          echo "" ;;  # bundled in python@3.12
        brew:venv)         echo "" ;;
        brew:git)          echo "" ;;  # Xcode CLI tools
        brew:rsync)        echo "rsync" ;;
        *)                 echo "" ;;
    esac
}

# ── Tool checks ─────────────────────────────────────────────────────
have() { command -v "$1" >/dev/null 2>&1; }

check_python() {
    PYTHON_BIN=""
    for cand in python3.12 python3.11 python3.13 python3.10 python3.14 python3 python; do
        if have "$cand"; then
            local ver; ver="$($cand -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
            if [[ -n "$ver" ]] && python_version_in_range "$ver"; then
                PYTHON_BIN="$cand"
                PYTHON_VERSION="$ver"
                return 0
            fi
        fi
    done
    return 1
}

python_version_in_range() {
    local ver="$1"
    awk -v v="$ver" -v mn="$PYTHON_MIN" -v mx="$PYTHON_MAX" 'BEGIN {
        split(v, a, "."); split(mn, b, "."); split(mx, c, ".");
        v_num = a[1]*100 + a[2];
        mn_num = b[1]*100 + b[2];
        mx_num = c[1]*100 + c[2];
        exit (v_num >= mn_num && v_num <= mx_num) ? 0 : 1
    }'
}

# ── Dependency check + install ──────────────────────────────────────
NEEDED_DEPS=(cmake cxx python-dev pip git rsync)

check_deps() {
    MISSING_TOOLS=()  # generic names of things we don't have
    have cmake     || MISSING_TOOLS+=(cmake)
    have git       || MISSING_TOOLS+=(git)
    have rsync     || MISSING_TOOLS+=(rsync)
    if ! have g++ && ! have clang++ ; then
        MISSING_TOOLS+=(cxx)
    fi
    if ! check_python ; then
        MISSING_TOOLS+=(python-dev)
    fi
    if [[ -n "${PYTHON_BIN:-}" ]]; then
        if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
            MISSING_TOOLS+=(pip)
        fi
    fi
}

install_deps() {
    if [[ ${#MISSING_TOOLS[@]} -eq 0 ]]; then
        ok "all required tools present"
        return 0
    fi
    if [[ "$NO_INSTALL" -eq 1 ]]; then
        die "missing tools: ${MISSING_TOOLS[*]}; --no-install set, refusing to sudo. Install manually and rerun."
    fi
    if [[ "$PKG_MGR" == "none" ]]; then
        die "no supported package manager detected on this $PLATFORM. Install ${MISSING_TOOLS[*]} manually."
    fi

    # macOS has a special path for the C++ toolchain (Xcode CLI tools)
    if [[ "$PLATFORM" == "macos" ]] && ! have clang++ ; then
        warn "macOS Xcode Command Line Tools missing. Will run: xcode-select --install"
        printf "Proceed? [y/N] "; read -r ans
        case "$ans" in [yY]*) xcode-select --install || true ;; *) die "aborted" ;; esac
    fi

    local pkgs=()
    for dep in "${MISSING_TOOLS[@]}"; do
        local name; name="$(pkg_name_for "$dep")"
        [[ -n "$name" ]] && pkgs+=("$name")
    done
    if [[ ${#pkgs[@]} -eq 0 ]]; then
        warn "missing tools but nothing to install via $PKG_MGR; proceeding"
        return 0
    fi

    # Show, ask, sudo
    log "Will install (${PKG_MGR}): ${pkgs[*]}"
    log "Command: $PKG_INSTALL_CMD ${pkgs[*]}"
    printf "Proceed? [y/N] "; read -r ans
    case "$ans" in
        [yY]*) ;;
        *)     die "aborted by user" ;;
    esac
    eval "$PKG_INSTALL_CMD ${pkgs[*]}"

    # Re-detect after install
    check_python || die "Python ${PYTHON_MIN}–${PYTHON_MAX} still not available after install"
    check_deps
    if [[ ${#MISSING_TOOLS[@]} -ne 0 ]]; then
        die "still missing after install: ${MISSING_TOOLS[*]}"
    fi
    ok "all required tools now present"
}

# ── Repo clone ──────────────────────────────────────────────────────
clone_or_update() {
    local url="$1" dir="$2"
    if [[ -d "$dir/.git" ]]; then
        log "$dir already exists; fetching"
        git -C "$dir" fetch --quiet origin
    else
        log "cloning $url → $dir"
        git clone --quiet "$url" "$dir"
    fi
    log "checking out ref: $REF"
    git -C "$dir" checkout --quiet "$REF"
}

# ── Build ───────────────────────────────────────────────────────────
build_ehc() {
    local ehc_dir="$PREFIX/EHC"
    local build_dir="$ehc_dir/build-$INSTALL_TAG"
    local install_dir="$ehc_dir/install/$INSTALL_TAG"

    if [[ "$FORCE" -eq 1 && -d "$build_dir" ]]; then
        log "--force: removing $build_dir"
        rm -rf "$build_dir"
    fi

    local jobs
    jobs="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)"

    log "configuring EHC ($build_dir)"
    cmake -S "$ehc_dir" -B "$build_dir" \
        -DCMAKE_BUILD_TYPE=Release \
        -DEHC_BUILD_PYTHON=ON \
        -DCMAKE_INSTALL_PREFIX="$install_dir" \
        -DPython_EXECUTABLE="$(command -v "$PYTHON_BIN")" \
        >/dev/null
    log "building EHC (-j$jobs)"
    cmake --build "$build_dir" --target install -- -j"$jobs"
    EHC_INSTALL="$install_dir"
    ok "EHC built and installed at $install_dir"
}

verify_build() {
    log "verifying ehc import"
    PYTHONPATH="$EHC_INSTALL" "$PYTHON_BIN" - <<'PY'
import sys, ehc
print(f"  ehc loaded from: {ehc.__file__}")
print(f"  python: {sys.version.split()[0]}")
cb_cfg = ehc.CodebookConfig()
cb_cfg.dim, cb_cfg.k, cb_cfg.seed = 16384, 128, 42
cb = ehc.TokenCodebook(cb_cfg); cb.build_from_vocabulary([])
sv = cb.encode_token("Q1860")
ix = list(sv.indices)[:4]
expected = [10024, 4971, 928, 3628]
ok = ix == expected
print(f"  Q1860 first-4 indices: {ix}")
print(f"  expected (post-BUG-EHC-06):  {expected}")
print(f"  match: {ok}")
sys.exit(0 if ok else 1)
PY
}

install_python_deps() {
    log "installing numpy via pip --user"
    "$PYTHON_BIN" -m pip install --user --quiet "numpy>=1.24"
}

write_env_file() {
    local env_file="$PREFIX/client.env"
    cat >"$env_file" <<EOF
# G.A8.1 modality-3 client env — generated by client.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Source this before invoking decode13:  source $env_file

export PYTHONPATH="$EHC_INSTALL:$PREFIX/G.A8.1\${PYTHONPATH:+:\$PYTHONPATH}"
export A81_INDEX_PATH="$PREFIX/G.A8.1/data/encoded"
export A81_TIER_ROUTED=1
export A81_SEED=42
EOF
    ENV_FILE="$env_file"
    ok "wrote $env_file"
}

# ── Subcommand: check ───────────────────────────────────────────────
do_check() {
    detect_platform
    detect_pkg_manager
    log "Platform:        $PLATFORM ($ARCH)"
    log "Package manager: $PKG_MGR"
    if [[ "$PLATFORM" == "windows" ]]; then
        warn "Windows MSYS2 detected — client.sh stub only. See scripts/INSTALL.md."
    fi
    check_deps
    if [[ -n "${PYTHON_BIN:-}" ]]; then
        log "Python:          $PYTHON_BIN ($PYTHON_VERSION)"
    else
        warn "No Python in supported range ($PYTHON_MIN–$PYTHON_MAX) found."
    fi
    if [[ ${#MISSING_TOOLS[@]} -eq 0 ]]; then
        ok "all prerequisites present; ready to ./client.sh build"
    else
        warn "missing: ${MISSING_TOOLS[*]}"
        log  "to install: ./client.sh build       (will prompt before sudo)"
    fi
}

# ── Subcommand: build ───────────────────────────────────────────────
do_build() {
    detect_platform
    detect_pkg_manager
    log "Platform:        $PLATFORM ($ARCH)"
    if [[ "$PLATFORM" == "unknown" ]]; then
        die "unsupported platform: $(uname -s)"
    fi
    if [[ "$PLATFORM" == "windows" ]]; then
        cat >&2 <<EOF

${YLW}Windows (MSYS2) is not yet automated.${OFF}

Manual steps documented in scripts/INSTALL.md:
  - Install MSYS2 clang64 toolchain + Python 3.10–3.14
  - Clone EHC + G.A8.1 to a path of your choice
  - cmake -B build-windows-x86_64 -DEHC_BUILD_PYTHON=ON -G Ninja
  - cmake --build build-windows-x86_64 --target install
  - Source the env vars listed in scripts/INSTALL.md

Why this stub: bash on Windows runs in MSYS2/clang64, but the
toolchain detection + sudo flow differs enough from POSIX that
we want it landed as a separate path rather than half-supported.

EOF
        exit 1
    fi

    mkdir -p "$PREFIX"
    log "Install prefix:  $PREFIX"

    install_deps
    log "Python:          $PYTHON_BIN ($PYTHON_VERSION)"

    clone_or_update "$EHC_REPO" "$PREFIX/EHC"
    clone_or_update "$G81_REPO" "$PREFIX/G.A8.1"

    install_python_deps
    build_ehc
    verify_build
    write_env_file

    cat <<EOF

${BOLD}${GRN}Done.${OFF} Next steps:

  ${DIM}# Load env vars${OFF}
  source $ENV_FILE

  ${DIM}# Pull the corpus from your encoding server${OFF}
  rsync -az encoding-host:/opt/G.A8.1/data/encoded/   $PREFIX/G.A8.1/data/encoded/
  rsync -az encoding-host:/opt/G.A8.1/data/wikidata_*.json   $PREFIX/G.A8.1/data/

  ${DIM}# Run a query${OFF}
  cd $PREFIX/G.A8.1
  python3 -m decode13.benchmark.run_production --help

EOF
}

# ── Dispatch ────────────────────────────────────────────────────────
case "$SUBCOMMAND" in
    check) do_check ;;
    build) do_build ;;
    *)     usage; exit 2 ;;
esac
