# Trio Rust PoC benchmark results

Status: complete

Speedup is baseline time / candidate time; values greater than 1 favor the candidate.
Ratios are medians of paired fresh-process trials, not independent-median ratios.

| Workload | Mode | CPU median (ms) | Wall median (ms) | Paired CPU speedup | CPU ratio range |
| --- | --- | ---: | ---: | ---: | --- |
| checkpoint_1 | python | 231.317 | 231.308 | baseline | — |
| checkpoint_1 | rust-opt | 285.836 | 288.625 | 0.809x | 0.725–0.864x |
| checkpoint_1 | rust-fast | 308.854 | 308.845 | 0.764x | 0.671–0.839x |
| checkpoint_600 | python | 167.069 | 167.068 | baseline | — |
| checkpoint_600 | rust-opt | 215.085 | 215.076 | 0.843x | 0.429–1.047x |
| checkpoint_600 | rust-fast | 199.091 | 199.115 | 0.823x | 0.574–1.140x |
| checkpoint_deep | python | 220.175 | 220.217 | baseline | — |
| checkpoint_deep | rust-opt | 223.643 | 223.636 | 0.984x | 0.869–1.336x |
| checkpoint_deep | rust-fast | 224.232 | 229.009 | 0.915x | 0.524–1.262x |
| channel_0 | python | 227.352 | 227.451 | baseline | — |
| channel_0 | rust-opt | 268.221 | 268.211 | 0.795x | 0.564–0.984x |
| channel_0 | rust-fast | 304.713 | 307.876 | 0.816x | 0.733–1.436x |
| channel_64 | python | 208.778 | 208.774 | baseline | — |
| channel_64 | rust-opt | 246.113 | 246.660 | 0.845x | 0.795–1.102x |
| channel_64 | rust-fast | 249.977 | 250.007 | 0.787x | 0.729–1.242x |
| nursery_spawn | python | 208.901 | 208.971 | baseline | — |
| nursery_spawn | rust-opt | 231.030 | 233.416 | 0.923x | 0.772–1.859x |
| nursery_spawn | rust-fast | 206.561 | 206.592 | 1.004x | 0.898–2.030x |
| deadline_churn | python | 212.320 | 216.434 | baseline | — |
| deadline_churn | rust-opt | 211.469 | 214.232 | 1.041x | 0.538–1.479x |
| deadline_churn | rust-fast | 217.297 | 217.290 | 0.954x | 0.430–1.391x |
| cancel_fanout | python | 192.487 | 192.509 | baseline | — |
| cancel_fanout | rust-opt | 200.411 | 200.442 | 0.958x | 0.434–1.129x |
| cancel_fanout | rust-fast | 201.045 | 205.433 | 0.955x | 0.493–1.032x |
| mixed_600 | python | 59.451 | 413.666 | baseline | — |
| mixed_600 | rust-opt | 64.961 | 415.643 | 1.000x | 0.581–1.128x |
| mixed_600 | rust-fast | 62.807 | 415.163 | 0.968x | 0.835–1.034x |

## Latency

Shown values are medians of each trial's quantile; raw per-probe samples are in JSON.

| Workload | Mode | Metric | p50 (µs) | p95 (µs) | p99 (µs) |
| --- | --- | --- | ---: | ---: | ---: |
| mixed_600 | python | timer_lateness | 690.822 | 1219.723 | 1829.709 |
| mixed_600 | python | checkpoint | 11.797 | 280.308 | 441.210 |
| mixed_600 | rust-opt | timer_lateness | 656.625 | 1199.610 | 1621.270 |
| mixed_600 | rust-opt | checkpoint | 13.261 | 271.041 | 401.125 |
| mixed_600 | rust-fast | timer_lateness | 707.198 | 1253.291 | 1703.521 |
| mixed_600 | rust-fast | checkpoint | 14.261 | 264.684 | 474.511 |

## Scope

Synthetic local measurements on a shared execution host. No claim of robot or production performance.
mixed_600 wall time deliberately includes sleeping; use CPU time and latency rather than wall-time speedup.
The range is observed trial variability, not a confidence interval. A small difference or overlap is inconclusive.
Warmups, import/build time exclusions, calibration, affinity, environment, and trial order are retained in JSON.
