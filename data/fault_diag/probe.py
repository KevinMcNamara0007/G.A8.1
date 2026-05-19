"""Probe queries against the encoded hydraulic fault index."""
import sys, os, json
from pathlib import Path

sys.path.insert(0, '/opt/G.A8.1')
sys.path.insert(0, '/opt/EHC/install/linux-x86_64')

from decode.query import QueryService

INDEX = '/opt/G.A8.1/data/fault_diag/encoded_hyd_d512'
svc = QueryService(INDEX)

print(f"INDEX STATS: {svc.stats}\n")

PROBES = [
    ('HYD_COOL_FAIL resolved_by',   'common critical code → solution'),
    ('HYD_VALVE_FAIL resolved_by',  'another common code'),
    ('HYD_PUMP_LEAK_WEAK resolved_by', 'rare code (63 events, 2.9%)'),
    ('HYD_ACCUM_LOW_SLT resolved_by',  'very rare (21 events, 1.0%)'),
    ('HYD_NONEXISTENT_CODE resolved_by', 'cold start - never seen'),
    ('HYD_COOL_FAIL co_occurs_with',   'what does cooler failure co-occur with'),
    ('HYD-RIG-005 reported',         'machine history'),
]

for query_text, note in PROBES:
    print("="*78)
    print(f"QUERY:  {query_text!r}")
    print(f"  ({note})")
    try:
        res = svc.query(query_text, k=5)
    except Exception as e:
        print(f"  ERROR: {e}")
        continue
    print(f"  confidence: {res.get('confidence')}")
    results = res.get('results', [])
    print(f"  {len(results)} hits:")
    for i, r in enumerate(results, 1):
        m = r.get('metadata') or {}
        sim = r.get('similarity')
        subj = m.get('subject', '?'); rel = m.get('relation', '?'); obj = m.get('object', '?')
        meta = {k: m.get(k) for k in ('event_id','machine_id','severity','time_to_fix_min','parts_replaced') if m.get(k) is not None}
        print(f"    {i}. sim={sim:.3f}  ({subj}, {rel})")
        print(f"        → {obj}")
        if meta:
            print(f"        meta: {meta}")
    print()
