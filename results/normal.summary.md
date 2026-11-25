# Trio Rust PoC benchmark results

Status: complete

Speedup is baseline time / candidate time; values greater than 1 favor the candidate.
Ratios are medians of paired fresh-process trials, not independent-median ratios.

| Workload | Mode | CPU median (ms) | Wall median (ms) | Paired CPU speedup | CPU ratio range |
| --- | --- | ---: | ---: | ---: | --- |
| checkpoint_1 | python | 205.231 | 205.237 | baseline | — |
| checkpoint_1 | python-batch | 209.354 | 209.373 | 0.995x | 0.965–1.138x |
| checkpoint_1 | rust | 337.202 | 337.238 | 0.614x | 0.599–0.715x |
| checkpoint_600 | python | 192.955 | 192.954 | baseline | — |
| checkpoint_600 | python-batch | 190.117 | 190.116 | 1.011x | 0.822–1.054x |
| checkpoint_600 | rust | 321.728 | 321.801 | 0.594x | 0.552–0.636x |
| checkpoint_deep | python | 180.482 | 180.488 | baseline | — |
| checkpoint_deep | python-batch | 183.257 | 183.263 | 0.997x | 0.948–1.029x |
| checkpoint_deep | rust | 226.152 | 226.152 | 0.804x | 0.774–0.829x |
| channel_0 | python | 186.360 | 186.367 | baseline | — |
| channel_0 | python-batch | 192.268 | 192.344 | 0.989x | 0.924–1.002x |
| channel_0 | rust | 291.323 | 291.360 | 0.637x | 0.609–0.664x |
| channel_64 | python | 168.835 | 169.269 | baseline | — |
| channel_64 | python-batch | 168.948 | 168.994 | 0.999x | 0.968–1.054x |
| channel_64 | rust | 263.169 | 263.186 | 0.652x | 0.630–0.671x |
| nursery_spawn | python | 212.163 | 212.169 | baseline | — |
| nursery_spawn | python-batch | 209.605 | 209.648 | 1.003x | 0.995–1.060x |
| nursery_spawn | rust | 285.167 | 285.184 | 0.750x | 0.710–0.765x |
| deadline_churn | python | 195.439 | 195.455 | baseline | — |
| deadline_churn | python-batch | 198.353 | 198.352 | 0.992x | 0.964–1.004x |
| deadline_churn | rust | 202.070 | 202.107 | 0.976x | 0.930–0.993x |
| cancel_fanout | python | 219.400 | 219.429 | baseline | — |
| cancel_fanout | python-batch | 211.965 | 211.964 | 1.036x | 0.977–1.069x |
| cancel_fanout | rust | 258.713 | 258.764 | 0.839x | 0.809–0.866x |
| mixed_600 | python | 39.094 | 409.932 | baseline | — |
| mixed_600 | python-batch | 38.357 | 409.754 | 1.046x | 0.886–1.061x |
| mixed_600 | rust | 48.811 | 412.194 | 0.806x | 0.771–0.856x |

## Latency

Shown values are medians of each trial's quantile; raw per-probe samples are in JSON.

| Workload | Mode | Metric | p50 (µs) | p95 (µs) | p99 (µs) |
| --- | --- | --- | ---: | ---: | ---: |
| mixed_600 | python | timer_lateness | 605.474 | 1088.053 | 1211.834 |
| mixed_600 | python | checkpoint | 8.783 | 204.184 | 255.171 |
| mixed_600 | python-batch | timer_lateness | 637.389 | 1083.894 | 1196.468 |
| mixed_600 | python-batch | checkpoint | 8.833 | 164.521 | 232.361 |
| mixed_600 | rust | timer_lateness | 629.002 | 1104.239 | 1231.230 |
| mixed_600 | rust | checkpoint | 13.355 | 198.902 | 267.757 |

## Scope

Synthetic local measurements on a shared execution host. No claim of robot or production performance.
mixed_600 wall time deliberately includes sleeping; use CPU time and latency rather than wall-time speedup.
The range is observed trial variability, not a confidence interval. A small difference or overlap is inconclusive.
Warmups, import/build time exclusions, calibration, affinity, environment, and trial order are retained in JSON.
