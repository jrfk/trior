# Trio Rust PoC benchmark results

Status: complete

Speedup is baseline time / candidate time; values greater than 1 favor the candidate.
Ratios are medians of paired fresh-process trials, not independent-median ratios.

| Workload | Mode | CPU median (ms) | Wall median (ms) | Paired CPU speedup | CPU ratio range |
| --- | --- | ---: | ---: | ---: | --- |
| checkpoint_600 | python | 192.197 | 192.225 | baseline | — |
| checkpoint_600 | rust-opt | 225.489 | 225.511 | 0.852x | 0.690–0.939x |
| channel_0 | python | 191.382 | 192.923 | baseline | — |
| channel_0 | rust-opt | 225.323 | 225.369 | 0.880x | 0.791–1.004x |
| mixed_600 | python | 55.441 | 413.081 | baseline | — |
| mixed_600 | rust-opt | 56.906 | 414.988 | 0.958x | 0.754–1.094x |

## Latency

Shown values are medians of each trial's quantile; raw per-probe samples are in JSON.

| Workload | Mode | Metric | p50 (µs) | p95 (µs) | p99 (µs) |
| --- | --- | --- | ---: | ---: | ---: |
| mixed_600 | python | timer_lateness | 701.235 | 1242.711 | 1486.379 |
| mixed_600 | python | checkpoint | 11.129 | 240.045 | 398.568 |
| mixed_600 | rust-opt | timer_lateness | 673.793 | 1151.722 | 1377.112 |
| mixed_600 | rust-opt | checkpoint | 12.592 | 236.138 | 318.930 |

## Scope

Synthetic local measurements on a shared execution host. No claim of robot or production performance.
mixed_600 wall time deliberately includes sleeping; use CPU time and latency rather than wall-time speedup.
The range is observed trial variability, not a confidence interval. A small difference or overlap is inconclusive.
Warmups, import/build time exclusions, calibration, affinity, environment, and trial order are retained in JSON.
