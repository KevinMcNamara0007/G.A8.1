# G.A8.1 modality-3 thin-client install

This is the **pull-only** deployment topology: one central encoding host
produces the corpus + index artifacts; many client hosts pull those
artifacts and run queries against them locally, without any encoding
on the edge.

`scripts/client.sh` automates the per-client setup on Linux and macOS.
Windows (MSYS2) is documented manually below.

## Quick start

```bash
git clone https://github.com/KevinMcNamara0007/G.A8.1.git
cd G.A8.1

# Detect platform and tools without changing anything
./scripts/client.sh check

# Install missing system deps (asks before sudo), clone EHC, build,
# write client.env
./scripts/client.sh build

# Load env vars + pull corpus from the encoding server
source ~/letthegamesbegin/client.env
rsync -az encoding-host:/opt/G.A8.1/data/encoded/   ~/letthegamesbegin/G.A8.1/data/encoded/
rsync -az encoding-host:/opt/G.A8.1/data/wikidata_*.json   ~/letthegamesbegin/G.A8.1/data/

# Run a query
cd ~/letthegamesbegin/G.A8.1
python3 -m decode13.benchmark.run_production --help
```

## Supported platforms

| Platform | Status | Toolchain |
|---|---|---|
| Linux (Debian/Ubuntu) | ✅ supported | gcc + libstdc++, apt |
| Linux (Fedora/RHEL)   | ✅ supported | gcc + libstdc++, dnf |
| Linux (Arch)          | ✅ supported | gcc + libstdc++, pacman |
| macOS (Apple Silicon, Intel) | ✅ supported | clang + libc++, brew |
| Windows MSYS2 clang64 | 📋 manual (stub) | clang + libc++; see below |
| Native Windows (PowerShell) | ❌ not supported | use WSL or MSYS2 |

## Prerequisites

Will be installed by `./client.sh build` if missing (with consent):

- **Python 3.10–3.14** (3.12 recommended). Server is on 3.12; both
  3.12 and 3.14 are known working.
- **CMake ≥ 3.20** for the EHC build.
- **C++17 compiler**: `g++ ≥ 11` or `clang++ ≥ 14`.
- **Python development headers** (`python3-dev` / `python3-devel`) for
  the nanobind module build.
- **git, rsync, pip**.

The script does not require Eigen3 or nlohmann/json system packages;
EHC's CMake fetches them on demand.

## What `client.sh build` does

1. Detects platform (`uname`) and package manager (`apt`/`dnf`/`pacman`/`brew`).
2. Checks for missing tools and prints the exact `<pkg-mgr> install …`
   command. Asks before invoking `sudo` — declines by default.
3. On macOS: prompts to run `xcode-select --install` if Command Line
   Tools are missing.
4. Clones `EHC` and `G.A8.1` to `<prefix>/EHC` and `<prefix>/G.A8.1`
   (default prefix `~/letthegamesbegin`).
5. Checks out the requested ref (default `main`).
6. `pip install --user numpy>=1.24`.
7. Configures and builds EHC with `EHC_BUILD_PYTHON=ON` into
   `<prefix>/EHC/install/<platform>-<arch>/`.
8. Verifies the build by importing `ehc`, encoding the canonical
   `Q1860` token, and asserting the first 4 sparse positions match the
   reference fixture (`[10024, 4971, 928, 3628]`). This catches
   BUG-EHC-06 regressions (cross-stdlib determinism break) before
   anything else gets used.
9. Writes `<prefix>/client.env` with `PYTHONPATH`, `A81_INDEX_PATH`,
   `A81_TIER_ROUTED=1`, `A81_SEED=42`.

## Options

| Flag | Default | Notes |
|---|---|---|
| `--prefix DIR` | `~/letthegamesbegin` | Install location |
| `--ref SHA` | `main` | Pin EHC + G.A8.1 to a known-good commit |
| `--ehc-repo URL` | upstream | Override the EHC git remote |
| `--g81-repo URL` | upstream | Override the G.A8.1 git remote |
| `--force` | off | Wipe the EHC build dir and rebuild from scratch |
| `--no-install` | off | Skip system-package install; fail loudly if anything is missing |

## After install

`client.env` is sourceable, not auto-loaded. Add it to your shell rc
or source it per-session.

The bundle the client pulls is exactly:

```
data/encoded/                   # 600 shards (≈ 164 MB at 100k records)
  manifest.json
  shard_NNNN/
    centroid.npz
    index/{chunk_index.npz, lsh_index.npz}
    tier_manifest.{json,npy}
    symmetry_manifest.json
    sidecar.{ehs,manifest}
    meta/, texts.json
  clusters.json, action_clusters.json, centroids.json, _global_idf.json

data/wikidata_*.json            # corpus source (for benchmark gold sampling)
```

`corpus_profile.json` is **optional** in the bundle. The decoder doesn't
need it; only `encode.profile` does.

## Manual Windows (MSYS2 clang64) install

Until `client.sh` supports MSYS2:

```bash
# 1. Install MSYS2 + clang64 toolchain
#    https://www.msys2.org/  →  install, then in MSYS2 clang64 shell:
pacman -S --needed mingw-w64-clang-x86_64-toolchain \
                   mingw-w64-clang-x86_64-cmake \
                   mingw-w64-clang-x86_64-ninja \
                   mingw-w64-clang-x86_64-python \
                   git rsync

# 2. Pick a prefix (no spaces!) and clone
PREFIX="$HOME/letthegamesbegin"
mkdir -p "$PREFIX" && cd "$PREFIX"
git clone https://github.com/KevinMcNamara0007/EHC.git
git clone https://github.com/KevinMcNamara0007/G.A8.1.git

# 3. Build EHC
cd EHC
cmake -S . -B build-windows-x86_64 \
    -DCMAKE_BUILD_TYPE=Release \
    -DEHC_BUILD_PYTHON=ON \
    -DCMAKE_INSTALL_PREFIX="$PWD/install/windows-x86_64" \
    -G Ninja
cmake --build build-windows-x86_64 --target install

# 4. pip install
python -m pip install --user "numpy>=1.24"

# 5. Sanity-check the build (must print "match: True")
PYTHONPATH="$PWD/install/windows-x86_64" python -c '
import ehc
cfg = ehc.CodebookConfig(); cfg.dim, cfg.k, cfg.seed = 16384, 128, 42
cb = ehc.TokenCodebook(cfg); cb.build_from_vocabulary([])
ix = list(cb.encode_token("Q1860").indices)[:4]
print("first-4:", ix, "match:", ix == [10024, 4971, 928, 3628])
'

# 6. Set env (Windows: in your shell profile or per-session)
export PYTHONPATH="$PREFIX/EHC/install/windows-x86_64:$PREFIX/G.A8.1"
export A81_INDEX_PATH="$PREFIX/G.A8.1/data/encoded"
export A81_TIER_ROUTED=1
export A81_SEED=42

# 7. Pull the corpus
rsync -az encoding-host:/opt/G.A8.1/data/encoded/   "$PREFIX/G.A8.1/data/encoded/"
rsync -az encoding-host:/opt/G.A8.1/data/wikidata_100k.json   "$PREFIX/G.A8.1/data/"
```

## Troubleshooting

**`./client.sh build` exits saying "Python 3.10–3.14 still not available after install".**
The package manager picked a Python outside our supported range. Install
3.12 explicitly: `apt install python3.12`, `brew install python@3.12`,
or use [`pyenv`](https://github.com/pyenv/pyenv).

**Build verification step prints `match: False`.**
This means BUG-EHC-06 (the `std::uniform_int_distribution` cross-stdlib
break) is regressing — `symbolic_encoder.cpp` should have a portable
rejection sampler in `hash_to_indices`. If you're on a fresh upstream
checkout that has *not* yet merged the BUG-EHC-06 fix, apply the patch
documented in `bugs_for_kevin.md` and rerun `./client.sh build --force`.

**`std::bad_alloc` when loading 1800+ shards.**
BUG-DATA-02: `decode13/query_service.py:_load_lsh` historically called
`.tolist()` on numpy arrays, blowing memory. The fix in the upstream
tree avoids this. If you're on a pre-fix checkout, apply the patch
from `bugs_for_kevin.md`.

**`tier_counts={'structured_atomic': 0, ...}` at decode startup.**
BUG-DATA-01: the corpus was encoded without `A81_TIER_ROUTED=1`. Ask
the encoding host to re-encode with the env var set. The client side
is fine.

**Cross-platform 0% Hit@k after everything looks healthy.**
You're probably on a different stdlib than the encoding host without
the BUG-EHC-06 patch. Run the build-verification one-liner from step
5 above; if `match: False`, the encoder is non-portable.
