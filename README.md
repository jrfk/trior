# Trior

An experimental Rust-powered structured concurrency runtime for Python,
aiming for Trio API compatibility and lower CPU overhead.

```python
import trior

async def worker():
    await trior.sleep(0.01)

async def main():
    async with trior.open_nursery() as nursery:
        for _ in range(600):
            nursery.start_soon(worker)

trior.run(main)
```

## Development

For maintainers and coding agents, see [AGENTS.md](AGENTS.md),
[the technical handoff](docs/HANDOFF.md), and [the roadmap](docs/ROADMAP.md).

The current prototype targets CPython 3.12 with Trio 0.35.0 as a reference.

```sh
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements-dev.lock
. .venv/bin/activate
maturin develop --release --locked
python -m pytest -q spikes/runtime/test_runtime.py spikes/runtime/test_sync.py spikes/runtime/test_io.py
python spikes/runtime/bench_runtime.py
python spikes/runtime/bench_sync.py
```

The independent scheduler owns tasks, ready queues, deadlines and parking
in Rust. Python coroutines execute in CPython. Event, Lock, Semaphore and
memory channels have experimental Python APIs with native wait queues;
the synchronization wrappers and channel payload storage use Python.

The Unix readiness reactor owns descriptor registration in Rust and uses
level-triggered epoll on Linux or kqueue on macOS, with timer-aware blocking waits and bounded polling
under ready-task load. The experimental trior.lowlevel and trior.socket
modules expose descriptor readiness and nonblocking socket operations.
The API is incomplete: async DNS, TCP connect,
higher-level streams, thread bridges, guest mode, instrumentation,
production resource cleanup and exhaustive compatibility remain outstanding.
The reactor has been tested on Linux only; macOS ARM64 passes cross-target
`cargo check`. Set `TRIOR_REACTOR=poll` to select the earlier Unix poll backend.

See [Stage 20](results/stage20/RESULTS_JA.md) for native reactor benchmarks.

See [Stage 19](results/stage19/RESULTS_JA.md) for I/O measurements.

See [Stage 18](results/stage18/RESULTS_JA.md) for measurements and limitations.

## Historical batch-loop experiment

The following describes the original scheduler adapter, which remains for
reproduction of the earlier benchmarks.

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
