# Sim-run ingest spec — for Danny's MATLAB output

One CSV. One row per simulation run. We ingest, encode, and serve queries.
No raw waveforms cross the boundary — MATLAB computes per-run aggregates
(it's good at that) and we index those.

## CSV column schema

### Required columns

| column | type | example | notes |
|---|---|---|---|
| `run_id` | string | `sim_2026_05_19_0042` | unique per run; any string is fine |
| `robot_model` | string | `HumanoidArm_v1` | the digital twin identifier |
| `injected_fault` | string | `TORQUE_SPIKE` | one of: `NOMINAL`, `JOINT_STUCK`, `TORQUE_SPIKE`, `POSITION_DRIFT`, `VELOCITY_OSCILLATION`, `SENSOR_DROPOUT`, `NOISE_BURST` (extend the catalog freely) |
| `severity` | string | `high` | `none` / `low` / `medium` / `high` |
| `affected_joint` | string | `shoulderRoll` | which joint the fault was injected on; `none` for NOMINAL |
| `start_ts` | ISO-8601 | `2026-05-19T14:33:00Z` | simulation start wall-clock; we use this for recency reranking |
| `duration_s` | float | `0.5` | window length the aggregates cover |

### Per-joint feature columns (4 joints × 3 aggregates = 12 columns)

For each of `shoulderPitch`, `shoulderRoll`, `shoulderYaw`, `elbowPitch`:

| column | type | description |
|---|---|---|
| `{joint}_q_range` | float | max(q) – min(q) over the window (radians) |
| `{joint}_qd_zcross` | int | velocity zero-crossings on de-meaned qd (oscillation indicator) |
| `{joint}_tau_maxabs` | float | max(|τ|) over the window (Nm) |

### Optional columns (anything else)

We pass through unknown columns as metadata on the encoded record.
Useful add-ons:

| column | example | use |
|---|---|---|
| `notes` | `"motor temp 78C, recovered after 200ms"` | free-text reranker can search on |
| `operator` | `danny@lab` | who ran the sim |
| `fix_applied` | `replaced shoulderRoll bearing` | populate the (label → fix) edge for retrieval |
| `time_to_fix_min` | 45 | feeds the reranker |

## Example: ten rows of the sample dataset

```
run_id,robot_model,injected_fault,severity,affected_joint,start_ts,duration_s,shoulderPitch_q_range,shoulderPitch_qd_zcross,shoulderPitch_tau_maxabs,...
sim_0001,HumanoidArm_v1,NOMINAL,none,none,2026-05-19T14:00:00Z,0.2,0.0231,4,17.4,...
sim_0002,HumanoidArm_v1,TORQUE_SPIKE,high,shoulderRoll,2026-05-19T14:00:05Z,0.2,0.0244,5,18.1,...
sim_0003,HumanoidArm_v1,JOINT_STUCK,medium,elbowPitch,2026-05-19T14:00:10Z,0.2,0.0218,3,17.6,...
```

## MATLAB export snippet

Five lines. Compute the aggregates per simulation run in MATLAB
(you already have the time series in scope) and write the table:

```matlab
% After each sim run, append a row to a struct array `runs`.
T = struct2table(runs);
writetable(T, 'sim_dataset.csv');
% That's it — ship sim_dataset.csv and we ingest it.
```

If you have N runs, you write N rows. We handle the rest.

## What the index serves back

After ingestion, the corpus answers queries like:

| query intent | how to ask | what comes back |
|---|---|---|
| All runs of a given fault | `TORQUE_SPIKE has_injected_fault` | top-k runs, sorted by similarity / recency / configurable |
| Fault on a specific joint | `TORQUE_SPIKE@shoulderRoll has_injected_fault` | composite-key narrows the cluster |
| Signature for one specific run | `{run_id} has_signature` | the recorded feature aggregates as metadata |
| Find similar runs to one I'm looking at | take a new run's features → query as bag | top-k nearest historical runs |
| Past fix patterns for a fault | `TORQUE_SPIKE has_fix_history` | distinct `fix_applied` values + frequency + recency |

## Limits we're being honest about

- **The index is not a classifier.** If you need to *decide* whether
  a live trace is `TORQUE_SPIKE` vs `VELOCITY_OSCILLATION`, do that in
  MATLAB (or any classifier). The index serves the lookup *after*
  classification: "given the label, what runs / fixes / context exist?"
- **Feature engineering matters.** The 12 aggregates above were chosen
  for the synthetic dataset. If your MATLAB simulation surfaces other
  fault-distinctive features (FFT bands, residuals against a nominal
  trajectory, etc.), add them as columns and they'll be searchable.
