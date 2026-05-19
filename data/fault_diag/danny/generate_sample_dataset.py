"""Generate a sample sim_dataset.csv matching SPEC.md.

Pulls windows from Mario's baseline CSV, injects each fault type with
varying severity, computes the 12 feature aggregates and writes the
CSV in the schema Danny would produce from MATLAB.

This is for demo / pipeline validation. Once Danny ships his actual
MATLAB-exported CSV in the same shape, the ingest adapter doesn't
need any code changes.
"""
import csv
import math
import random
import statistics
from datetime import datetime, timedelta
from pathlib import Path

# Reuse windowing + injection from danny_pipeline (it's right next door)
import sys
sys.path.insert(0, '/opt/G.A8.1/data/fault_diag')
from danny_pipeline import (
    load_csv, window, JOINT_TRIPLES, JOINT_NAMES, INJECTORS, FAULT_TYPES,
    SAMPLE_HZ, WINDOW_N,
)

random.seed(2026_05_19)

OUT_CSV = '/opt/G.A8.1/data/fault_diag/danny/sample_sim_dataset.csv'
ROBOT_MODELS = ['HumanoidArm_v1', 'HumanoidArm_v2', 'IndustrialArm_R6']

# How many runs per (fault, severity) bucket
SEVERITIES = {
    'NOMINAL':              ['none'],
    'JOINT_STUCK':          ['low', 'medium', 'high'],
    'TORQUE_SPIKE':         ['low', 'medium', 'high'],
    'POSITION_DRIFT':       ['low', 'medium', 'high'],
    'VELOCITY_OSCILLATION': ['low', 'medium', 'high'],
    'SENSOR_DROPOUT':       ['low', 'medium', 'high'],
    'NOISE_BURST':          ['low', 'medium', 'high'],
}
RUNS_PER_BUCKET = 10
# Total: 1 + 6×3 = 19 buckets × 10 = 190 runs

# Severity-aware injector wrappers: scale the perturbation by severity
SEV_MULT = {'low': 0.4, 'medium': 1.0, 'high': 2.2}


def inject_with_severity(window_data, fault, severity):
    """Run the injector but with magnitude scaled by severity.
       Mutates window_data in place. Returns affected joint name."""
    affected = None
    if fault == 'NOMINAL':
        return 'none'
    if fault == 'JOINT_STUCK':
        # Affected joint is whichever the injector picked — we'll capture it
        # by recording the joint with min q_range after injection
        INJECTORS[fault](window_data)
        ranges = {j: max(window_data[f'left{j[0].upper()+j[1:]}_q']) - min(window_data[f'left{j[0].upper()+j[1:]}_q'])
                  for j in JOINT_NAMES}
        affected = min(ranges, key=ranges.get)
    elif fault == 'TORQUE_SPIKE':
        # Scale spike by severity
        from danny_pipeline import CHANNELS_TAU
        tau_ch = random.choice(CHANNELS_TAU)
        vals = window_data[tau_ch]
        baseline = max(abs(v) for v in vals)
        mag = baseline * (3.0 + 3.0 * SEV_MULT[severity]) * random.choice([-1, 1])
        spike_idx = random.randint(len(vals)//4, 3*len(vals)//4)
        spike_dur = max(2, int(5 * SEV_MULT[severity]))
        for j in range(spike_idx, min(spike_idx + spike_dur, len(vals))):
            vals[j] = mag
        # Map tau channel back to joint name
        for joint in JOINT_NAMES:
            if joint in tau_ch.replace('TauMeasured', '').lower() or \
               tau_ch.startswith(f'left{joint[0].upper()+joint[1:]}'):
                affected = joint
                break
    elif fault == 'POSITION_DRIFT':
        from danny_pipeline import CHANNELS_Q
        q_ch = random.choice(CHANNELS_Q)
        rng = max(window_data[q_ch]) - min(window_data[q_ch])
        drift = (rng + 0.05) * SEV_MULT[severity]
        for i in range(len(window_data[q_ch])):
            window_data[q_ch][i] += drift * (i / len(window_data[q_ch]))
        for joint in JOINT_NAMES:
            if q_ch.startswith(f'left{joint[0].upper()+joint[1:]}'):
                affected = joint
                break
    elif fault == 'VELOCITY_OSCILLATION':
        from danny_pipeline import CHANNELS_QD
        qd_ch = random.choice(CHANNELS_QD)
        freq = random.uniform(30, 80)
        amp = max(abs(v) for v in window_data[qd_ch]) * (2 * SEV_MULT[severity]) + 0.05
        for i in range(len(window_data[qd_ch])):
            t = i / SAMPLE_HZ
            window_data[qd_ch][i] += amp * math.sin(2 * math.pi * freq * t)
        for joint in JOINT_NAMES:
            if qd_ch.startswith(f'left{joint[0].upper()+joint[1:]}'):
                affected = joint
                break
    elif fault == 'SENSOR_DROPOUT':
        from danny_pipeline import ALL_CHANNELS
        ch = random.choice(ALL_CHANNELS)
        dur = int(WINDOW_N * (0.25 + 0.25 * SEV_MULT[severity]))
        dur = min(dur, WINDOW_N - 1)
        start = random.randint(0, WINDOW_N - dur)
        for i in range(start, start + dur):
            window_data[ch][i] = 0.0
        for joint in JOINT_NAMES:
            if ch.startswith(f'left{joint[0].upper()+joint[1:]}'):
                affected = joint
                break
    elif fault == 'NOISE_BURST':
        from danny_pipeline import ALL_CHANNELS
        ch = random.choice(ALL_CHANNELS)
        sig = statistics.pstdev(window_data[ch]) or 0.01
        amp = sig * (6 * SEV_MULT[severity])
        dur = WINDOW_N // 3
        start = random.randint(0, WINDOW_N - dur)
        for i in range(start, start + dur):
            window_data[ch][i] += random.gauss(0, amp)
        for joint in JOINT_NAMES:
            if ch.startswith(f'left{joint[0].upper()+joint[1:]}'):
                affected = joint
                break
    return affected or 'none'


def compute_aggregates(w):
    out = {}
    for q_ch, qd_ch, tau_ch in JOINT_TRIPLES:
        # Joint name = strip 'left' prefix and '_q' suffix; first char lowercase
        jname = q_ch[4:-2]
        jname = jname[0].lower() + jname[1:]
        q_vals = w[q_ch]
        out[f'{jname}_q_range'] = round(max(q_vals) - min(q_vals), 5)
        qd_vals = w[qd_ch]
        m = statistics.mean(qd_vals)
        dm = [x - m for x in qd_vals]
        out[f'{jname}_qd_zcross'] = sum(1 for i in range(1, len(dm))
                                        if dm[i-1] * dm[i] < 0)
        out[f'{jname}_tau_maxabs'] = round(max(abs(x) for x in w[tau_ch]), 4)
    return out


def main():
    print(f"[load] reading baseline CSV")
    rows = load_csv()
    base_windows = window(rows)
    print(f"[base] {len(base_windows)} candidate windows")

    runs = []
    run_idx = 0
    t0 = datetime(2026, 5, 19, 14, 0, 0)

    for fault, sevs in SEVERITIES.items():
        for sev in sevs:
            for _ in range(RUNS_PER_BUCKET):
                run_idx += 1
                base = random.choice(base_windows)
                w = {k: v[:] for k, v in base.items()}  # deep copy
                affected = inject_with_severity(w, fault, sev)
                aggs = compute_aggregates(w)
                runs.append({
                    'run_id':         f'sim_{run_idx:04d}',
                    'robot_model':    random.choice(ROBOT_MODELS),
                    'injected_fault': fault,
                    'severity':       sev,
                    'affected_joint': affected,
                    'start_ts':       (t0 + timedelta(seconds=5 * run_idx)).isoformat() + 'Z',
                    'duration_s':     round(WINDOW_N / SAMPLE_HZ, 4),
                    **aggs,
                })

    random.shuffle(runs)

    # Column order matches SPEC.md
    cols = ['run_id','robot_model','injected_fault','severity','affected_joint',
            'start_ts','duration_s'] + \
           [f'{j}_{m}' for j in ['shoulderPitch','shoulderRoll','shoulderYaw','elbowPitch']
                       for m in ['q_range','qd_zcross','tau_maxabs']]

    Path(OUT_CSV).parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, 'w', newline='') as f:
        wtr = csv.DictWriter(f, fieldnames=cols)
        wtr.writeheader()
        wtr.writerows(runs)

    print(f"[write] {len(runs)} sim runs → {OUT_CSV}  ({Path(OUT_CSV).stat().st_size/1024:.1f} KB)")
    print(f"\n[preview]")
    for r in runs[:3]:
        print(f"  {r['run_id']}: {r['injected_fault']:22s} sev={r['severity']:6s} "
              f"on {r['affected_joint']:14s} "
              f"shoulderRoll_tau_max={r['shoulderRoll_tau_maxabs']:6.2f}")


if __name__ == '__main__':
    main()
