# Trior

An experimental Rust-powered structured concurrency runtime for Python,
aiming for Trio API compatibility and lower CPU overhead.

> Early development. Not a drop-in replacement for Trio or production-ready.

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

## Architecture

Python executes user coroutines; Rust owns scheduler state, ready queues,
timers, cancellation and I/O readiness. Linux uses epoll; macOS uses kqueue;
poll is retained for comparison. The public Python package is `trior`.

Current prototype: basic nurseries (including start/start_soon and task status), cancellation, timers, synchronization,
memory channels and partial nonblocking socket operations. TCP connect,
higher-level streams, DNS, threads and complete Trio API parity are pending.
Linux has been tested; macOS ARM64 previously passed a cross-target type check.

See [architecture](docs/architecture.md), [roadmap](docs/ROADMAP.md),
[research](docs/research.md) and [technical handoff](docs/HANDOFF.md).

## Development

CPython 3.12 is the presently supported build target; 3.15 is a development
goal. Trio 0.35.0 is used for differential tests, not required by the runtime.

```sh
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements-dev.lock
. .venv/bin/activate
maturin develop --release --locked
python -m pytest -q
TRIOR_REACTOR=poll python -m pytest -q
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for benchmark and contribution guidance.
See [the release guide](docs/release.md) for distribution builds and publishing setup.

## Fixed-rate benchmark

Compare Trio 0.35.0 and Trior with 600 concurrent workers (timers, Events,
memory channels and local socket I/O) for 60 seconds at 10, 20, 50 and 100 Hz:

```sh
python benchmarks/bench_steady_state.py compare --output /tmp/trior-steady-state.json
```

The comparison runs three trials per runtime and frequency in fresh processes.
The full run takes about 24 minutes. In GitHub Actions, start **Steady-state
benchmark** manually when collecting a baseline or evaluating runtime changes.
It checks every worker's completion count and reports per-trial CPU occupancy,
process CPU time, latency percentiles and maximum, and peak RSS.
It also reports when the workload generator misses a scheduled period and
saves each trial as it completes. In the original macOS ARM64 campaign,
Trior's median CPU occupancy was 14.1% to 52.9% lower at equal completed
work. That campaign predates dispatch timing.
See [measurement protocol and results](docs/steady-state-results.md).

## License status

Trior's independent-code license has not yet been selected by the owner.
The existing Trio copyright and MIT notice are retained in
[LICENSE.Trio](LICENSE.Trio) for historical and potentially derived material.
See [licensing notes](docs/licensing.md). This is a pre-release repository;
do not interpret the upstream notice as a license grant for all Trior code.
