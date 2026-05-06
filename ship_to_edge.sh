#!/usr/bin/env bash
# ============================================================================
# ship_to_edge.sh — M1 → Edge DC bundle ship over SSH.
#
#   Usage:
#     ./ship_to_edge.sh user@edge.host [REMOTE_INDEX_PATH]
#
#   Defaults:
#     REMOTE_INDEX_PATH = $A81_INDEX_PATH (whatever the local DC encoded into).
#     Bundle is written to /tmp/a81-bundle-<id>.tar locally and on the edge,
#     then deleted on success on both sides.
#
#   Trust model:
#     SSH provides the authenticated channel between DC and edge. The bundle
#     is UNSIGNED by default (per-file SHA-256 in the manifest still catches
#     bit rot and accidental corruption). Set A81_BUNDLE_SIGN=true to opt
#     into KMS signing; that requires A81_KMS_PROVIDER and a signing key
#     ref configured in your environment.
#
#   What this script does NOT do:
#     - Does not push the G.A8.1 Python package or the EHC native binary.
#       Those are versioned with the release and shipped separately
#       (see build_eh.sh for the EHC compile step).
#     - Does not configure SSH access. Set up keys / agent forwarding first.
# ============================================================================

set -euo pipefail

# ── Args ────────────────────────────────────────────────────────
if [[ $# -lt 1 ]]; then
  echo "usage: $0 user@edge.host [REMOTE_INDEX_PATH]" >&2
  exit 64
fi
EDGE_TARGET="$1"
REMOTE_INDEX_PATH="${2:-${A81_INDEX_PATH:-}}"

# ── Resolve config ──────────────────────────────────────────────
G_A81_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$G_A81_DIR"

# Prefer process env; fall back to config.env values for defaults.
# Source config.env so A81_INDEX_PATH and friends are populated when invoked
# without explicit env. Process env wins.
if [[ -f "$G_A81_DIR/config.env" ]]; then
  set -a; source "$G_A81_DIR/config.env"; set +a
fi

LOCAL_INDEX_PATH="${A81_INDEX_PATH:-}"
if [[ -z "$LOCAL_INDEX_PATH" ]]; then
  echo "error: A81_INDEX_PATH is unset; cannot locate local encoded data" >&2
  exit 1
fi
if [[ ! -d "$LOCAL_INDEX_PATH" ]]; then
  echo "error: local INDEX_PATH does not exist: $LOCAL_INDEX_PATH" >&2
  exit 1
fi
if [[ -z "$REMOTE_INDEX_PATH" ]]; then
  REMOTE_INDEX_PATH="$LOCAL_INDEX_PATH"
fi

# Profile gate — refuse to ship without a corpus profile (edge can't reprofile).
if [[ ! -f "$LOCAL_INDEX_PATH/corpus_profile.json" ]]; then
  echo "error: $LOCAL_INDEX_PATH/corpus_profile.json missing." >&2
  echo "       Run the v13.1 corpus profiler before shipping; edge has no corpus to reprofile." >&2
  exit 1
fi

# ── Bundle path ─────────────────────────────────────────────────
BUNDLE_ID="$(python3 -c 'import os; print(os.urandom(8).hex())')"
LOCAL_BUNDLE="/tmp/a81-bundle-${BUNDLE_ID}.tar"
REMOTE_BUNDLE="/tmp/a81-bundle-${BUNDLE_ID}.tar"

# ── Sign?  Default unsigned for M1; opt-in via env. ─────────────
SIGN_FLAG="--unsigned"
SIGN_LABEL="unsigned"
if [[ "${A81_BUNDLE_SIGN:-false}" == "true" ]]; then
  if [[ "${A81_KMS_PROVIDER:-none}" == "none" ]]; then
    echo "error: A81_BUNDLE_SIGN=true but A81_KMS_PROVIDER=none." >&2
    echo "       Configure a KMS provider (qkey or local) or unset A81_BUNDLE_SIGN." >&2
    exit 1
  fi
  if [[ -z "${A81_BUNDLE_SIGNING_KEY_REF:-}" ]]; then
    echo "error: A81_BUNDLE_SIGN=true requires A81_BUNDLE_SIGNING_KEY_REF." >&2
    exit 1
  fi
  SIGN_FLAG=""
  SIGN_LABEL="signed:${A81_BUNDLE_SIGNING_KEY_REF}"
fi

echo "[1/5] resolving plan"
echo "      local INDEX_PATH    = $LOCAL_INDEX_PATH"
echo "      remote target       = ${EDGE_TARGET}:${REMOTE_INDEX_PATH}"
echo "      bundle              = ${LOCAL_BUNDLE}  (${SIGN_LABEL})"

# ── Export ──────────────────────────────────────────────────────
echo "[2/5] exporting bundle"
A81_BUNDLE_PATH="$LOCAL_BUNDLE" \
  python3 -m tools.bundle_export $SIGN_FLAG

# ── Transfer ────────────────────────────────────────────────────
echo "[3/5] transferring over SSH (scp)"
scp -q "$LOCAL_BUNDLE" "${EDGE_TARGET}:${REMOTE_BUNDLE}"

# ── Remote import ───────────────────────────────────────────────
# We assume the remote has the G.A8.1 package available at
# $A81_REMOTE_DIR (default ~/G.A8.1). Override A81_REMOTE_DIR if the
# edge install lives elsewhere.
A81_REMOTE_DIR="${A81_REMOTE_DIR:-\$HOME/G.A8.1}"

echo "[4/5] importing on edge"
# shellcheck disable=SC2087
ssh "$EDGE_TARGET" bash -s <<EOF
set -euo pipefail
cd "$A81_REMOTE_DIR"
A81_MODALITY=edge_dc \
A81_ROLE=edge \
A81_BUNDLE_PATH="$REMOTE_BUNDLE" \
A81_INDEX_PATH="$REMOTE_INDEX_PATH" \
A81_BUNDLE_VERIFY_ON_LOAD=$([[ "$SIGN_LABEL" == "unsigned" ]] && echo false || echo true) \
A81_KMS_PROVIDER="${A81_KMS_PROVIDER:-none}" \
A81_KMS_LOCAL_DIR="${A81_KMS_LOCAL_DIR:-}" \
A81_QKEY_URL="${A81_QKEY_URL:-}" \
A81_QKEY_ACCESS_KEY_FILE="${A81_QKEY_ACCESS_KEY_FILE:-}" \
A81_QKEY_MODE="${A81_QKEY_MODE:-omega}" \
python3 -m tools.bundle_import
rm -f "$REMOTE_BUNDLE"
EOF

# ── Cleanup ─────────────────────────────────────────────────────
echo "[5/5] cleanup"
rm -f "$LOCAL_BUNDLE"

echo "✓ ship_to_edge: bundle ${BUNDLE_ID} delivered to ${EDGE_TARGET}:${REMOTE_INDEX_PATH}"
