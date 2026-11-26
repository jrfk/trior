# Contributing

Trior is an experimental project. Read README.md and docs/ROADMAP.md before
starting. Keep changes narrowly scoped and preserve Trio semantics.

Use the development setup in README.md. Add behavior tests under tests/,
prefer differential tests against Trio 0.35.0, and exercise both default
and poll backends on Linux. macOS tests should exercise kqueue on real hardware.
For shared scheduler changes cover cancellation, checkpoints and cleanup.

Run benchmarks with matched Python, workload and hardware in fresh processes:

```sh
python benchmarks/bench_runtime.py
python benchmarks/bench_sync.py
python benchmarks/bench_sparse_io.py trio --count 600
python benchmarks/bench_sparse_io.py trior --count 600
TRIOR_REACTOR=poll python benchmarks/bench_sparse_io.py trior --count 600
python benchmarks/bench_io.py trio --count 600
python benchmarks/bench_io.py trior --count 600
```

Report CPU time, elapsed time, raw repeats, environment and limitations.
Do not claim full compatibility or extrapolate microbenchmarks to production.

Run the full 600-worker steady-state benchmark on demand when evaluating
scheduler or reactor changes or collecting a release baseline. It takes
about 24 minutes and runs only when started explicitly. In GitHub Actions,
select **Steady-state benchmark** and **Run workflow**. Download the
`steady-state` artifact to inspect completed trials. For direct comparisons
with historical measurements, use the same local hardware and Python build.
Keep upstream Trio contributions separate. Licensing is pending owner decision;
see docs/licensing.md before external contributions or publication.
