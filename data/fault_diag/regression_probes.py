"""Deterministic regression probe — emits JSON of canonical_query / sim / object
for every NL test. Used to byte-diff before vs after refactor.
"""
import sys, json, hashlib
sys.path.insert(0, '/opt/G.A8.1')
sys.path.insert(0, '/opt/G.A8.1/data/fault_diag')

from decode.query import QueryService

PROBES = [
    'cooler failure',
    'the cooling system is broken',
    'coolant degraded efficiency',
    'valve stuck and broken',
    'solenoid responding with severe lag',
    'small lag in valve switching',
    'pump leaking severely from case drain',
    'weak pump seal leak',
    'accumulator dead, no pre-charge',
    'accumulator nitrogen slightly low',
    'HYD_COOL_FAIL',
    'HYD_COOL_FAIL co_occurs_with',
    'battery dead',
]


def run(rewrite_fn, label):
    svc = QueryService('/opt/G.A8.1/data/fault_diag/encoded_hyd_d512')
    out = []
    for q in PROBES:
        rw = rewrite_fn(q)
        res = svc.query(rw.canonical_query, k=1)
        hit = res['results'][0] if res['results'] else None
        out.append({
            'input': q,
            'canonical_query': rw.canonical_query,
            'code': rw.code,
            'relation': rw.relation,
            'filter_score': round(rw.score, 4),
            'top_sim': round(hit['similarity'], 4) if hit else None,
            'top_object': hit['metadata'].get('object', '') if hit else None,
        })
    digest = hashlib.sha256(
        json.dumps(out, sort_keys=True).encode()
    ).hexdigest()[:16]
    return {'label': label, 'digest': digest, 'rows': out}


EXPECTED_DIGEST = '14f142473860f2e7'


if __name__ == '__main__':
    from hooks import rewrite
    result = run(rewrite, 'hooks')
    out_path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/probe_current.json'
    with open(out_path, 'w') as f:
        json.dump(result, f, indent=2)
    ok = result['digest'] == EXPECTED_DIGEST
    print(f"digest={result['digest']}  expected={EXPECTED_DIGEST}  "
          f"rows={len(result['rows'])}  {'OK' if ok else 'REGRESSION'}")
    sys.exit(0 if ok else 1)
