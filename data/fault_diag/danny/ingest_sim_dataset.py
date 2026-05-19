"""Ingest adapter: sample_sim_dataset.csv → SRO triples → encoded index.

Reads the CSV format defined in SPEC.md and emits triples using the
dedup+composite pattern we validated (sub-ms p50, 100% fix-correctness
at 100K-event scale). Then runs a few canonical queries to show what
the index serves back.

For Danny: when your MATLAB output lands in this same shape, this script
ingests it without modification. Add or rename columns? Edit the
FEATURE_COLS / METADATA_COLS constants at the top.
"""
import csv
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
CSV_IN     = HERE / 'sample_sim_dataset.csv'
TRIPLES    = HERE / 'sim_triples.jsonl'
ENCODED    = HERE / 'encoded_sim'

# Feature columns — used to build the per-run signature
FEATURE_COLS = [
    'shoulderPitch_q_range','shoulderPitch_qd_zcross','shoulderPitch_tau_maxabs',
    'shoulderRoll_q_range', 'shoulderRoll_qd_zcross', 'shoulderRoll_tau_maxabs',
    'shoulderYaw_q_range',  'shoulderYaw_qd_zcross',  'shoulderYaw_tau_maxabs',
    'elbowPitch_q_range',   'elbowPitch_qd_zcross',   'elbowPitch_tau_maxabs',
]
REQUIRED_COLS = ['run_id','robot_model','injected_fault','severity',
                 'affected_joint','start_ts','duration_s']
METADATA_COLS = REQUIRED_COLS[1:]  # robot_model and downstream — run_id is the key


class IngestError(Exception):
    """Raised on schema validation failure. Message is end-user-facing."""


def validate_rows(rows):
    if not rows:
        raise IngestError(
            "CSV has no data rows. Need at least one row matching the SPEC.md schema."
        )
    missing_required = [c for c in REQUIRED_COLS if c not in rows[0]]
    if missing_required:
        raise IngestError(
            f"CSV is missing required column(s): {missing_required}. "
            f"See SPEC.md for the full schema. Got columns: {list(rows[0].keys())}"
        )
    missing_features = [c for c in FEATURE_COLS if c not in rows[0]]
    if missing_features:
        raise IngestError(
            f"CSV is missing feature column(s): {missing_features}. "
            f"All 12 per-joint feature columns are required for quantization."
        )


# ─── feature quantization ────────────────────────────────────────────
def quantize_features(rows):
    """Compute 33/66 percentile breakpoints per feature → tokens LOW/MID/HIGH."""
    bps = {}
    for col in FEATURE_COLS:
        vals = sorted(float(r[col]) for r in rows)
        n = len(vals)
        bps[col] = (vals[n//3], vals[2*n//3])
    def token_for(col, val):
        lo, hi = bps[col]
        return 'LOW' if val <= lo else ('HIGH' if val > hi else 'MID')
    return token_for, bps


# ─── triple emission ─────────────────────────────────────────────────
def emit_triples(rows, token_for, out_path):
    n_triples = 0
    with open(out_path, 'w') as f:
        for r in rows:
            run_id = r['run_id']
            fault  = r['injected_fault']
            model  = r['robot_model']
            joint  = r['affected_joint']
            sev    = r['severity']

            # Metadata bundle attached to every triple from this row.
            # Strategy: pass through ALL CSV columns, parsing known numerics.
            # Required-cols and features get typed; unknown columns become
            # string metadata Danny can use for reranking / display.
            meta = {}
            for col, val in r.items():
                if col in FEATURE_COLS:
                    meta[col] = float(val) if val != '' else None
                elif col == 'duration_s':
                    meta[col] = float(val) if val != '' else None
                else:
                    meta[col] = val

            # 1) Canonical fault → run (the dominant retrieval key)
            f.write(json.dumps({**meta, 'subject': fault,
                                'relation': 'has_run', 'object': run_id}) + '\n')
            n_triples += 1

            # 2) Composite key: fault@robot_model → run  (fan out cluster ~3×)
            f.write(json.dumps({**meta, 'subject': f'{fault}@{model}',
                                'relation': 'has_run', 'object': run_id}) + '\n')
            n_triples += 1

            # 3) Finer composite: fault@robot_model@joint → run
            if joint and joint != 'none':
                f.write(json.dumps({**meta, 'subject': f'{fault}@{model}@{joint}',
                                    'relation': 'has_run', 'object': run_id}) + '\n')
                n_triples += 1

            # 4) Run → its per-feature signature (for "find similar runs")
            tokens = [f'{col}_{token_for(col, float(r[col]))}' for col in FEATURE_COLS]
            f.write(json.dumps({**meta, 'subject': run_id,
                                'relation': 'has_signature',
                                'object': ' '.join(tokens)}) + '\n')
            n_triples += 1

            # 5) Run → fault label (reverse lookup; useful for "what fault did run X have?")
            f.write(json.dumps({**meta, 'subject': run_id,
                                'relation': 'has_injected_fault', 'object': fault}) + '\n')
            n_triples += 1

            # 6) Fault → severity (so "TORQUE_SPIKE high_severity" type queries work)
            f.write(json.dumps({**meta, 'subject': fault,
                                'relation': 'has_severity', 'object': sev}) + '\n')
            n_triples += 1

    return n_triples


# ─── encode ──────────────────────────────────────────────────────────
def encode_shard(triples_path, out_dir):
    env = {**os.environ,
           'PYTHONPATH': '/opt/EHC/install/linux-x86_64:/opt/G.A8.1'}
    r = subprocess.run(
        ['python3', '-m', 'encode.encode_triples',
         '--source', str(triples_path),
         '--output', str(out_dir),
         '--dim', '512', '--k', '23',
         '--no-autotune', '--force'],
        cwd='/opt/G.A8.1', env=env, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr); sys.exit(1)
    for line in r.stdout.splitlines():
        if any(k in line for k in ('[encode]','[done]')): print(f"  {line}")


# ─── demo queries ────────────────────────────────────────────────────
def demo_queries(out_dir):
    sys.path.insert(0, '/opt/G.A8.1')
    from decode.query import QueryService
    svc = QueryService(str(out_dir))
    print(f"  {svc.stats}\n")

    DEMOS = [
        ('TORQUE_SPIKE has_run',
         'all sim runs with TORQUE_SPIKE injected (top-5)'),
        ('TORQUE_SPIKE@HumanoidArm_v1 has_run',
         'narrow: TORQUE_SPIKE specifically on HumanoidArm_v1'),
        ('TORQUE_SPIKE@HumanoidArm_v1@shoulderRoll has_run',
         'narrower: TORQUE_SPIKE on shoulderRoll of HumanoidArm_v1'),
        ('JOINT_STUCK has_run',
         'all JOINT_STUCK runs (different fault class)'),
        ('NOMINAL has_run',
         'baseline runs (no fault injected)'),
        ('TORQUE_SPIKE has_severity',
         'severity distribution observed for TORQUE_SPIKE'),
    ]
    for query, note in DEMOS:
        print(f"  QUERY: {query!r}")
        print(f"    ({note})")
        res = svc.query(query, k=5)
        if not res['results']:
            print(f"    (no results)\n"); continue
        for i, r in enumerate(res['results'][:5], 1):
            m = r['metadata']
            sim = r['similarity']
            # Show the most-useful metadata depending on relation
            if r['metadata'].get('relation') == 'has_severity':
                line = f"sev={m.get('object', '')}"
            else:
                obj = m.get('object', '')
                line = (f"run={obj}  model={m.get('robot_model','')}  "
                        f"joint={m.get('affected_joint','')}  sev={m.get('severity','')}  "
                        f"τmax={m.get('shoulderRoll_tau_maxabs',0):5.1f}")
            print(f"    {i}. sim={sim:.3f}  {line}")
        print()

    # Show what a "find similar runs to X" lookup looks like
    print(f"  QUERY: signature of sim_0044 →  what runs have a similar signature?")
    sig_res = svc.query('sim_0044 has_signature', k=1)
    if sig_res['results']:
        sig = sig_res['results'][0]['metadata']['object']
        print(f"    sim_0044 signature: {sig}")
        # We'd ideally query by signature tokens to find similar runs; since
        # signatures are unique-per-run, this is more illustrative than useful
        # in the dedup+composite shape. For "find similar windows" the proper
        # path is to embed the query window into the same token bag and
        # query — but that's a separate workflow.


# ─── main ────────────────────────────────────────────────────────────
def main():
    with open(CSV_IN) as f:
        rows = list(csv.DictReader(f))
    print(f"[read]   {len(rows)} sim runs from {CSV_IN}")

    try:
        validate_rows(rows)
    except IngestError as e:
        print(f"\n[error] {e}")
        sys.exit(2)

    # Show class balance — confirm the CSV looks sane
    print(f"[counts] {Counter(r['injected_fault'] for r in rows)}")

    token_for, bps = quantize_features(rows)
    n = emit_triples(rows, token_for, TRIPLES)
    print(f"[triples] wrote {n:,} → {TRIPLES}")

    print(f"\n[encode] D=512, k=23 (canonical) ...")
    encode_shard(TRIPLES, ENCODED)

    print(f"\n[demo queries]")
    demo_queries(ENCODED)


if __name__ == '__main__':
    main()
