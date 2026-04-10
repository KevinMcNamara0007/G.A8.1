# G.A8.1 Edge Service — Query Benchmark Results

**Date:** 2026-04-09 09:23
**Engine:** G.A8.1 C++ (EHC) with edge analyst hooks
**Vectors:** 247,551
**Shards:** 80
**Media:** 33,721

## Scorecard

| Metric | Value |
|---|---|
| Relevance Rate | 41/50 (82%) |
| Precision Rate | 36/50 (72%) |
| Explanation Rate | 50/50 (100%) |
| Gap Analysis Rate | 0/50 (0%) |
| Media Surfaced | 30/50 (60%) |
| Avg Keyword Overlap | 53.0% |
| Latency p50 | 16ms |
| Latency p95 | 37ms |

## Confusion Matrix by Category

| Category | Relevant | Precise | Explained | Gapped | Media |
|---|---|---|---|---|---|
| Geopolitical Links | 9/10 | 9/10 | 10/10 | 0/10 | 7/10 |
| Threat & Security | 9/10 | 9/10 | 10/10 | 0/10 | 7/10 |
| Actor Profiles | 9/10 | 5/10 | 10/10 | 0/10 | 5/10 |
| Topic Discovery | 5/10 | 5/10 | 10/10 | 0/10 | 6/10 |
| Specific Events | 9/10 | 8/10 | 10/10 | 0/10 | 5/10 |
| **TOTAL** | **41/50** | **36/50** | **50/50** | **0/50** | **30/50** |

## Per-Query Results

| # | Cat | Query | KW% | Top% | Relevant | Precise | Media | Latency |
|---|---|---|---|---|---|---|---|---|
| 1 | A | find all links between Iran and Terror | 100% | 100% | ✓ | ✓ | ✓ | 189ms |
| 2 | A | connections between Venezuela and cartels | 30% | 50% | ✓ | ✓ | — | 2ms |
| 3 | A | links between Russia and Syria | 100% | 100% | ✓ | ✓ | ✓ | 21ms |
| 4 | A | Iran and Israel conflict | 100% | 100% | ✓ | ✓ | ✓ | 3ms |
| 5 | A | relationship between Hezbollah and Iran | 55% | 100% | ✓ | ✓ | — | 31ms |
| 6 | A | Turkey and Kurdish forces | 57% | 67% | ✓ | ✓ | ✓ | 28ms |
| 7 | A | China and North Korea alliance | 28% | 50% | ✗ | ✓ | ✓ | 16ms |
| 8 | A | Saudi Arabia and Yemen war | 45% | 50% | ✓ | ✓ | — | 29ms |
| 9 | A | Pakistan and Taliban connections | 70% | 100% | ✓ | ✓ | ✓ | 19ms |
| 10 | A | Qatar and Muslim Brotherhood | 37% | 33% | ✓ | ✗ | ✓ | 9ms |
| 11 | B | cyber attacks on infrastructure | 70% | 100% | ✓ | ✓ | ✓ | 3ms |
| 12 | B | missile launches and ballistic tests | 62% | 100% | ✓ | ✓ | — | 37ms |
| 13 | B | nuclear enrichment programs | 77% | 100% | ✓ | ✓ | ✓ | 6ms |
| 14 | B | drone strikes in the middle east | 45% | 50% | ✓ | ✓ | ✓ | 6ms |
| 15 | B | chemical weapons use in Syria | 72% | 100% | ✓ | ✓ | ✓ | 36ms |
| 16 | B | money laundering and sanctions evasion | 78% | 75% | ✓ | ✓ | ✓ | 18ms |
| 17 | B | ransomware attacks on government | 37% | 67% | ✓ | ✓ | ✓ | 5ms |
| 18 | B | assassination of military commanders | 70% | 100% | ✓ | ✓ | — | 21ms |
| 19 | B | suicide bombings and civilian casualties | 12% | 25% | ✗ | ✗ | — | 7ms |
| 20 | B | espionage and intelligence operations | 100% | 100% | ✓ | ✓ | ✓ | 32ms |
| 21 | C | IRGC Quds Force operations | 28% | 25% | ✗ | ✗ | ✓ | 2ms |
| 22 | C | Hezbollah military activities | 67% | 67% | ✓ | ✓ | — | 21ms |
| 23 | C | Hamas rocket attacks | 57% | 67% | ✓ | ✓ | — | 8ms |
| 24 | C | Houthi rebel actions | 40% | 67% | ✓ | ✓ | ✓ | 38ms |
| 25 | C | ISIS remnants and resurgence | 33% | 33% | ✓ | ✗ | — | 2ms |
| 26 | C | Mossad intelligence operations | 100% | 100% | ✓ | ✓ | ✓ | 34ms |
| 27 | C | Taliban government policies | 43% | 67% | ✓ | ✓ | ✓ | 7ms |
| 28 | C | Al Qaeda network activities | 33% | 33% | ✓ | ✗ | ✓ | 32ms |
| 29 | C | Popular Mobilization Forces Iraq | 35% | 25% | ✓ | ✗ | — | 1ms |
| 30 | C | Kataib Hezbollah militia | 33% | 33% | ✓ | ✗ | — | 2ms |
| 31 | D | protests and civil unrest | 30% | 33% | ✓ | ✗ | — | 2ms |
| 32 | D | election interference and propaganda | 7% | 33% | ✗ | ✗ | — | 5ms |
| 33 | D | humanitarian crisis and refugees | 23% | 67% | ✗ | ✓ | ✓ | 25ms |
| 34 | D | oil and energy geopolitics | 37% | 33% | ✓ | ✗ | — | 29ms |
| 35 | D | religious extremism and radicalization | 23% | 33% | ✗ | ✗ | ✓ | 16ms |
| 36 | D | arms trafficking and smuggling | 3% | 33% | ✗ | ✗ | ✓ | 1ms |
| 37 | D | diplomatic negotiations and peace talks | 28% | 50% | ✗ | ✓ | — | 35ms |
| 38 | D | proxy wars in the region | 70% | 100% | ✓ | ✓ | ✓ | 24ms |
| 39 | D | social media disinformation campaigns | 40% | 75% | ✓ | ✓ | ✓ | 20ms |
| 40 | D | economic sanctions impact | 53% | 67% | ✓ | ✓ | ✓ | 16ms |
| 41 | E | Iran missile strike on Israel | 100% | 100% | ✓ | ✓ | — | 36ms |
| 42 | E | Natanz nuclear facility sabotage | 68% | 75% | ✓ | ✓ | — | 12ms |
| 43 | E | Beirut port explosion | 70% | 100% | ✓ | ✓ | ✓ | 36ms |
| 44 | E | Gaza ceasefire negotiations | 100% | 100% | ✓ | ✓ | ✓ | 7ms |
| 45 | E | Khamenei statements on nuclear policy | 65% | 75% | ✓ | ✓ | — | 11ms |
| 46 | E | IAEA inspections and violations | 67% | 67% | ✓ | ✓ | ✓ | 6ms |
| 47 | E | Strait of Hormuz shipping threats | 30% | 50% | ✓ | ✓ | ✓ | 3ms |
| 48 | E | Afghanistan withdrawal aftermath | 33% | 33% | ✓ | ✗ | ✓ | 7ms |
| 49 | E | Iraq parliament protests | 67% | 67% | ✓ | ✓ | — | 1ms |
| 50 | E | Syrian refugee camps conditions | 25% | 25% | ✗ | ✗ | — | 14ms |
