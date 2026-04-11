# G.A8.1 — Holographic Encoding Engine

Two-tier sharded BSC (Binary Sparse Coding) engine for encoding, storing,
and querying any data type at datacenter scale.

**Key properties:**
- Zero neural networks, zero GPU, zero training
- 16,384-dimensional sparse ternary vectors (128 active indices)
- Sub-20ms query latency on 250K+ vectors
- 793 bytes per vector, ~7GB for 10M vectors
- Parallel multi-core search, async-ready API
- 7-hook plugin architecture for domain customization

## Quick Start

```bash
# 1. Install (builds EHC C++ library, runs smoke tests)
./install.sh

# 2. Encode data
source config.env
python3 encode/encode.py \
    --source /path/to/data.jsonl \
    --output /path/to/encoded \
    --clusters /path/to/clusters.json

# 3. Query from Python
python3 -c "
from query_service import QueryService
svc = QueryService('/path/to/encoded')
results = svc.query('iran missile test', k=10)
for r in results['results']:
    print(r['similarity'], r['metadata']['message_text_translated'][:80])
"
```

## Directory Structure

```
G.A8.1/
  install.sh              # Build EHC + smoke test (run first)
  config.env              # All tunables (source before encoding)
  config.py               # Python config reader (auto-loads from env)
  README.md               # This file

  encode/
    encode.py             # Encode orchestrator (main entry point)
    worker_encode.py      # Per-shard encoder (parallel workers)
    discover_clusters.py  # Action cluster discovery (BSC k-means)
    resolvers/            # Domain-specific token normalizers
      __init__.py         #   Registry
      wikidata.py         #   QID → canonical label
      genomics.py         #   HGNC gene symbol resolver
      pubmed.py           #   MeSH term resolver
      edge_gazetteer.py   #   Edge analyst domain terms

  decode/
    query_service.py      # C++ query service (parallel, async-ready)
    hooks.py              # 7-hook plugin architecture
    adaptive_gazetteer.py # Hebbian + Ebbinghaus learner (optional)
    benchmark.py          # WikiData-style benchmark
    benchmark_edge.py     # Edge multi-factor benchmark

  encode_edge.py          # Edge analyst full pipeline (reference impl)
  pipeline.sh             # Shell pipeline for WikiData encoding
```

## Architecture

```
SOURCE DATA (any format)
    |
    v
ENCODE: tokenize ALL fields → select top-12 by IDF → superpose
    |
    +--> SEARCHABLE: BSC vector (dim=16384, k=128) → CompactIndex + LSH
    |
    +--> HIDDEN: original record fields → sidecar JSON arrays
    |
    +--> MEDIA: C++ VisionEncoder/VideoEncoder → separate media index
    |
    v
HOLOGRAPHIC MATRIX (80 shards, two-tier routing)
    |
    v
QUERY: clean → encode → route(centroid knn) → search(parallel) → rerank → enrich
    |
    v
RESULTS: [{id, similarity, metadata: {text, author, tags, media_url, why_matched, ...}}]
```

## Encoding

### Supported Input Formats

| Format | Auto-detected by | Example |
|---|---|---|
| JSON triples | File starts with `[` and records have `subject` field | WikiData, knowledge graphs |
| JSONL messages | File ends with `.jsonl` or records are one-per-line JSON | Social media, logs, events |

### How Encoding Works

Every record is encoded the same way regardless of data type:

1. **Tokenize ALL fields** — subject + relation + object (or equivalent)
2. **Select top √k = 12 tokens** by global IDF with gazetteer guaranteed slots
3. **superpose(tokens)** — majority vote of 12 hash-based sparse vectors
4. **Store sidecar** — original record fields in parallel JSON arrays

Short records (triples, log lines) use all tokens naturally.
Long records (messages, documents) compress to their 12 most discriminating features.

### Two-Tier Shard Routing

```
shard_id = hash(subject) × nearest_cluster(relation)
```

- **Level 1**: blake2b hash of subject entity → entity bucket
- **Level 2**: BSC cosine to nearest action cluster centroid → action cluster
- **Result**: semantically coherent shards (~3K vectors each)

### Running an Encode

```bash
# Step 0: Discover action clusters from corpus
python3 encode/discover_clusters.py \
    --source data.jsonl \
    --n-clusters 20 \
    --output clusters.json

# Step 1: Encode
python3 encode/encode.py \
    --source data.jsonl \
    --output /encoded \
    --clusters clusters.json \
    --entity-buckets 4 \
    --waves 4

# Or use the edge pipeline (handles JSONL combining, media, gazetteer):
python3 encode_edge.py
```

## Ingesting Data

G.A8.1 supports two ingest modes: **batch encode** for building an index from
scratch, and **incremental ingest** for appending new records to an existing index.

### Batch Encode (full corpus)

Use this for the initial build or when re-encoding the entire corpus:

```bash
# 1. Discover clusters
python3 encode/discover_clusters.py --source data.jsonl --n-clusters 20 --output clusters.json

# 2. Full encode
python3 encode/encode.py --source data.jsonl --output /encoded --clusters clusters.json
```

This produces the complete holographic matrix — all shards, indices, sidecar
metadata, centroids, gazetteer, and global IDF.

**When to re-encode from scratch:**
- First time encoding a new corpus
- Significant change in data distribution (new language, new domain)
- After changing `A81_DIM`, `A81_K`, or shard configuration
- After updating the gazetteer or resolver with many new terms

### Incremental Ingest (append to existing)

Use this for adding new records without re-encoding the entire corpus.
The existing index stays intact — new vectors are appended to the
appropriate shards using the same routing and encoding strategy.

```python
from ingest import IncrementalIngest

# Connect to existing encoded index
ing = IncrementalIngest("/path/to/encoded")
```

#### Single Record

```python
ing.ingest({
    "subject": "hakc93",
    "relation": "telegram iran terrorism",
    "object": "Breaking: new missile test reported in eastern Iran...",
    "timestamp": "2026-04-09T14:30:00Z",
    "media_path": "/path/to/image.jpg",       # optional
    "_sidecar": {                               # optional — preserves original fields
        "message_text_translated": "Breaking: new missile test...",
        "message_text": "عاجل: تجربة صاروخية جديدة...",
        "author": "hakc93",
        "channel": "news_channel",
        "tags": ["iran", "military", "missile"],
        "posted_at": "2026-04-09T14:30:00Z",
        "url": "https://t.me/news_channel/12345",
        "media_path": "/path/to/image.jpg",
    },
})
```

#### Batch of Records

```python
new_messages = [
    {"subject": "author1", "relation": "topic tags", "object": "Message text..."},
    {"subject": "author2", "relation": "topic tags", "object": "Another message..."},
    # ... hundreds or thousands of records
]

ing.ingest_batch(new_messages)
```

#### Flush to Disk

Records are buffered in memory until you explicitly flush. This allows
batching many ingests before incurring the disk I/O cost:

```python
# Check buffer status
print(ing.stats)
# → {"ingested": 500, "buffered": 500, "affected_shards": 12, "flushed": 0}

# Write to disk (atomic per shard)
ing.flush()
# → [shard 0003] +42 vectors (total: 3136)
# → [shard 0017] +38 vectors (total: 2890)
# → Flushed 500 vectors to 12 shards in 2.3s
```

#### Hot Reload in Running Service

If a `QueryService` is running (e.g., serving the web interface), reload
the affected shards to pick up the new data — no restart needed:

```python
# After flush
svc.reload_shards(ing.affected_shards)
# → [QueryService] Reloaded 12 shards
```

Or from a FastAPI endpoint:

```python
@app.post("/ingest/batch")
async def ingest_batch(records: List[dict]):
    ing = IncrementalIngest(index_dir)
    ing.ingest_batch(records)
    ing.flush()
    app_state.a81_query_service.reload_shards(ing.affected_shards)
    return {"ingested": ing.stats["ingested"]}
```

#### What Happens Under the Hood

For each ingested record:

1. **Route**: `hash(subject) × nearest_cluster(relation)` → target shard
   (same deterministic routing as batch encode)
2. **Encode**: tokenize all fields → select top-12 by IDF + gazetteer → superpose
   (same codebook, same IDF, same gazetteer as original encode)
3. **Buffer**: vector + sidecar metadata held in memory
4. **Flush**: for each affected shard:
   - Load existing index from disk
   - Append new vectors to CompactIndex + LSH
   - Append new metadata to sidecar JSON arrays
   - Rewrite shard files atomically

#### Incremental vs Batch: When to Use Which

| Scenario | Use | Why |
|---|---|---|
| First encode of 250K records | **Batch** | Parallel waves, optimized I/O |
| Daily scrape of 5K new messages | **Incremental** | 2-5 seconds, no downtime |
| Monthly re-scrape of full corpus | **Batch** | Fresh IDF, clean index |
| Real-time streaming (1 msg/sec) | **Incremental** | Flush every 100 records |
| Changed dim/k/shard config | **Batch** | Existing index incompatible |
| Added new gazetteer terms | **Either** | Batch for full benefit, incremental works |

#### Record Format

The minimum record for ingest:

```python
{
    "subject": "entity_name",        # Required: routes to shard
    "relation": "context tags",       # Required: routes to action cluster
    "object": "searchable content",   # Required: the text to encode
}
```

Full record with sidecar (preserves all original fields for display):

```python
{
    "subject": "hakc93",
    "relation": "telegram iran terrorism politics",
    "object": "Full translated message text here...",
    "timestamp": "2026-04-09T14:30:00Z",
    "media_path": "/abs/path/to/image.jpg",
    "url": "https://source.url/post/123",
    "_sidecar": {
        "message_text_translated": "Full translated message...",
        "message_text": "Original language text...",
        "author": "hakc93",
        "channel": "channel_name",
        "tags": ["iran", "terrorism", "politics"],
        "posted_at": "2026-04-09T14:30:00Z",
        "url": "https://source.url/post/123",
        "language": "fa",
        "media_path": "/abs/path/to/image.jpg",
        "media_type": "image",
    }
}
```

If `_sidecar` is omitted, the ingest engine constructs sidecar metadata from
the top-level fields. If `_sidecar` is present, those values are stored exactly
as provided — never transformed.

## Querying

### Python API

```python
from query_service import QueryService

# Basic — uses default hooks
svc = QueryService("/path/to/encoded")

# With product hooks (auto-detected from hooks.py in product dir)
from hooks import load_hooks
hooks = load_hooks(product_dir="/path/to/product", index_dir="/path/to/encoded")
svc = QueryService("/path/to/encoded", hooks=hooks)

# Text search
results = svc.query("iran missile test", k=10)

# Image search (separate media index)
images = svc.query_images("military vehicle", k=5)

# Multimodal (parallel text + image, weighted merge)
multi = svc.query_multimodal("hezbollah operations", k=10, image_weight=0.3)

# Async (for FastAPI / concurrent workloads)
results = await svc.aquery("iran missile test", k=10)
```

### Query Response

```json
{
  "results": [
    {
      "id": "s41_17",
      "similarity": 0.493,
      "metadata": {
        "message_text_translated": "Iran published a terror list...",
        "author": "canarymission",
        "channel": "news_channel",
        "tags": ["iran", "terrorism", "politics"],
        "media_url": "/media/abc123.jpg",
        "posted_at": "2026-01-12T18:35:51Z",
        "why_matched": "Contains: iran, terror | Location: iran",
        "why_not": "'links' not found (1/4 gap)"
      }
    }
  ],
  "confidence": 0.493,
  "audit": {
    "duration_ms": 16,
    "strategy": "a81_cpp_edge_analyst",
    "shards_searched": 3
  }
}
```

## Hook Architecture

Seven hooks, one engine. Products customize behavior by dropping a `hooks.py`:

| Hook | When | Default | Edge Override |
|---|---|---|---|
| `query_cleaner` | Before encoding query | Strip stops + filter words | NER + gazetteer + query expansion |
| `reranker` | After BSC search | 50% BSC + 40% KW + 10% proximity | + Hebbian + recency |
| `enricher` | Before returning results | Basic keyword explanation | "Why matched" / "Why not" panels |
| `learner` | After returning results | No-op | Hebbian correlation update |
| `resolver` | Encode time | Identity (passthrough) | Domain-specific (WikiData QIDs, HGNC genes) |
| `salience_scorer` | Encode time | Pure IDF | IDF × gazetteer boost (3x for domain terms) |
| `media_encoder` | Encode time | VisionEncoder + VideoEncoder | Same (C++ compiled) |

### Creating Product Hooks

Drop a `hooks.py` in your product directory:

```python
# my_product/hooks.py
from hooks import HookSet, CleanedQuery, ScoredResult

def my_query_cleaner(text: str) -> CleanedQuery:
    tokens = text.lower().split()
    return CleanedQuery(original=text, cleaned=" ".join(tokens), tokens=tokens)

def get_hooks(index_dir=None) -> HookSet:
    return HookSet(
        query_cleaner=my_query_cleaner,
        name="my_product",
    )
```

G.A8.1 auto-discovers it:
```python
hooks = load_hooks(product_dir="/path/to/my_product")
# → loads my_product/hooks.py, calls get_hooks()
```

## Resolvers and Gazetteers

Resolvers and gazetteers are two tools that improve encoding quality.
They serve different purposes but use the same mechanism — a lookup table
that influences which tokens get into the top-12 salient slots.

### When to Use What

| Data has... | Tool | What it does | Example |
|---|---|---|---|
| Canonical identities (same thing, many names) | **Resolver** | Normalizes tokens before hashing | `BRCC1 → brca1`, `Q142 → france` |
| Important domain terms (no canonical IDs) | **Gazetteer** | Boosts terms into top-12 guaranteed slots | `terrorism`, `missile`, `iran` |
| Both | **Both** | Resolver normalizes first, gazetteer boosts after | WikiData + domain concepts |
| Neither (generic text) | **Neither** | Pure IDF selects salient tokens | General web crawl, logs |

**Rule of thumb:**
- If your corpus has entities with multiple spellings → you need a **resolver**
- If your corpus has domain terms that users will search for → you need a **gazetteer**
- If you're not sure → start with neither, add a gazetteer when recall is low

### Resolvers

Resolvers normalize tokens so the same entity always produces the same hash.
Without a resolver, `"BRCC1"` and `"BRCA1"` are two different tokens occupying
two of your 12 salient slots for the same gene. With a resolver, they collapse
to one canonical token — you recover a slot AND the slot is more discriminating.

**Built-in resolvers:**

| Domain | File | What it resolves |
|---|---|---|
| WikiData | `resolvers/wikidata.py` | QID → canonical English label (`Q142 → france`) |
| Genomics | `resolvers/genomics.py` | Gene symbols, aliases, Ensembl/Entrez IDs → HGNC approved symbol |
| PubMed | `resolvers/pubmed.py` | MeSH terms → canonical medical terminology |

**Creating a resolver:**

```python
# resolvers/my_domain.py
def load_my_labels(path: str) -> dict:
    """Load canonical label lookup.
    Returns: {any_variant → canonical_form}
    """
    lookup = {}
    with open(path) as f:
        for line in f:
            variant, canonical = line.strip().split('\t')
            lookup[variant.lower()] = canonical.lower()
    return lookup

def normalize_entity(entity: str, lookup: dict) -> str:
    key = entity.strip().lower()
    return lookup.get(key, key)
```

**Wiring a resolver into hooks:**

```python
# my_product/hooks.py
from hooks import HookSet

def get_hooks(index_dir=None):
    from resolvers.my_domain import load_my_labels, normalize_entity
    lookup = load_my_labels("/path/to/labels.tsv")

    def my_resolver(token: str) -> str:
        return normalize_entity(token, lookup)

    return HookSet(resolver=my_resolver, name="my_product")
```

The resolver runs at **encode time** — it normalizes tokens before they are
hashed into BSC vectors. At query time, the same resolver should normalize
query tokens so they match the encoded form.

### Gazetteers

Gazetteers boost domain-critical terms into the top-12 salient slots
regardless of their IDF score. Without a gazetteer, a term like `"terrorism"`
might have low IDF (appears in 30% of docs) and get pushed out by rare
but irrelevant words. With a gazetteer, `"terrorism"` gets a guaranteed slot.

**How it works:**

During encoding, the salience selector has two phases:
1. **Phase 1**: Reserve slots for gazetteer terms found in the record
2. **Phase 2**: Fill remaining slots by IDF (rarest first)

This ensures domain-critical terms are never crowded out. The `A81_GAZETTEER_BOOST`
config (default 3.0) is the IDF multiplier, but with `A81_GAZETTEER_GUARANTEED=true`
(default), gazetteer terms get reserved slots regardless of IDF.

**Built-in gazetteers:**

| Domain | File | Terms |
|---|---|---|
| Edge/OSINT | `resolvers/edge_gazetteer.py` | 174 terms: locations, organizations, threat concepts |

**Creating a gazetteer:**

```python
# resolvers/my_gazetteer.py
def load_my_gazetteer() -> frozenset:
    return frozenset({
        # Important domain terms that users will search for
        "kubernetes", "deployment", "pod", "container", "ingress",
        "service", "namespace", "helm", "configmap", "secret",
        "timeout", "crashloop", "evicted", "pending", "oom",
    })
```

**Wiring a gazetteer into hooks:**

```python
# my_product/hooks.py
from hooks import HookSet

def get_hooks(index_dir=None):
    from resolvers.my_gazetteer import load_my_gazetteer
    gaz = load_my_gazetteer()
    boost = 3.0

    def my_salience_scorer(token: str, idf_score: float) -> float:
        return idf_score * (boost if token in gaz else 1.0)

    return HookSet(salience_scorer=my_salience_scorer, name="my_product")
```

**Auto-detection:** If an encoded output directory contains `_gazetteer.json`,
G.A8.1 automatically enables gazetteer boosting — no hooks.py needed.

```bash
# During encode, save gazetteer to output
echo '["kubernetes","pod","timeout","oom"]' > /encoded/_gazetteer.json

# At query time, auto-detected:
svc = QueryService("/encoded")
# → "[hooks] Auto-detected gazetteer: 4 terms"
```

### Query Expansion (built on gazetteers)

When a gazetteer contains related terms (e.g., `terror`, `terrorism`, `terrorist`),
the query cleaner hook can expand a query to include all variants:

```
User searches: "terror"
Expansion:     ["terror", "terrorism", "terrorist"]
BSC vector:    superpose(all three) — amplifies signal across all forms
```

This is implemented in the edge hooks (`edge_query_cleaner`) using concept
families derived from the gazetteer. The expansion happens before encoding,
so the BSC vector contains signal for all variants simultaneously.

### Resolvers vs Gazetteers Decision Matrix

```
Is the same real-world entity spelled multiple ways?
  YES → Use a RESOLVER (normalize before encoding)
        Examples: gene symbols, WikiData entities, person names

  NO  → Are there domain terms users will search for?
          YES → Use a GAZETTEER (boost into top-12)
                Examples: threat terms, error codes, medical conditions

          NO  → Use neither (pure IDF handles it)
                Examples: generic text, web crawl, chat logs
```

## Configuration

All tunables in `config.env`. Override via environment variables:

```bash
# Vector space
A81_DIM=16384              # BSC dimensionality
A81_K=128                  # Sparsity (active indices)
A81_MAX_SALIENT_TOKENS=12  # Token budget per vector (sqrt(k))

# Sharding
A81_ENTITY_BUCKETS=4       # Level 1 routing buckets
A81_ACTION_CLUSTERS=20     # Level 2 action clusters
A81_WAVES=4                # Parallel encoding waves

# Query
A81_QUERY_SHARDS=3         # Shards to search per query
A81_QUERY_TOP_K=10         # Default results per query

# Scoring weights (must sum to 100)
A81_WEIGHT_BSC=50          # BSC vector similarity
A81_WEIGHT_KEYWORD=40      # Keyword overlap
A81_WEIGHT_PROXIMITY=10    # Adjacent term bonus

# Gazetteer
A81_GAZETTEER_BOOST=3.0    # IDF multiplier for domain terms

# Paths
A81_SOURCE_PATH=/path/to/staged    # Source data files/directory
A81_INDEX_PATH=/path/to/encoded    # Target encoded output (read+write)
A81_PRODUCT_DIR=/path/to/product   # Product directory containing hooks.py
A81_MEDIA_DIR=                     # Media files (auto-detect if empty)
A81_CLUSTERS_PATH=/path/to/clusters.json  # Cluster definitions
```

### Path Reference

| Variable | Required For | Description |
|---|---|---|
| `A81_SOURCE_PATH` | encode | Where raw input files/directories live (JSONL, JSON, etc.) |
| `A81_INDEX_PATH` | encode + query | Where the encoded holographic matrix is written and read |
| `A81_PRODUCT_DIR` | query | Product directory containing `hooks.py` for query intelligence |
| `A81_MEDIA_DIR` | encode (optional) | Where image/video files live. Empty = auto-detect from source parent |
| `A81_GAZETTEER_PATH` | encode (optional) | Custom gazetteer JSON file. Empty = use product gazetteer |
| `A81_CLUSTERS_PATH` | encode | Cluster definitions from `discover_clusters.py` |

### Configuration Examples

**Default (uses paths from config.env):**

```bash
source config.env
python3 encode_edge.py
```

**Override specific paths for a deployment:**

```bash
A81_SOURCE_PATH=/data/raw_messages \
A81_INDEX_PATH=/data/encoded \
A81_PRODUCT_DIR=/opt/edge_analyst \
python3 encode_edge.py
```

**Multiple environments via separate config files:**

```bash
# config.dev.env
A81_SOURCE_PATH=/Users/me/test_data
A81_INDEX_PATH=/Users/me/test_encoded
A81_ENTITY_BUCKETS=2
A81_ACTION_CLUSTERS=10

# config.prod.env
A81_SOURCE_PATH=/data/production/raw
A81_INDEX_PATH=/data/production/encoded
A81_ENTITY_BUCKETS=8
A81_ACTION_CLUSTERS=40

# Use one or the other
source config.dev.env && python3 encode_edge.py
source config.prod.env && python3 encode_edge.py
```

**Container deployment (docker, kubernetes):**

```yaml
# docker-compose.yml
services:
  a81-encoder:
    image: ga81:latest
    environment:
      A81_SOURCE_PATH: /data/raw
      A81_INDEX_PATH: /data/encoded
      A81_PRODUCT_DIR: /app/product
      A81_DIM: 16384
      A81_ENTITY_BUCKETS: 8
      A81_ACTION_CLUSTERS: 40
    volumes:
      - ./raw:/data/raw:ro
      - ./encoded:/data/encoded
      - ./product:/app/product:ro
```

**Inline override (one-shot encode):**

```bash
A81_SOURCE_PATH=/tmp/new_data A81_INDEX_PATH=/tmp/test_encoded \
  python3 encode/encode.py --clusters /tmp/clusters.json
```

## Deployment

### Linux Server (encode only)

```bash
# Copy EHC/ and G.A8.1/ to server
scp -r EHC/ G.A8.1/ user@server:/opt/

# Build and test
ssh user@server
cd /opt/G.A8.1 && ./install.sh

# Encode
source config.env
python3 encode/encode.py --source /data/input.jsonl \
    --output /data/encoded --clusters /data/clusters.json
```

### Linux Server (encode + query API)

```bash
# Additional: copy product directory
scp -r product.edge.analyst.bsc/ user@server:/opt/

# Install FastAPI deps
pip install fastapi uvicorn pydantic orjson

# Start service
A81_INDEX_PATH=/data/encoded /opt/product.edge.analyst.bsc/edge_service/start.sh
```

### Requirements

| Component | Required | Notes |
|---|---|---|
| Python | 3.9+ | Standard library + numpy |
| CMake | 3.18+ | For building EHC |
| C++ compiler | C++20 | gcc ≥ 10, clang ≥ 12, or Apple Clang |
| numpy | Required | Core dependency |
| Pillow | Optional | Image encoding |
| opencv-python | Optional | Video encoding |
| FastAPI + uvicorn | Optional | Web API (query serving) |

## Performance

Measured on 247,551 social media messages with 33,721 media files:

| Metric | Value |
|---|---|
| Encode speed | 2,500 vectors/sec |
| Encode time (247K) | ~100 seconds |
| Query latency p50 | 16ms |
| Query latency p95 | 41ms |
| Async 3-concurrent | 30ms total (10ms each) |
| Relevance (50 queries) | 82% |
| Precision (top result) | 72% |
| Per-vector storage | 793 bytes |
| 1M vectors projection | ~0.7 GB |
| 10M vectors projection | ~7.4 GB |
| Startup (load 80 shards) | 3 seconds |

## Key Principles

1. **Searchable vs Hidden** — The vector is the address. The sidecar is the house. Never encode paths, URLs, or metadata into the search vector.

2. **√k Token Budget** — With k=128, the superpose majority vote reliably discriminates ~12 independent tokens. This is a physics constraint, not a tuning knob.

3. **All Fields Feed Salience** — Tokenize subject + relation + object. Select top-12 from the full pool. This is why triples (87% Hit@1) and messages (82% relevance) both work.

4. **Gazetteer Guaranteed Slots** — Domain-critical terms always get into the top-12, regardless of IDF. Prevents rare-but-irrelevant words from crowding out important domain terms.

5. **Query Expansion** — "terror" expands to ["terror", "terrorism", "terrorist"] via concept families. Superposition of all variants amplifies signal simultaneously.

6. **Convention Over Configuration** — Drop a `hooks.py`, the engine finds it. Drop a `_gazetteer.json`, salience boosting activates. No manual wiring.

7. **Never Transform Source Data** — The sidecar stores original record fields exactly as ingested. Zero data loss from encode to display.
