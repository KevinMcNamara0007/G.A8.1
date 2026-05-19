"""Stream-generate a hefty fault-diagnosis corpus for scale testing.

Uses existing UCI-derived events as per-class signature templates, then
synthesizes N new events with machine-model variety, timestamp spread,
secondary code co-occurrence, and codes outside the lexical catalog
(testing cold-start at scale).

Emits SRO triples directly — no intermediate event/resolution JSONL —
to keep disk modest. ~5–6 triples per event.
"""
import json
import random
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

random.seed(2026_05_19)

SRC_EVENTS = '/opt/G.A8.1/data/fault_diag/hyd_events.jsonl'
SRC_RES    = '/opt/G.A8.1/data/fault_diag/hyd_resolutions.jsonl'
OUT_PATH   = '/opt/G.A8.1/data/fault_diag/hefty_triples.jsonl'

N_EVENTS_TARGET = 100_000

# ─── Machine model fleet ──────────────────────────────────────────
MACHINE_MODELS = [
    ('HYDRAULIC_TEST_RIG_ZEMA_v1',    100),  # name, count
    ('HYDRAULIC_PRESS_SIEMENS_X300',   80),
    ('HYDRAULIC_ACTUATOR_PARKER_PA50',120),
    ('HYDRAULIC_PUMP_BOSCH_BR15',      90),
    ('HYDRAULIC_VALVE_REXROTH_R7',    110),
]
MACHINES = []
for model, n in MACHINE_MODELS:
    prefix = model.split('_')[1][:4].upper()
    for i in range(n):
        MACHINES.append((f'{prefix}-{i:04d}', model))

# ─── Codes — 11 from lexical catalog + 5 codes outside it (cold-start probes) ──
CATALOG_CODES = [
    'HYD_COOL_FAIL', 'HYD_COOL_DEGRADED',
    'HYD_VALVE_FAIL', 'HYD_VALVE_LAG_SEV', 'HYD_VALVE_LAG_SML',
    'HYD_PUMP_LEAK_SEV', 'HYD_PUMP_LEAK_WEAK',
    'HYD_ACCUM_FAIL', 'HYD_ACCUM_LOW_SEV', 'HYD_ACCUM_LOW_SLT',
    'HYD_UNSTABLE',
]
EXTRA_CODES = [
    'HYD_FILTER_CLOG_HIGH',
    'HYD_FLUID_CONTAM',
    'HYD_TEMP_HIGH',
    'HYD_PRESS_OSCILLATION',
    'HYD_MOTOR_VIBRATION',
]
ALL_CODES = CATALOG_CODES + EXTRA_CODES

# ─── Code → fix template (mirrors hooks.py templates + extras) ────
FIX_BY_CODE = {
    'HYD_COOL_FAIL':         ('Replaced cooler assembly — restored thermal headroom.',         ['cooler_assy_p/n_4471'],            90),
    'HYD_COOL_DEGRADED':     ('Flushed coolant loop, replaced filter cartridge.',              ['filter_cart_p/n_2210'],            35),
    'HYD_VALVE_FAIL':        ('Replaced proportional control valve.',                          ['valve_assy_p/n_V32-44'],           75),
    'HYD_VALVE_LAG_SEV':     ('Cleaned spool and bore, replaced seals.',                       ['valve_seal_kit_K-7'],              60),
    'HYD_VALVE_LAG_SML':     ('Changed return-line filter element.',                           ['filter_elem_p/n_RL-9'],            25),
    'HYD_PUMP_LEAK_SEV':     ('Pulled pump, replaced shaft seal and case gasket.',             ['shaft_seal_S-12','case_gasket_G-3'],110),
    'HYD_PUMP_LEAK_WEAK':    ('Replaced shaft seal — case drain flow returned to nominal.',    ['shaft_seal_S-12'],                 70),
    'HYD_ACCUM_FAIL':        ('Replaced accumulator unit, recharged nitrogen to spec.',        ['accum_p/n_A-4L','N2_charge_set'],  65),
    'HYD_ACCUM_LOW_SEV':     ('Recharged accumulator with N2 to 130 bar.',                     ['N2_charge_set'],                   40),
    'HYD_ACCUM_LOW_SLT':     ('Topped up accumulator nitrogen pre-charge.',                    ['N2_charge_set'],                   20),
    'HYD_UNSTABLE':          ('Allowed system to warm to operating temperature.',              [],                                  15),
    'HYD_FILTER_CLOG_HIGH':  ('Replaced primary and return-line filter elements.',             ['filter_elem_p/n_RL-9','filter_elem_p/n_PR-12'], 45),
    'HYD_FLUID_CONTAM':      ('Drained, flushed, and refilled with new ISO-46 fluid.',         ['hyd_fluid_iso46_20L'],             120),
    'HYD_TEMP_HIGH':         ('Cleared blocked cooler intake, verified fan operation.',        [],                                  30),
    'HYD_PRESS_OSCILLATION': ('Replaced relief valve, re-bled hydraulic circuit.',             ['relief_valve_p/n_RV-8'],           55),
    'HYD_MOTOR_VIBRATION':   ('Replaced motor bearings and re-balanced rotor.',                ['motor_bearing_set_MB-3','rotor_balance_kit'], 180),
}

SEVERITY_BY_CODE = {
    # critical
    'HYD_COOL_FAIL':'critical', 'HYD_VALVE_FAIL':'critical', 'HYD_PUMP_LEAK_SEV':'critical',
    'HYD_ACCUM_FAIL':'critical', 'HYD_FLUID_CONTAM':'critical', 'HYD_MOTOR_VIBRATION':'critical',
    # warning
    'HYD_COOL_DEGRADED':'warning', 'HYD_VALVE_LAG_SEV':'warning', 'HYD_PUMP_LEAK_WEAK':'warning',
    'HYD_ACCUM_LOW_SEV':'warning', 'HYD_FILTER_CLOG_HIGH':'warning', 'HYD_TEMP_HIGH':'warning',
    'HYD_PRESS_OSCILLATION':'warning',
    # info
    'HYD_VALVE_LAG_SML':'info', 'HYD_ACCUM_LOW_SLT':'info', 'HYD_UNSTABLE':'info',
}

# Code-family co-occurrence (which codes tend to fire together)
FAMILY = {
    'cool':  ['HYD_COOL_FAIL','HYD_COOL_DEGRADED','HYD_TEMP_HIGH'],
    'valve': ['HYD_VALVE_FAIL','HYD_VALVE_LAG_SEV','HYD_VALVE_LAG_SML','HYD_PRESS_OSCILLATION'],
    'pump':  ['HYD_PUMP_LEAK_SEV','HYD_PUMP_LEAK_WEAK','HYD_MOTOR_VIBRATION'],
    'accum': ['HYD_ACCUM_FAIL','HYD_ACCUM_LOW_SEV','HYD_ACCUM_LOW_SLT'],
    'fluid': ['HYD_FLUID_CONTAM','HYD_FILTER_CLOG_HIGH'],
}
CODE_TO_FAMILY = {c: fam for fam, codes in FAMILY.items() for c in codes}

# Realistic code-frequency distribution (heavier on warnings/info)
CODE_WEIGHTS = {
    'HYD_COOL_FAIL':12, 'HYD_COOL_DEGRADED':18, 'HYD_TEMP_HIGH':14,
    'HYD_VALVE_FAIL':6, 'HYD_VALVE_LAG_SEV':10, 'HYD_VALVE_LAG_SML':18, 'HYD_PRESS_OSCILLATION':8,
    'HYD_PUMP_LEAK_SEV':5, 'HYD_PUMP_LEAK_WEAK':14, 'HYD_MOTOR_VIBRATION':6,
    'HYD_ACCUM_FAIL':5, 'HYD_ACCUM_LOW_SEV':10, 'HYD_ACCUM_LOW_SLT':18,
    'HYD_FLUID_CONTAM':6, 'HYD_FILTER_CLOG_HIGH':14,
    'HYD_UNSTABLE':4,
}
weighted_codes = []
for c, w in CODE_WEIGHTS.items():
    weighted_codes.extend([c] * w)

START_TS = datetime(2026, 1, 1)
TECHS = [f'TECH-{i:02d}' for i in range(1, 25)]

def pick_secondaries(primary, max_n=3):
    """Most events have 0-3 secondaries; secondaries skew within the
    same family for realism but can cross families ~20% of the time."""
    n = random.choices([0,1,2,3], weights=[28,42,22,8])[0]
    if n == 0:
        return []
    fam = CODE_TO_FAMILY.get(primary, 'misc')
    out = []
    pool_same = [c for c in FAMILY.get(fam, []) if c != primary]
    pool_other = [c for c in ALL_CODES if c != primary and CODE_TO_FAMILY.get(c) != fam]
    while len(out) < n:
        if random.random() < 0.80 and pool_same:
            c = random.choice(pool_same)
        else:
            c = random.choice(pool_other)
        if c not in out and c != primary:
            out.append(c)
        if len(out) >= len(pool_same) + len(pool_other):
            break
    return out


def emit_triples_for_event(out, eid, machine_id, machine_model, ts, primary, secondaries):
    fix_text, parts, ttf = FIX_BY_CODE[primary]
    sev = SEVERITY_BY_CODE[primary]
    base_meta = {'event_id': eid, 'machine_id': machine_id, 'machine_model': machine_model, 'ts': ts}

    # 1) code → fix
    out.write(json.dumps({**base_meta, 'subject': primary, 'relation': 'resolved_by',
                          'object': fix_text, 'severity': sev,
                          'time_to_fix_min': ttf, 'parts_replaced': parts,
                          'technician_id': random.choice(TECHS)}) + '\n')
    # 2) code → parts
    for part in parts:
        out.write(json.dumps({**base_meta, 'subject': primary, 'relation': 'requires_part',
                              'object': part}) + '\n')
    # 3) code → machine model
    out.write(json.dumps({**base_meta, 'subject': primary, 'relation': 'occurs_on',
                          'object': machine_model}) + '\n')
    # 4) machine → reported code
    out.write(json.dumps({**base_meta, 'subject': machine_id, 'relation': 'reported',
                          'object': primary, 'severity': sev}) + '\n')
    # 5) primary → secondary co-occurrence
    for sec in secondaries:
        out.write(json.dumps({**base_meta, 'subject': primary, 'relation': 'co_occurs_with',
                              'object': sec}) + '\n')
    return 4 + len(parts) + len(secondaries)


def main():
    n_triples = 0
    n_events = 0
    code_counts = defaultdict(int)
    with open(OUT_PATH, 'w') as out:
        for i in range(N_EVENTS_TARGET):
            primary = random.choice(weighted_codes)
            secondaries = pick_secondaries(primary)
            machine_id, machine_model = random.choice(MACHINES)
            # Spread events over ~140 days
            ts = (START_TS + timedelta(seconds=random.randint(0, 12_000_000))).isoformat() + 'Z'
            eid = f'EVT-H-{i:07d}'
            n_triples += emit_triples_for_event(out, eid, machine_id, machine_model, ts, primary, secondaries)
            code_counts[primary] += 1
            n_events += 1
            if (i+1) % 25_000 == 0:
                print(f"  ... {i+1:,} events / {n_triples:,} triples", flush=True)

    print(f"\nTotal events:  {n_events:,}")
    print(f"Total triples: {n_triples:,}")
    print(f"File:          {OUT_PATH}  ({Path(OUT_PATH).stat().st_size/1024/1024:.1f} MB)")
    print(f"\nPrimary code distribution:")
    for c, n in sorted(code_counts.items(), key=lambda x: -x[1]):
        flag = '' if c in CATALOG_CODES else '  ← outside lexical catalog'
        print(f"  {c:25s} {n:6,}  ({100*n/n_events:5.1f}%){flag}")


if __name__ == '__main__':
    main()
