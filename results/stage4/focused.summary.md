# Trio Rust PoC benchmark results

Status: complete

Speedup is baseline time / candidate time; values greater than 1 favor the candidate.
Ratios are medians of paired fresh-process trials, not independent-median ratios.

| Workload | Mode | CPU median (ms) | Wall median (ms) | Paired CPU speedup | CPU ratio range |
| --- | --- | ---: | ---: | ---: | --- |
| checkpoint_600 | python | 448.093 | 448.516 | baseline | — |
| checkpoint_600 | rust-opt | 490.288 | 490.284 | 0.905x | 0.743–1.174x |
| checkpoint_600 | rust-fast | 542.848 | 546.392 | 0.806x | 0.734–1.089x |
| nursery_spawn | python | 530.906 | 530.963 | baseline | — |
| nursery_spawn | rust-opt | 555.035 | 562.214 | 0.954x | 0.923–1.437x |
| nursery_spawn | rust-fast | 590.721 | 599.655 | 0.904x | 0.596–1.372x |
| mixed_600 | python | 56.642 | 413.373 | baseline | — |
| mixed_600 | rust-opt | 61.445 | 414.598 | 0.947x | 0.696–1.113x |
| mixed_600 | rust-fast | 59.603 | 413.893 | 0.925x | 0.757–1.096x |

## Latency

Shown values are medians of each trial's quantile; raw per-probe samples are in JSON.

| Workload | Mode | Metric | p50 (µs) | p95 (µs) | p99 (µs) |
| --- | --- | --- | ---: | ---: | ---: |
| mixed_600 | python | timer_lateness | 683.191 | 1238.963 | 1475.623 |
| mixed_600 | python | checkpoint | 11.151 | 279.156 | 406.901 |
| mixed_600 | rust-opt | timer_lateness | 690.875 | 1238.690 | 1446.168 |
| mixed_600 | rust-opt | checkpoint | 12.679 | 239.581 | 540.240 |
| mixed_600 | rust-fast | timer_lateness | 728.134 | 1251.942 | 1447.265 |
| mixed_600 | rust-fast | checkpoint | 13.434 | 258.016 | 522.115 |

## Scope

Synthetic local measurements on a shared execution host. No claim of robot or production performance.
mixed_600 wall time deliberately includes sleeping; use CPU time and latency rather than wall-time speedup.
The range is observed trial variability, not a confidence interval. A small difference or overlap is inconclusive.
Warmups, import/build time exclusions, calibration, affinity, environment, and trial order are retained in JSON.
