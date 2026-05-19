"""Fault-flow bench against the 517K-triple hefty corpus.

The standard Hit@k harness assumes unique (s, r) → gold_id, which
doesn't fit this corpus shape (many records share the same code+relation
because many machines hit the same fault). So we measure properties
that actually matter for the fault-diag flow:

  1. Fix-correctness@1 — for each code, does the top retrieved
     `object` match the canonical fix for that code?
  2. Top-k machine diversity — does top-10 return events from
     distinct machines (i.e. retrieval isn't degenerately latching
     onto one machine's history)?
  3. NL routing accuracy at scale — does hooks.py rewrite still
     hit the right code when there are 100K events to retrieve from?
  4. Cold-start behavior — what does an unknown code score?
  5. Latency under load — p50/p95/p99 over 1000 queries.
"""
import sys, time, json, statistics
from collections import Counter
sys.path.insert(0, '/opt/G.A8.1')
sys.path.insert(0, '/opt/G.A8.1/data/fault_diag')

from decode.query import QueryService
from hooks import rewrite

INDEX = sys.argv[1] if len(sys.argv) > 1 else '/opt/G.A8.1/data/fault_diag/encoded_hefty_d512'
svc = QueryService(INDEX)
print(f"INDEX: {svc.stats}")

# Canonical expected fixes per code (matches generator FIX_BY_CODE)
EXPECTED_FIX = {
    'HYD_COOL_FAIL':         'Replaced cooler assembly',
    'HYD_COOL_DEGRADED':     'Flushed coolant loop',
    'HYD_VALVE_FAIL':        'Replaced proportional control valve',
    'HYD_VALVE_LAG_SEV':     'Cleaned spool and bore',
    'HYD_VALVE_LAG_SML':     'Changed return-line filter',
    'HYD_PUMP_LEAK_SEV':     'Pulled pump, replaced shaft seal',
    'HYD_PUMP_LEAK_WEAK':    'Replaced shaft seal',
    'HYD_ACCUM_FAIL':        'Replaced accumulator unit',
    'HYD_ACCUM_LOW_SEV':     'Recharged accumulator',
    'HYD_ACCUM_LOW_SLT':     'Topped up accumulator',
    'HYD_UNSTABLE':          'Allowed system to warm',
    'HYD_FILTER_CLOG_HIGH':  'Replaced primary and return-line filter',
    'HYD_FLUID_CONTAM':      'Drained, flushed, and refilled',
    'HYD_TEMP_HIGH':         'Cleared blocked cooler intake',
    'HYD_PRESS_OSCILLATION': 'Replaced relief valve',
    'HYD_MOTOR_VIBRATION':   'Replaced motor bearings',
}

# ─── 1. Fix-correctness@1 — all 16 codes ────────────────────────
print("\n" + "="*70)
print("1. FIX-CORRECTNESS@1 — does top result give the right fix?")
print("="*70)
correct = 0
in_catalog = []
out_catalog = []
LEXICAL_CATALOG = {'HYD_COOL_FAIL','HYD_COOL_DEGRADED','HYD_VALVE_FAIL','HYD_VALVE_LAG_SEV',
                   'HYD_VALVE_LAG_SML','HYD_PUMP_LEAK_SEV','HYD_PUMP_LEAK_WEAK',
                   'HYD_ACCUM_FAIL','HYD_ACCUM_LOW_SEV','HYD_ACCUM_LOW_SLT','HYD_UNSTABLE'}
for code, expect in EXPECTED_FIX.items():
    res = svc.query(f"{code} resolved_by", k=1)
    obj = res['results'][0]['metadata'].get('object', '') if res['results'] else ''
    sim = res['results'][0]['similarity'] if res['results'] else 0
    ok = expect.lower() in obj.lower()
    correct += int(ok)
    flag = '' if code in LEXICAL_CATALOG else '  (outside lexical catalog)'
    print(f"  {'✓' if ok else '✗'} {code:25s} sim={sim:.3f}{flag}")
print(f"\n  Total: {correct}/{len(EXPECTED_FIX)} = {100*correct/len(EXPECTED_FIX):.1f}%")

# ─── 2. Top-k machine diversity ─────────────────────────────────
print("\n" + "="*70)
print("2. TOP-10 MACHINE DIVERSITY — does retrieval span the fleet?")
print("="*70)
diversity_scores = []
for code in ['HYD_COOL_FAIL', 'HYD_VALVE_LAG_SML', 'HYD_TEMP_HIGH', 'HYD_ACCUM_FAIL']:
    res = svc.query(f"{code} resolved_by", k=10)
    mids = [r['metadata'].get('machine_id') for r in res['results']]
    models = [r['metadata'].get('machine_model') for r in res['results']]
    n_distinct_machines = len(set(mids))
    n_distinct_models = len(set(models))
    diversity_scores.append(n_distinct_machines)
    print(f"  {code:25s} → {n_distinct_machines}/10 distinct machines, "
          f"{n_distinct_models}/5 distinct models")

# ─── 3. NL routing through hooks.py ─────────────────────────────
print("\n" + "="*70)
print("3. NL ROUTING ACCURACY @ SCALE — hooks.py → retrieval")
print("="*70)
NL_PROBES = [
    ('cooler failure',                'HYD_COOL_FAIL'),
    ('the cooling system is broken',  'HYD_COOL_FAIL'),
    ('valve stuck and broken',        'HYD_VALVE_FAIL'),
    ('solenoid responding with severe lag', 'HYD_VALVE_LAG_SEV'),
    ('pump leaking severely',         'HYD_PUMP_LEAK_SEV'),
    ('accumulator dead',              'HYD_ACCUM_FAIL'),
    ('accumulator nitrogen slightly low', 'HYD_ACCUM_LOW_SLT'),
]
nl_correct = 0
for nl, expected_code in NL_PROBES:
    rw = rewrite(nl)
    res = svc.query(rw.canonical_query, k=1)
    obj = res['results'][0]['metadata'].get('object', '') if res['results'] else ''
    expected_obj = EXPECTED_FIX[expected_code]
    ok = (rw.code == expected_code) and (expected_obj.lower() in obj.lower())
    nl_correct += int(ok)
    print(f"  {'✓' if ok else '✗'} {nl!r:42s} → {rw.code}  →  {obj[:50]!r}")
print(f"\n  Total: {nl_correct}/{len(NL_PROBES)} = {100*nl_correct/len(NL_PROBES):.1f}%")

# ─── 4. Cold-start ──────────────────────────────────────────────
print("\n" + "="*70)
print("4. COLD-START — codes not in corpus")
print("="*70)
for unknown in ['HYD_GARBLED_FOO', 'HYD_TOTALLY_UNKNOWN', 'P0420_resolved_by']:
    res = svc.query(f'{unknown} resolved_by', k=1)
    sim = res['results'][0]['similarity'] if res['results'] else 0
    obj = res['results'][0]['metadata'].get('object','')[:60] if res['results'] else 'none'
    print(f"  {unknown:25s} sim={sim:.3f}  top_obj={obj!r}")

# ─── 5. Latency under load ──────────────────────────────────────
print("\n" + "="*70)
print("5. LATENCY UNDER LOAD — 2000 queries")
print("="*70)
import random
random.seed(11)
all_codes = list(EXPECTED_FIX.keys())
ts = []
for _ in range(2000):
    code = random.choice(all_codes)
    rel = random.choice(['resolved_by','requires_part','occurs_on','co_occurs_with'])
    t = time.perf_counter()
    svc.query(f"{code} {rel}", k=10)
    ts.append((time.perf_counter()-t)*1000)
ts.sort()
print(f"  n=2000 queries (k=10)")
print(f"  p50 = {ts[1000]:.2f} ms")
print(f"  p95 = {ts[1900]:.2f} ms")
print(f"  p99 = {ts[1980]:.2f} ms")
print(f"  max = {ts[-1]:.2f} ms")
print(f"  qps = {2000 / sum(ts) * 1000:.0f}")
