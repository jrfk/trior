# Trio Rust PoC benchmark results

Status: complete

Speedup is baseline time / candidate time; values greater than 1 favor the candidate.
Ratios are medians of paired fresh-process trials, not independent-median ratios.

| Workload | Mode | CPU median (ms) | Wall median (ms) | Paired CPU speedup | CPU ratio range |
| --- | --- | ---: | ---: | ---: | --- |
| checkpoint_1 | python | 179.987 | 180.045 | baseline | — |
| checkpoint_1 | rust | 330.253 | 330.246 | 0.545x | 0.524–0.561x |
| checkpoint_1 | rust-opt | 225.482 | 225.496 | 0.798x | 0.757–0.823x |
| checkpoint_600 | python | 187.013 | 187.013 | baseline | — |
| checkpoint_600 | rust | 327.288 | 327.281 | 0.569x | 0.554–0.603x |
| checkpoint_600 | rust-opt | 208.414 | 208.420 | 0.903x | 0.850–0.940x |
| checkpoint_deep | python | 202.975 | 202.975 | baseline | — |
| checkpoint_deep | rust | 256.386 | 256.472 | 0.782x | 0.716–0.837x |
| checkpoint_deep | rust-opt | 214.642 | 214.666 | 0.946x | 0.917–1.012x |
| channel_0 | python | 206.531 | 206.532 | baseline | — |
| channel_0 | rust | 344.764 | 344.847 | 0.603x | 0.583–0.613x |
| channel_0 | rust-opt | 236.767 | 236.761 | 0.879x | 0.790–0.908x |
| channel_64 | python | 211.342 | 211.343 | baseline | — |
| channel_64 | rust | 363.849 | 363.862 | 0.579x | 0.543–0.617x |
| channel_64 | rust-opt | 244.709 | 244.714 | 0.876x | 0.845–0.896x |
| nursery_spawn | python | 216.746 | 216.746 | baseline | — |
| nursery_spawn | rust | 298.140 | 298.134 | 0.731x | 0.663–0.780x |
| nursery_spawn | rust-opt | 228.422 | 228.429 | 0.953x | 0.922–0.967x |
| deadline_churn | python | 209.010 | 209.004 | baseline | — |
| deadline_churn | rust | 222.812 | 222.806 | 0.943x | 0.894–0.998x |
| deadline_churn | rust-opt | 213.658 | 213.655 | 0.965x | 0.941–1.044x |
| cancel_fanout | python | 219.313 | 219.314 | baseline | — |
| cancel_fanout | rust | 265.791 | 265.786 | 0.818x | 0.806–0.857x |
| cancel_fanout | rust-opt | 223.996 | 223.996 | 0.965x | 0.927–1.027x |
| mixed_600 | python | 40.663 | 410.183 | baseline | — |
| mixed_600 | rust | 51.170 | 412.724 | 0.798x | 0.731–0.882x |
| mixed_600 | rust-opt | 44.314 | 411.031 | 0.932x | 0.858–1.053x |

## Latency

Shown values are medians of each trial's quantile; raw per-probe samples are in JSON.

| Workload | Mode | Metric | p50 (µs) | p95 (µs) | p99 (µs) |
| --- | --- | --- | ---: | ---: | ---: |
| mixed_600 | python | timer_lateness | 636.688 | 1127.465 | 1304.435 |
| mixed_600 | python | checkpoint | 8.974 | 222.921 | 270.286 |
| mixed_600 | rust | timer_lateness | 631.021 | 1166.945 | 1273.944 |
| mixed_600 | rust | checkpoint | 13.294 | 223.456 | 320.384 |
| mixed_600 | rust-opt | timer_lateness | 638.250 | 1117.025 | 1280.396 |
| mixed_600 | rust-opt | checkpoint | 10.162 | 198.690 | 267.517 |

## Scope

Synthetic local measurements on a shared execution host. No claim of robot or production performance.
mixed_600 wall time deliberately includes sleeping; use CPU time and latency rather than wall-time speedup.
The range is observed trial variability, not a confidence interval. A small difference or overlap is inconclusive.
Warmups, import/build time exclusions, calibration, affinity, environment, and trial order are retained in JSON.
