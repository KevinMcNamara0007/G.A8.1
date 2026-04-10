# A8.1 Reasoning Benchmark — Multi-Seed Results
## 6 Seeds × 500 Queries × 4 Modes = 7,200 Total Queries

---

## Summary

| Seed | Direct Hit@1 | Direct Hit@5 | CoT Hit@5 | CoT Uplift | CoT Recovered | Complex Both |
|------|-------------|-------------|-----------|------------|---------------|-------------|
| 42 | 77.2% | 92.6% | 96.6% | +4.0% | 20 | 99.5% |
| 123 | 80.8% | 95.2% | 98.0% | +2.8% | 14 | 99.5% |
| 7 | 79.8% | 95.0% | 97.4% | +2.4% | 12 | 99.0% |
| 999 | 78.8% | 95.6% | 97.8% | +2.2% | 11 | 98.5% |
| 2024 | 77.4% | 95.2% | 97.4% | +2.2% | 11 | 100.0% |
| 314 | 83.4% | 96.0% | 98.0% | +2.0% | 10 | 99.0% |
| **Mean** | **79.6%** | **94.9%** | **97.5%** | **+2.6%** | **13** | **99.2%** |
| **Std** | **±2.3%** | **±1.2%** | **±0.5%** | **±0.7%** | — | **±0.5%** |

---

## Key Findings

### Direct Retrieval
- **Mean Hit@1: 79.6% ±2.3%** — stable across seeds
- **Mean Hit@5: 94.9% ±1.2%** — very tight variance
- Seed 314 outperforms (83.4%) — within expected sampling variance

### Chain-of-Thought
- **Mean uplift: +2.6% ±0.7%** — consistent positive contribution
- **Mean recoveries: 13 per 500 queries** — ~35% of Hit@5 misses recovered
- CoT Hit@5 at **97.5% ±0.5%** — extremely tight, near-ceiling
- Diminishing returns: seed 42 sees +4.0% but seed 314 only +2.0% (already high baseline)

### Complex Comparison
- **Mean both-found: 99.2% ±0.5%** — near-perfect
- Seed 2024: 100% — all 200 comparisons successful
- The two-tier routing handles independent entity lookups with virtually zero interference

### Abductive Verification
- 0% across all seeds (not re-run — structurally impossible without inverse index)
- Finding is architectural, not statistical — no seed variance to measure

---

## Comparison to A7

| Metric | A7 | A8.1 (mean ±std) |
|--------|-----|-------------------|
| Direct Hit@1 | 83.0% | 79.6% ±2.3% |
| Direct Hit@5 | 92.0% | 94.9% ±1.2% |
| CoT uplift | +3.0% | +2.6% ±0.7% |
| CoT Hit@5 | ~95% | 97.5% ±0.5% |
| Complex both | — | 99.2% ±0.5% |
| Latency | 6.7ms | <2ms |
| Schema | 822 relations | zero |

---

## Note on Direct Hit@1 Variance

The reasoning benchmark uses single-formulation `query(subject, relation)` — 
one bind(S,R) vector, one routing path. The seed variance benchmark uses the 
fan-out multi-formulation approach (multiple query vectors, multiple routing 
attempts). This explains the delta:

| Benchmark | Method | Mean Hit@1 |
|-----------|--------|-----------|
| Seed variance (fan-out) | Multiple formulations | 83.8% ±1.0% |
| Reasoning (single) | One bind(S,R) | 79.6% ±2.3% |

The fan-out adds ~4% through broader search coverage. Both numbers are valid — 
they measure different query strategies against the same index.

---

*6 seeds × 500 queries = 3,000 direct + 3,000 CoT + 1,200 complex = 7,200 total queries*
*All queries sampled via reservoir sampling from 21,233,150 ground-truth triples*
*Engine: EHC C++ v12.5.0.2 · D=16,384 · k=128 · 1,800 shards*
