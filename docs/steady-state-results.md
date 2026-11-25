# Fixed-rate 600-worker benchmark

## Protocol

`benchmarks/bench_steady_state.py` compares independent Trior with Trio 0.35.0.
CPU occupancy for equivalent completed work is the primary metric.
The default campaign runs 24 fresh subprocesses sequentially, covering three
repeats per runtime and frequency at 10, 20, 50 and 100 Hz for 60 seconds each.
Runtime order alternates by repeat.

Exactly 600 long-lived workers: 200 timers, 100 Event waiters, 150 memory
channel receivers, 150 local socketpair receivers. One additional controller
releases work at absolute deadlines. Each worker completes exactly duration × Hz
operations. First deadline is one period after measurement starts, last is at
60 seconds. Delayed work catches up; nothing is dropped. Event notifications
are retained in one shared Event per tick. Each channel has enough capacity
for all ticks. Socket messages are one byte, with async backpressure. Channel
sequence and socket payload are checked, and every worker's completion count
must match. The comparison driver also rejects unequal totals.

This workload releases work in batches at the same rate for all workers.
Socket traffic goes through the runtime's public socket facade and includes the
sender's checkpoint and scheduling overhead. Sparse I/O phases and
cancellation churn are separate parts of the Stage 29 roadmap.

All workers/resources and compact double latency arrays are allocated before
timing. Timing begins after all 600 workers have entered a common start gate;
it includes gate release, scheduled work, drain and nursery exit. Resource
cleanup, sorting, JSON and imports are outside the interval. Latency is each
operation's completion time minus its absolute intended deadline (clamped at
zero), including controller delay and queueing. Percentiles are nearest rank
across all 600 workers. CPU occupancy is 100 × process CPU time / measured
wall time, so one fully occupied core is 100%. Drain time and CPU per
operation help interpret occupancy when work completes after the final deadline.

RSS is the process peak up to the point before sorting and includes the
interpreter, runtime, socket resources, Events and preallocated latency arrays.
At higher rates the measurement storage grows to 3.6 million doubles at
100 Hz. Trials begin with workers at the start gate and run with OS-managed
CPU placement and power settings. Background activity and thermal drift may
affect the results. The JSON records per-trial metrics and latency summaries.

## Reproduce

Each worker process opens 300 socket descriptors plus the runtime's own
descriptors. It raises its soft descriptor limit to 332 if needed and if
the hard limit allows it.

```sh
env VIRTUAL_ENV=$PWD/.venv .venv/bin/maturin develop --release --locked
.venv/bin/python -m pytest -q
TRIOR_REACTOR=poll .venv/bin/python -m pytest -q
.venv/bin/python benchmarks/bench_steady_state.py compare --output /tmp/trior-steady-state-60s.json
# Optional comparison backend (a separate full campaign):
TRIOR_REACTOR=poll .venv/bin/python benchmarks/bench_steady_state.py compare --output /tmp/trior-steady-state-poll.json
```

## Validation environment

Measured on 2026-11-25 (JST) on macOS 27.2.1 (26B131), Darwin 27.2.0, ARM64.
CPython 3.12.13, Trio 0.35.0, Rust 1.90.0, Trior release build
from runtime revision `de891a6` and the default kqueue reactor.
95 tests passed on kqueue and 95 on poll, including 12 benchmark tests.
Linux epoll was not executed in this campaign.

## Results

Each of the 24 trials completed exactly the expected work per worker and per
category. The table uses the median of three trials per runtime and rate.
Reductions are relative to Trio 0.35.0.

| Hz | Completions per trial | Trio CPU occupancy | Trior CPU occupancy | Occupancy reduction | Trio CPU (s) | Trior CPU (s) | CPU time reduction |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 360,000 | 13.71% | 6.46% | 52.9% | 8.225 | 3.876 | 52.9% |
| 20 | 720,000 | 20.76% | 11.61% | 44.1% | 12.458 | 6.967 | 44.1% |
| 50 | 1,800,000 | 39.58% | 26.65% | 32.7% | 23.750 | 15.994 | 32.7% |
| 100 | 3,600,000 | 53.47% | 45.91% | 14.1% | 32.089 | 27.551 | 14.1% |

Latency percentiles, peak RSS and drain time are medians of the three
per-trial values. Maximum latency is the largest observed across all three
trials for that row. Drain is measured wall time beyond the 60-second schedule.

| Hz | Runtime | p50 (ms) | p95 (ms) | p99 (ms) | Max (ms) | Peak RSS (MiB) | CPU occupancy range | Drain (ms) |
|---:|:---|---:|---:|---:|---:|---:|---:|---:|
| 10 | Trio | 9.808 | 16.013 | 19.290 | 28.095 | 36.44 | 13.03–13.80% | 16.99 |
| 10 | Trior | 2.987 | 7.279 | 8.334 | 18.408 | 27.70 | 6.08–6.49% | 6.69 |
| 20 | Trio | 7.262 | 11.380 | 14.401 | 95.272 | 39.75 | 20.39–22.75% | 10.21 |
| 20 | Trior | 2.937 | 7.582 | 12.500 | 123.063 | 31.75 | 10.29–15.36% | 8.42 |
| 50 | Trio | 5.645 | 9.441 | 14.138 | 311.982 | 49.17 | 36.06–41.72% | 7.85 |
| 50 | Trior | 2.656 | 7.276 | 9.570 | 101.755 | 42.56 | 19.30–32.87% | 6.11 |
| 100 | Trio | 3.593 | 5.900 | 9.396 | 1147.082 | 62.94 | 53.31–53.77% | 9.66 |
| 100 | Trior | 1.987 | 5.421 | 6.466 | 100.446 | 59.45 | 31.82–49.50% | 3.32 |

Trior used less process CPU time and had lower occupancy in every paired trial.
The median reduction narrowed as the frequency increased, and individual
Trior samples at 100 Hz varied from 31.82% to 49.50% occupancy. CPU time
supports the occupancy result because both runtimes completed the same work
in roughly 60 seconds. The data establish the observed difference on this host.

Median p99 was lower with Trior at all four rates. The largest 20 Hz delay
was higher with Trior (123.063 ms versus 95.272 ms). At 100 Hz, Trio's first
trial had a p99 of 608.826 ms while its other trials were below 10 ms.
Both runtimes caught up by the end of their trials. The cause of the
transient delays was not isolated.

The [per-trial JSON](steady-state-samples.json) contains all 24 samples,
including per-category completions, CPU per operation, throughput, wall times
and latency quantiles. Each trial was saved separately as it finished, then
combined using the comparison CLI's aggregation function.
