# Trio Rust batch-loop experiment

CPython 3.12 only, Trio 0.35.0 exactly. Experimental process-wide adapter,
not a complete Rust runtime. It replaces only the runnable-batch loop and
keeps Python-owned tasks, cancellation, timers, and I/O unchanged.

Build with Rust and uv installed:

```sh
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements-dev.lock
. .venv/bin/activate
maturin develop --release
python -m pytest tests --backend=python -q
python -m pytest tests --backend=python-batch -q
python -m pytest tests --backend=rust -q
python -m pytest tests --backend=rust-opt -q
python -m pytest tests --backend=rust-fast -q
python benchmarks/run.py --normal --output results/reproduction.json
```

Build used Rust 1.99.1, PyO3 0.30.1, CPython 3.12.14 on Linux x86_64.
Cargo.lock pins Rust dependencies. Version/source hash guards reject other
Trio sources. Run each backend in a fresh process. No production deployment
or full compatibility claim. See benchmarks/README.md and notes/compatibility.md.

The `rust-opt` variant interns Python attribute names in the native loop;
`rust` retains the original implementation as a control. See
`results/stage2/normal.json` and `RESULTS_JA.md` for the second experiment.
CPU occupancy and diagnostic interval timing are in
`results/stage3/PROFILE_JA.md`. The production source `src/lib.rs` does not
include the diagnostic timers; `notes/lib_probe.rs` preserves that variant.
`rust-fast` is an unsuccessful research variant that expands the default
checkpoint rescheduling path in Rust. Its measurements and compatibility
limits are in `results/stage4/RESULTS_JA.md`; do not select it for application
use.

For the Trio 0.35 / Python 3.15 investigation, see
`results/stage5/README_JA.md`. The independent Linux PID CPU sampler is
`benchmarks/sample_pid_cpu.py`; the optional in-process diagnostic sampler is
`benchmarks/production_cpu_probe.py`.

An isolated Trio source fork with a PyO3-backed Task state, native reschedule,
and native batch is in `spikes/native_task_state`. Its GC and CPU measurements
are in `results/stage6/RESULTS_JA.md`; the stock Python implementation remains
faster in the tested synthetic workloads.

The Rust translation is derived from Trio's MIT-licensed scheduler; see
LICENSE.Trio. Source files, benchmark raw data, and test logs are included.
