# Benchmark protocol

Run from the project root after building/installing the native extension in
release mode. Do not run tests, builds, or other benchmarks concurrently.

```bash
PYTHONPATH=python .venv/bin/python benchmarks/run.py --list
PYTHONPATH=python .venv/bin/python benchmarks/run.py --quick --output results/quick.json
PYTHONPATH=python .venv/bin/python benchmarks/run.py --normal --output results/normal.json
```

`python` is the unchanged Trio baseline. `python-batch` extracts the batch loop
into a Python helper and controls for the new boundary. `rust` uses the native
batch helper. Each child calls `trio_rust_poc.activate(mode)` before `trio.run`.
`rust-opt` changes only repeated Python attribute/method name creation in the
native batch helper, using PyO3's interned strings.
`rust-fast` is a research-only variant of `rust-opt` that expands the default
checkpoint reschedule path in Rust; see the stage4 report before using it.

Each workload/round is a paired comparison. Mode order and workload order are
randomized from a saved seed. A fresh subprocess runs each mode/trial, performs
one untimed warmup, collects garbage, then measures the same workload once.
Imports, backend activation, and warmup are excluded; Trio run startup and
shutdown are included. GC remains enabled at interpreter default thresholds.
`PYTHONHASHSEED=0` and Trio's batch-reversal RNG seed are recorded. The normal
scheduling policy is retained; Hypothesis deterministic scheduling is not enabled.

CPU workloads are calibrated once on the unmodified Python backend. The chosen
integer work multiplier is then identical for all modes and rounds. Quick mode
targets at least 80 ms of baseline work and uses 3 paired rounds; normal mode
targets 200 ms and uses 7. Calibration is capped at 100 times base work.
These are local noise controls, not a statistical guarantee.

Children are pinned to the first permitted CPU by default. Use `--cpu NUMBER`
to select a CPU or `--cpu none` to disable pinning. Affinity, CPU quota, Python,
Trio version, GC policy, and harness source hashes are retained. A shared host
can still contend for the pinned CPU. Large variation needs investigation.

## Workloads

- `checkpoint_1`, `checkpoint_600`: scheduler-dominated runnable tasks.
- `checkpoint_deep`: 32 nested awaits, 10 runnable tasks.
- `channel_0`, `channel_64`: verified request/reply over two memory channels.
  Buffered request/reply never fills the buffer, so this is the uncontended
  buffered path, not bulk queued throughput.
- `nursery_spawn`: 100 children per nursery, each takes one checkpoint.
- `deadline_churn`: create a scope, update its deadline twice, remove it; yield
  every 16 scopes so expired/stale-entry processing participates.
- `cancel_fanout`: start and cancel 600 blocked children, verifying all cleanup.
- `mixed_600`: 600 application tasks (580 idle, 20 periodic) plus one observer.
  Worker work is deliberately small Python arithmetic. The observer takes
  80/200 probes every 2 ms using absolute intended times and measures timer
  lateness and checkpoint resumption delay. This is a synthetic case, not a
  replay of a real robot workload.

Use process CPU time for CPU savings. `mixed_600` wall time deliberately includes
sleeping, so its near-1 wall ratio is not evidence of no CPU improvement.
Its fixed observation schedule avoids reducing the number of probes when the
scheduler falls behind (coordinated omission). If delayed, probes catch up.

Correctness assertions and post-run counters remain enabled in every mode.
Counters are cross-checked between paired modes. The harness fails rather than
silently accepting dropped work. It is not a replacement for compatibility tests.

## Output schema (version 1)

- `metadata`: environment, options, ordering seed, timing definition, timestamps.
- `calibration[workload]`: baseline measurement, selected scale and parameters.
- `raw_runs[]`: mode, workload, pair/round/sequence, CPU and wall nanoseconds,
  operation counts, trial PID, and latency samples/quantiles where relevant.
- `summary[workload].modes[mode]`: timing median, min/max, standard deviation,
  median absolute deviation; baseline/candidate ratios from paired rounds.
- `status`: `running`, `complete`, or `failed`, with `error` on failure.

Results are atomically checkpointed after each child. The companion Markdown
summary is generated at the end, including failure cases. Ratio > 1 is faster.
The observed min/max range is not a confidence interval. Latency summary values
are medians of per-trial quantiles, while raw per-probe samples remain in JSON.
Quantiles use linear interpolation at `(n - 1) * q`.

For a smoke check without calibration:

```bash
PYTHONPATH=python .venv/bin/python benchmarks/run.py --quick --no-calibrate --repeats 1 --warmups 0 --output results/smoke.json
```

Read no performance conclusion into that smoke run. Subset selection is
available through `--cases` and `--modes`; changing workload or interpreter
parameters requires a new named result file.
