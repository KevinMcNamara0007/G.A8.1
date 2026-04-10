#!/usr/bin/env bash
# ============================================================
# G.A8.1 — Two-Tier Emergent Routing Pipeline
#
# Step 0: Discover action clusters from corpus
# Step 1: Two-tier encode (entity hash × action cluster)
# Step 2: Benchmark
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SOURCE="${1:-/Users/stark/Quantum_Computing_Lab/DC1/GoldC-Wiki/triples_clean.json}"
OUTPUT="${2:-/Users/stark/Quantum_Computing_Lab/DC1/GoldC-Wiki/output/a81_encoded}"

ENTITY_BUCKETS=36
N_CLUSTERS=50
CLUSTER_SAMPLE=200000
WAVES=9
DIM=16384
K=128

echo "============================================================"
echo "  G.A8.1 — Two-Tier Emergent Routing"
echo "============================================================"
echo "  Source:   $SOURCE"
echo "  Output:   $OUTPUT"
echo "  Entity:   $ENTITY_BUCKETS buckets"
echo "  Action:   $N_CLUSTERS clusters (discovered)"
echo "  Shards:   $((ENTITY_BUCKETS * N_CLUSTERS)) max"
echo "  D=$DIM  k=$K"
echo "============================================================"

if [ ! -f "$SOURCE" ]; then
    echo "ERROR: Source not found: $SOURCE"
    exit 1
fi

# Clean previous
if [ -d "$OUTPUT" ]; then
    echo "  Cleaning previous output..."
    rm -rf "$OUTPUT"
fi
mkdir -p "$OUTPUT"

# Step 0: Discover clusters
echo ""
echo "--- STEP 0: Discover action clusters ---"
python3 encode/discover_clusters.py \
    --source "$SOURCE" \
    --sample "$CLUSTER_SAMPLE" \
    --n-clusters "$N_CLUSTERS" \
    --output "$OUTPUT/clusters.json" \
    --dim "$DIM"

# Step 1: Two-tier encode
echo ""
echo "--- STEP 1: Two-tier encode ---"
python3 encode/encode.py \
    --source "$SOURCE" \
    --output "$OUTPUT" \
    --clusters "$OUTPUT/clusters.json" \
    --entity-buckets "$ENTITY_BUCKETS" \
    --waves "$WAVES" \
    --dim "$DIM" \
    --k "$K"

echo ""
echo "============================================================"
echo "  Pipeline complete."
echo "  Output: $OUTPUT"
echo "============================================================"
