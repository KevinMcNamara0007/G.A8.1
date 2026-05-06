# G.A8.1 — Internet Subspace Modality Migration Guide

This document describes the four Internet Subspace modalities (M1–M4)
defined in the whitepaper and gives a precise procedure for migrating a
corpus from one modality to the next. The detailed worked example is
**M1 → M2** (datacenter encode → edge inference), since that is the
first transition most operators run and it exercises every script and
config artifact in the system.

---

## 1. Modality overview

The four modalities sit on a spectrum from *operationally familiar* to
*architecturally novel*. Each strictly extends the security claims of
its predecessor and reuses the same G.A8.1 substrate.

| #  | Name           | Codebook lives | Compute happens | New trust claim                                | Wired today |
|----|----------------|----------------|-----------------|------------------------------------------------|-------------|
| M1 | **Halo DC**    | DC             | DC              | none — single trust domain                     | full        |
| M2 | **Edge DC**    | edge (after import) | edge        | bundle integrity + edge inference              | thin cut    |
| M3 | **Entangled DC** | edge         | remote DC       | subspace privacy: codebook ↔ compute split     | thin cut    |
| M4 | **Edge ↔ Edge** | edge          | public infra (BitNet 2.5) | end-to-end ternary, anonymous inference | scaffold    |

### Trust model in one paragraph each

- **M1 Halo DC.** Everything (encode, indices, codebook, query) runs
  inside one customer-controlled boundary. The subspace privacy claim
  exists in the substrate but is not exercised. Operationally identical
  to a normal on-prem AI deployment.

- **M2 Edge DC.** A central encoder produces a signed (or
  ssh-authenticated unsigned) bundle and ships it to one or more edge
  devices. The edge runs disconnected or intermittently connected. The
  central operator and the edge operator are still inside the same
  trust boundary — M2 protects against accidental tampering and
  geographic separation, not against the edge operator.

- **M3 Entangled DC.** The codebook and inverted indices stay at the
  edge under direct customer control. Encoded ternary VSAs travel over
  TLS 1.3 to a remote similarity processor on commodity / sovereign /
  partner infrastructure. The remote operator cannot decode queries,
  candidates, or results without the codebook. **First modality where
  the subspace privacy claim is load-bearing.**

- **M4 Edge ↔ Edge.** Same posture as M3, but the remote endpoint is a
  ternary-native generative LLM (Microsoft BitNet 2.5 trained on EH
  VSAs) rather than a similarity-only service. End-to-end ternary
  computation; the customer is mathematically anonymous to the
  inference provider beyond network metadata.

---

## 2. Common prerequisites

Before any modality migration, both the source and target hosts need:

1. **Python 3.9 or newer** with `numpy` available.
2. **EHC native library** built for the host's `(os, arch)`. Use the
   `build_eh.sh` script in this directory.
3. **G.A8.1 source tree** (this directory) checked out to the same
   release on both hosts.
4. **`config.env`** at the G.A8.1 root populated with the right
   modality and paths. Per-modality overlays live in `configs/`.

### Build EHC on this host

```bash
cd /path/to/G.A8.1
./build_eh.sh                   # release build, installs nanobind bindings
# or
./build_eh.sh --debug           # debug build
./build_eh.sh --tests           # also build EHC unit/parity tests
```

The script auto-detects `(darwin|linux) × (arm64|x86_64)`, picks Ninja
when available, builds into `EHC/build-<os>-<arch>/`, and installs the
nanobind Python wheel via `pip install --user`. Per-platform build
dirs prevent macOS-developer and Linux-edge builds from clobbering
each other on shared filesystems.

### Confirm the install

```bash
python3 -c "from config import cfg; print(cfg.summary())"
```

Expected output (defaults):

```
modality=halo_dc role=hybrid D=16384 k=128 salient=12 shards=4×20=80 \
LSH=8t/16b query=3sh/10k weights=50/40/10 gaz_boost=3.0 kms=none
```

---

## 3. M1 → M2 migration (worked example)

This is the procedure to take a corpus encoded in your datacenter (M1)
and run inference on it from an edge device (M2). The transport is
SSH; the bundle is unsigned by default (per-file SHA-256 still
catches bit rot, and SSH gives you channel authenticity).

### 3.1 Phase A — Datacenter (M1) preparation

Assume your DC host has G.A8.1 installed and your corpus encoded.
Concretely, that means:

| Path                                  | Contents                                       |
|---------------------------------------|------------------------------------------------|
| `$A81_SOURCE_PATH/corpus.jsonl`       | source records (one JSON per line)             |
| `$A81_INDEX_PATH/`                    | encoded shards, indices, sidecar, **profile**  |
| `$A81_INDEX_PATH/corpus_profile.json` | D, k, salient_tokens chosen by the v13.1 profiler |
| `$A81_INDEX_PATH/centroids.json`      | action-cluster centroids                       |
| `$A81_INDEX_PATH/clusters.json`       | discovered action clusters                     |
| `$A81_INDEX_PATH/structural_v13/…`    | per-shard binary indices + cfg                 |

If you do not yet have an encoded corpus, run the standard pipeline.
Note the **D coordination** between steps: the profiler picks the
recommended D, and the cluster discovery + encode steps must use the
same D (`discover_clusters.py` does not auto-read the profile).

```bash
cd /path/to/G.A8.1
export A81_MODALITY=halo_dc
export A81_SOURCE_PATH=/data/corpus.jsonl
export A81_INDEX_PATH=/data/encoded

mkdir -p "$A81_INDEX_PATH"

# Step 1: pre-encode corpus profiler (writes corpus_profile.json)
python3 -m encode.profile \
    --source "$A81_SOURCE_PATH" \
    --output "$A81_INDEX_PATH"

# Step 2: extract the recommended D from the profile so discover and
# encode use the same dimension as the encoded vectors will live at.
DIM=$(python3 -c "
import json, sys
with open('$A81_INDEX_PATH/corpus_profile.json') as f:
    print(json.load(f)['recommended_dim'])
")
echo "profiler chose D=$DIM"

# Step 3: discover action clusters at the profile's D
python3 encode/discover_clusters.py \
    --source "$A81_SOURCE_PATH" \
    --sample 200000 \
    --n-clusters 50 \
    --output "$A81_INDEX_PATH/clusters.json" \
    --dim "$DIM"

# Step 4: two-tier encode. encode.py reads corpus_profile.json and uses
# the profiler's D/k automatically — do NOT pass --dim or --k unless you
# explicitly intend to override the profiler.
python3 encode/encode.py \
    --source "$A81_SOURCE_PATH" \
    --output "$A81_INDEX_PATH" \
    --clusters "$A81_INDEX_PATH/clusters.json" \
    --entity-buckets 36
```

### 3.2 Phase B — Verify M1 health before shipping

A bundle made from a broken corpus is just as broken on the edge.
First, structural-verify the encoded directory:

```bash
# Confirm the landmarks the bundle/edge will need
ls -1 "$A81_INDEX_PATH"/corpus_profile.json \
       "$A81_INDEX_PATH"/clusters.json \
       "$A81_INDEX_PATH"/centroids.json 2>&1 | head

# Confirm the expected number of shards exist (try v13-tier-routed layout first,
# fall back to legacy structural_v13/ single-shard layout)
SHARDS=$(ls -1d "$A81_INDEX_PATH"/shard_* 2>/dev/null | wc -l)
if [ "$SHARDS" -eq 0 ]; then
    [ -d "$A81_INDEX_PATH/structural_v13" ] && SHARDS=1
fi
echo "shards on disk: $SHARDS"

# Inspect the chosen geometry
python3 -c "
import json
with open('$A81_INDEX_PATH/corpus_profile.json') as f:
    p = json.load(f)
print('D=', p['recommended_dim'], 'k=', p['recommended_k'])
"
```

Then, if your deployment uses the legacy edge query adapter
(`decode.query_service`), it expects an additional `corpus.jsonl`
sidecar generated by `decode13/eval/run_edge_benchmark.py`. The v13
native query path (`decode13.query_service`) reads the per-shard
sidecar files written by `encode.py` directly. Choose the smoke test
that matches what your edge runtime will use:

```bash
# Option A — v13 native (no extra sidecar needed)
python3 -c "
import sys; sys.path.insert(0, '.')
from decode13.query_service import QueryService
svc = QueryService('$A81_INDEX_PATH')
print(svc.stats() if callable(getattr(svc, 'stats', None)) else 'svc loaded')
"

# Option B — legacy edge adapter (requires corpus.jsonl alongside structural_v13/)
ls "$A81_INDEX_PATH/corpus.jsonl" >/dev/null 2>&1 && \
python3 -c "
import sys; sys.path.insert(0, '.')
from decode.query_service import QueryService
svc = QueryService('$A81_INDEX_PATH')
print('vectors:', svc.stats.get('total_vectors'))
" || echo "corpus.jsonl not present — skip Option B or run run_edge_benchmark first"
```

### 3.3 Phase C — Set up the edge host

On the edge host, install G.A8.1 and build EHC for the edge's
architecture (which may differ from the DC's):

```bash
# On the edge:
git clone <your-G.A8.1-repo>     # or rsync the directory
cd /path/to/G.A8.1
./build_eh.sh                    # builds EHC for the edge's (os, arch)

# Confirm config loads
python3 -c "from config import cfg; print(cfg.summary())"
```

Set up SSH key-based access from the DC to the edge:

```bash
# On the DC:
ssh-copy-id user@edge.host
ssh user@edge.host 'echo connection-ok'   # should print without password
```

### 3.4 Phase D — Ship the bundle

Back on the DC, with `$A81_INDEX_PATH` set to the source you want to
ship and the G.A8.1 directory as your CWD:

```bash
cd /path/to/G.A8.1

# The remote's G.A8.1 directory; default is $HOME/G.A8.1
export A81_REMOTE_DIR=/opt/g_a8_1

# Single command does: profile-gate check → bundle export →
# scp → remote import → cleanup. Bundle is unsigned over SSH.
./ship_to_edge.sh user@edge.host /var/lib/edge/encoded
```

You will see output like:

```
[1/5] resolving plan
      local INDEX_PATH    = /data/encoded
      remote target       = user@edge.host:/var/lib/edge/encoded
      bundle              = /tmp/a81-bundle-3f9a8b21cc7e4d10.tar  (unsigned)
[2/5] exporting bundle
exported bundle_id=… files=N profile=yes unsigned -> /tmp/a81-bundle-….tar
[3/5] transferring over SSH (scp)
[4/5] importing on edge
imported bundle_id=… files=N profile=yes unsigned -> /var/lib/edge/encoded
[5/5] cleanup
✓ ship_to_edge: bundle … delivered to user@edge.host:/var/lib/edge/encoded
```

If anything fails, the script aborts before clobbering edge state.

### 3.5 Phase D-alt — Manual ship (if you cannot use ship_to_edge.sh)

If your environment blocks `ssh ... bash -s <<EOF` patterns (some
hardened jump hosts strip stdin), run the three steps separately:

```bash
# 1. On DC — export
A81_BUNDLE_PATH=/tmp/bundle.tar \
A81_INDEX_PATH=/data/encoded \
python3 -m tools.bundle_export --unsigned

# 2. Transfer (substitute your transport — scp, rsync, removable media)
scp /tmp/bundle.tar user@edge.host:/tmp/

# 3. On edge — import
ssh user@edge.host
cd /opt/g_a8_1
A81_MODALITY=edge_dc \
A81_ROLE=edge \
A81_BUNDLE_PATH=/tmp/bundle.tar \
A81_INDEX_PATH=/var/lib/edge/encoded \
A81_BUNDLE_VERIFY_ON_LOAD=false \
A81_KMS_PROVIDER=none \
python3 -m tools.bundle_import
```

### 3.6 Phase E — Verify on the edge

Repeat the structural checks from Phase B against the edge's
`INDEX_PATH`:

```bash
ssh user@edge.host
cd /opt/g_a8_1

EDGE_INDEX=/var/lib/edge/encoded

# Same landmarks Phase B verified
ls -1 "$EDGE_INDEX"/corpus_profile.json \
       "$EDGE_INDEX"/clusters.json \
       "$EDGE_INDEX"/centroids.json

# Shard count matches DC
EDGE_SHARDS=$(ls -1d "$EDGE_INDEX"/shard_* 2>/dev/null | wc -l)
if [ "$EDGE_SHARDS" -eq 0 ]; then
    [ -d "$EDGE_INDEX/structural_v13" ] && EDGE_SHARDS=1
fi
echo "edge shards: $EDGE_SHARDS"

# Profile matches DC's chosen geometry
python3 -c "
import json
with open('$EDGE_INDEX/corpus_profile.json') as f:
    p = json.load(f)
print('D=', p['recommended_dim'], 'k=', p['recommended_k'])
"
```

The shard count and `(D, k)` must match what Phase B printed. If they
do, the migration is structurally complete; run the same query smoke
test you used in Phase B (Option A or Option B depending on which
edge adapter you deploy) and confirm the top hit matches the DC's
top hit on the same query.

### 3.7 Phase F — Subsequent updates

The bundle protocol records a `bundle_id` per ship. To deliver an
updated corpus to the same edge, repeat Phase D — the importer will
overlay the new files on top of the existing `$A81_INDEX_PATH`.

> **Not yet wired**: incremental delta bundles. Today's import re-ships
> the full corpus. The `A81_BUNDLE_DELTA_BASE` env var is parsed but
> the differential pack format is on the M2-hardening list.

### 3.8 Optional — Sign the bundle

If your transport is not SSH-authenticated (e.g., S3 + URL exchange,
sneakernet to a third party), opt into KMS signing:

```bash
# On DC — set KMS provider before ship
export A81_KMS_PROVIDER=qkey
export A81_QKEY_URL=https://qkey.your.org/qkey
export A81_QKEY_ACCESS_KEY_FILE=/etc/qkey/access.key
export A81_QKEY_MODE=omega
export A81_BUNDLE_SIGNING_KEY_REF=bundle/signing/v1
export A81_BUNDLE_SIGN=true

./ship_to_edge.sh user@edge.host /var/lib/edge/encoded
```

The edge needs the **same KMS configuration** (same `A81_QKEY_URL`,
same access key, same `BUNDLE_SIGNING_KEY_REF` value) so it can derive
the same HMAC key and verify. With `qkey`, both sides hit the same
OneShot endpoint and the key is regenerated identically per ref. With
`local`, the contents of `$A81_KMS_LOCAL_DIR` must be transferred to
the edge alongside the bundle (and `local` is dev-only, so this is not
recommended for production).

---

## 4. M1/M2 → M3 migration

M3 introduces the **processor / client split**. The encoded ternary
VSAs move to a *processor* node that holds them in memory and runs
similarity. The codebook + indices + sidecar stay on n *client* nodes.
Clients encode queries locally, ship ternary VSAs to the processor
over an SSH tunnel, get ranked `(shard_id, slot_id, score)` tuples
back, look up source content from the local sidecar.

### M1→M3 and M2→M3 are the same procedure

Whether the encoded data starts in the DC (M1) or already on an edge
(M2), the M3 transition is operationally identical:

1. Stand up a processor node.
2. Upload encoded shards to it.
3. Designate one or more nodes as clients (the DC, the existing edge,
   or any newly-provisioned customer-controlled box).
4. Open SSH tunnels from each client to the processor.
5. Repoint the client's query path through the M3 wire.

The only difference is *where the encoded data physically starts the
journey* — DC disk for M1→M3, edge disk for M2→M3. Steps 1–5 are the
same.

### Three structural guarantees

These hold by construction; they are not flag-gated and they cannot be
turned off:

1. **Processor has no codebook.** `transport/remote_processor.py` does
   not import, accept, or hold a codebook. The class has no surface to
   receive one. Verifiable: `grep -i 'codebook' transport/remote_processor.py`
   returns only the assertion that it doesn't.
2. **Clients own the codebook.** Each client runs the existing G.A8.1
   query path locally (with codebook on disk under `INDEX_PATH`) and
   uses `transport.edge_client.EdgeClient` as a thin HTTP client. The
   codebook never crosses the wire in either direction.
3. **Codebook update sharing is Day 2.** Multiple clients staying in
   sync as the codebook evolves needs a peer-to-peer (client-to-client,
   never via processor) sync protocol. Not yet built; will reuse the
   M2 bundle primitives over SSH when it lands.

### Channel privacy = SSH (default) or HTTPS

Channel privacy is delegated to the OS: sshd or libssl. The default is
**SSH-tunnel**, where the processor binds 127.0.0.1 only, the client
opens an SSH local-forward, and EdgeClient connects to the local
forwarded port over plain HTTP inside the tunnel. SSH handles KEX,
AEAD, integrity, and host-key trust via known_hosts. No app-level TLS
code path runs.

The HTTPS path remains for cases where SSH-tunnel isn't applicable
(e.g., processor behind a vendor LB that won't allow tunnels). It
enforces TLS 1.3, but cert pinning is a known gap (urllib limitation);
SSH-tunnel sidesteps that via known_hosts.

### 4.1 Phase A — Stand up the processor

On a host (commodity cloud, sovereign cloud, partner DC — anything you
can SSH into), install G.A8.1 and EHC. The processor needs the same
G.A8.1 codebase as a client; the runtime profile differs (no codebook,
no sidecar on disk).

```bash
# On the processor host:
git clone <your-G.A8.1-repo> /opt/g_a8_1
cd /opt/g_a8_1
./build_eh.sh                    # builds EHC for the processor's (os, arch)

# Bind the WSGI app to 127.0.0.1 ONLY. SSH provides the public ingress.
python3 -c "
from transport.remote_processor import RemoteProcessor, RemoteProcessorConfig, serve
proc = RemoteProcessor(RemoteProcessorConfig(pin_mode='session'))
serve(proc, host='127.0.0.1', port=8443)
" &
```

Confirm the listener is loopback-only:

```bash
ss -ltnp | grep 8443
# expect: 127.0.0.1:8443  (NOT 0.0.0.0:8443)
```

> **Not yet wired**: shard upload over the wire. Today the processor's
> `load_shard()` is a Python API only — production initialization
> requires a separate operator-side script that reads encoded shards
> from disk on the processor host. The proper upload protocol (M3
> hardening) lands later.

### 4.2 Phase B — Stand up a client

On any client node (DC for M1→M3, existing edge for M2→M3, new node
for fleet expansion), install G.A8.1 and ensure the codebook +
sidecar live in `$A81_INDEX_PATH`:

```bash
cd /opt/g_a8_1
./build_eh.sh

# Verify the codebook artifacts are present
ls "$A81_INDEX_PATH"/corpus_profile.json \
    "$A81_INDEX_PATH"/clusters.json \
    "$A81_INDEX_PATH"/centroids.json
```

If you already migrated this node through M2, the artifacts are
already in place from `ship_to_edge.sh`. If you're coming straight
from M1 (no edge ever set up), run the encode pipeline as in §3.1
and the artifacts will land at `$A81_INDEX_PATH`.

### 4.3 Phase C — Open the SSH tunnel

```bash
# On the client:
./tunnel_to_processor.sh open user@processor.host
# Output ends with the assigned local port, e.g. 18443
```

The script emits the env vars to set:

```bash
export A81_REMOTE_TRANSPORT=ssh-tunnel
export A81_REMOTE_URL=http://127.0.0.1:18443
```

The tunnel is daemonized; PID file lives under `/tmp/a81-tunnel-<sha8>.pid`.
Tear it down later with `./tunnel_to_processor.sh close user@processor.host`.

### 4.4 Phase D — Configure the client for entangled_dc

```bash
# On the client:
export A81_MODALITY=entangled_dc
export A81_ROLE=edge
export A81_REMOTE_TRANSPORT=ssh-tunnel
export A81_REMOTE_URL=http://127.0.0.1:18443    # from Phase C

# Subspace statistical hardening (config-validated; not yet applied to wire).
# These are SEPARATE from channel privacy (SSH) and structural privacy
# (codebook stays on client). They're left at default-on so the validator
# accepts the modality; the actual rotation/blinding code is Day 2 hardening.
export A81_BASIS_ROTATION=true
export A81_BLINDING=true

# Validate config
python3 -c "
import sys; sys.path.insert(0, '.')
from config import cfg
cfg.assert_ready_for('entangled_dc')
print(cfg.summary())
"
```

### 4.5 Phase E — Smoke test the wire round-trip

```bash
# On the client:
python3 << 'PY'
import sys, numpy as np
sys.path.insert(0, '.')
from transport.edge_client import EdgeClient, EdgeClientConfig
from transport.wire import ProfileMetadata
import os, json

# Read the corpus profile to know the right (D, k)
with open(os.environ['A81_INDEX_PATH'] + '/corpus_profile.json') as f:
    p = json.load(f)
dim, k = p['recommended_dim'], p['recommended_k']

client = EdgeClient(
    EdgeClientConfig(
        remote_url=os.environ['A81_REMOTE_URL'],
        transport=os.environ['A81_REMOTE_TRANSPORT'],
    ),
    ProfileMetadata(dim=dim, k=k, source_hash='client-A'),
)

# Synthetic ternary query — replace with a real codebook-encoded VSA in production.
v = np.zeros(dim, dtype=np.int8)
idx = np.random.default_rng(0).choice(dim, size=k, replace=False)
v[idx] = np.random.default_rng(1).choice([-1, 1], size=k).astype(np.int8)

print('health:', client.health())
resp = client.query(v, top_k=5)
print('hits:', resp.hits)
PY
```

If `health` returns a JSON dict (`{"shards": …, "vectors": …, …}`)
and `query` returns a `QueryResponse` (possibly with empty hits if no
shards are loaded yet on the processor), the wire is correct
end-to-end. Empty hits at this stage is expected — shard upload is Day 2.

### 4.6 Status

| Component                        | Wired? |
|----------------------------------|--------|
| Processor has no codebook        | **structural** (cannot be turned off) |
| Clients own codebook             | **structural** |
| Ternary VSA wire format          | yes    |
| SSH-tunnel transport             | yes    |
| HTTPS transport (TLS 1.3 floor)  | yes    |
| Per-session profile pinning      | yes    |
| EdgeClient round-trip            | yes    |
| Shard upload from client→processor | **no** (next M3 hardening item) |
| Sliding-window basis rotation    | **no** (subspace statistical hardening) |
| Per-query blinding mask          | **no** (subspace statistical hardening) |
| TLS SPKI cert-pinning hook       | **no** (urllib limitation; use SSH-tunnel) |
| Codebook-update sharing (n clients in sync) | **no** (Day 2) |

---

## 5. M3 → M4 migration (scaffold only)

M4 replaces the remote similarity processor with a ternary-native
generative LLM. The validation track is a T5 distilled on EH VSAs;
the production track is BitNet 2.5 with embeddings stripped and
direct VSA processing. Neither is wired today.

```bash
export A81_MODALITY=edge_to_edge
export A81_LLM_PROVIDER=none                 # only valid value at this stage
python3 -c "from config import cfg; cfg.assert_ready_for('edge_to_edge')"
```

`A81_LLM_PROVIDER=t5_validation` and `A81_LLM_PROVIDER=bitnet25` will
be accepted once the bridge model and remote LLM endpoint land.
`assert_ready_for(edge_to_edge)` raises `ConfigError` for any other
value today, by design.

---

## 6. Status snapshot

What's wired today:

| Capability                                  | Module / file                                  |
|---------------------------------------------|------------------------------------------------|
| Modality overlay loader                     | `config.py:_load_modality_overlay`             |
| `cfg.assert_ready_for(modality)`            | `config.py`                                    |
| KMS provider abstraction (none/local)       | `kms.py`                                       |
| M2 bundle export (signed and unsigned)      | `tools/bundle_export.py`                       |
| M2 bundle import + per-file SHA-256 verify  | `tools/bundle_import.py`                       |
| M2 ssh ship helper                          | `ship_to_edge.sh`                              |
| EHC native build helper                     | `build_eh.sh`                                  |
| M3 sparse-ternary wire format               | `transport/wire.py`                            |
| M3 edge client (transport-aware)            | `transport/edge_client.py`                     |
| M3 remote processor + profile pinning       | `transport/remote_processor.py`                |
| M3 SSH-tunnel helper                        | `tunnel_to_processor.sh`                       |

Day 2 (deferred — out of scope for current sprint):

- OneShot/qkey REST client (`kms.py:QKeyProvider`) — works but frozen;
  production KMS moves to OS-level (PKCS#11 / kernel keyring /
  systemd credential).
- Codebook-update sharing among n clients (peer-to-peer over SSH).

Not yet wired (M2/M3 hardening, separate sprint):

- M2 incremental delta bundles
- M2 payload encryption (`A81_BUNDLE_ENC_KEY_REF` is parsed, unused)
- M3 shard upload from client→processor over the wire (today: Python API only)
- M3 sliding-window basis rotation (subspace statistical hardening)
- M3 per-query blinding mask (subspace statistical hardening)
- M3 TLS SPKI pinning hook (urllib limitation; use SSH-tunnel instead)
- M4 T5 / BitNet 2.5 bridge

---

## 7. Troubleshooting

### `corpus_profile.json missing`

The v13.1 profiler did not run. Run it:

```bash
python3 -m encode.profile --source "$A81_SOURCE_PATH" --output "$A81_INDEX_PATH"
```

Or, if you intentionally want to ship without a profile (not
recommended; edge cannot reprofile):

```bash
A81_BUNDLE_INCLUDE_PROFILE=false ./ship_to_edge.sh user@edge.host
```

### `bundle signature verification FAILED`

The edge derived a different signing key than the DC. With `local`
KMS, this means `$A81_KMS_LOCAL_DIR` differs between hosts. With the
Day-2 `qkey` provider, the access key, URL, mode, or signing key ref
differs across hosts. For the active path (M1→M2 over SSH), bundles
are unsigned by default and this error doesn't apply.

### `transport=ssh-tunnel refuses non-loopback host`

EdgeClient was given a non-127.0.0.1 / non-localhost URL while in
SSH-tunnel mode. The fix is to open the tunnel first
(`./tunnel_to_processor.sh open user@host`) and point
`A81_REMOTE_URL` at the local forwarded port (e.g.
`http://127.0.0.1:18443`). Or, if you genuinely want direct HTTPS
without a tunnel, set `A81_REMOTE_TRANSPORT=https` and an `https://…`
URL.

### `A81_BUNDLE_VERIFY_ON_LOAD=true but bundle is unsigned`

The DC shipped an unsigned bundle (the M1→M2 default) but the edge
config asks to verify signatures. Either re-ship signed (set
`A81_BUNDLE_SIGN=true` on DC), or set `A81_BUNDLE_VERIFY_ON_LOAD=false`
on the edge. The importer will not silently downgrade.

### `entangled_dc REQUIRES A81_CODEBOOK_LOCATION=edge`

You set `A81_MODALITY=entangled_dc` but left
`A81_CODEBOOK_LOCATION=local` (the M1 default). The validator refuses
because moving the codebook off-edge collapses the M3 privacy claim.
The `configs/entangled_dc.env` overlay sets this correctly; ensure
nothing in your process env is overriding it.

### `entangled_dc REQUIRES A81_BASIS_ROTATION=true` / `A81_BLINDING=true`

Same shape: a process env var has overridden the overlay's defaults.
These defenses are mandatory in M3 per whitepaper §8.3 and §8.4.

### `LLM_PROVIDER='bitnet25' is not yet supported`

M4 is scaffold-only. Until the BitNet bridge lands, only
`A81_LLM_PROVIDER=none` is accepted. The error is intentional, not a
bug.

---

## 8. References

- Internet Subspace whitepaper: `Internet_Subspace_Whitepaper.docx`
- Per-modality overlays: `configs/halo_dc.env`, `configs/edge_dc.env`,
  `configs/entangled_dc.env`, `configs/edge_to_edge.env`
- Test suites: `tests/test_bundle.py` (7 tests), `tests/test_transport.py` (9 tests)
- KMS / OneShot integration: `kms.py`, source at
  `../MjolnirPhotonics/product.quantum.oneshot/`
