# Trior — development instructions

## Mission

Trior is an independent experimental async runtime for Python, powered by Rust,
with a Trio-compatible public API. Repository: https://github.com/jrfk/trior.
Reference: https://github.com/python-trio/trio (v0.35.0) and
https://trio.readthedocs.io/en/stable/. The independent runtime is the primary
development target; historical partial replacements of Trio are research controls,
not the production architecture.

Priorities, in order:

1. Preserve Trio semantics (structured concurrency, cancellation, checkpoints,
   resource ownership, exception propagation and task isolation).
2. Lower process CPU time and idle CPU load for equivalent work, especially
   applications with around 600 long-lived coroutines.
3. Improve elapsed time, throughput, latency and memory usage.
4. Maintain readable, portable, testable code.

Rust is a means, not a goal. Do not claim full/drop-in compatibility based on
a subset of tests. Keep upstream Trio contributions separate from Trior.

## Getting oriented

Read [docs/HANDOFF.md](docs/HANDOFF.md), [docs/ROADMAP.md](docs/ROADMAP.md),
README.md and docs/research.md, plus archived results as needed before changing code.
Stage 20 implementation: c783eb1; Stage 20.5 separates the active package
from archived research (research/stage20). Begin with Stage 21 unless directed otherwise.

- Core: src/runtime.rs; src/reactor.rs; src/reactor/{epoll,kqueue,poll}.rs.
- Public facade: python/trior/.
- Python coroutine driver/wrappers: python/trior/_runtime.py.
- Independent-runtime tests and benchmarks: tests/ and benchmarks/.
- Historical adapters, tests, benchmarks and raw results: branch research/stage20.
- API reference test dependency pinned to Trio 0.35.0; not a runtime dependency. Current package requires
  CPython >=3.12,<3.13; Python 3.15 is a development target, not yet supported.
  Do not broaden metadata until the relevant tests pass.

## Architecture and correctness

Keep coroutine execution in CPython; move scheduler, readiness, deadlines and
other runtime bookkeeping into Rust where benchmarks justify it. Minimize
Python/Rust crossings, Python allocations and OS calls. Never hold a mutable
native borrow or lock across Python coroutine callbacks. Keep GIL handling and
ownership explicit. Preserve contextvars and cancellation/cleanup invariants.
Account for descriptor reuse, close, simultaneous readiness/cancellation,
fairness, stale events, and cleanup of partially completed operations.
Prefer local deterministic tests over external services. Use Trio itself as the
behavioral oracle at the pinned version. Consult upstream licensing and retain
attribution for derived code.

## Build and regression checks

From repository root:

```sh
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements-dev.lock
. .venv/bin/activate
maturin develop --release --locked
python -m pytest -q
TRIOR_REACTOR=poll python -m pytest -q
```

Historical control tests are preserved on research/stage20; use current differential tests for main.
Linux defaults to epoll, macOS to kqueue, and TRIOR_REACTOR=poll selects the
comparison implementation. A macOS cross-target check is not a runtime test.
Do not report unexecuted checks as passing. State exact platform/Python versions.

## Performance protocol

Measure equivalent completed work in fresh processes with same Python,
reference Trio and workload. Record process CPU time and wall time separately,
CPU occupancy = CPU seconds / wall seconds * 100 (one-core convention),
throughput, relevant latency percentiles, RSS and idle CPU load where possible.
Use repeats, raw samples and medians; record environment, affinity, parameters
and variance. For I/O use both sparse readiness and dense traffic. For long
runs include a fixed-rate workload with roughly 600 long-lived tasks and
cancellation/deadline churn. A speedup is not proof of reduced CPU consumption
or production suitability. Investigate regressions; do not cherry-pick.

## Workflow

For each stage:
- Read existing code and upstream behavior; define a narrow compatibility scope.
- Implement, add differential tests and run relevant regression suites.
- Measure performance where the change affects the hot path.
- Record commands, results, limitations and follow-up in docs/ or benchmark artifacts; avoid accumulating raw experimental output on main.
- Update README/roadmap when public scope or stage status changes.
- Use scoped commits and PRs according to the owner's requested workflow.
- Delegate independent research, test and benchmark work to subagents when
  available and authorized; integrate and verify the results centrally.

No publishing to PyPI or upstream Trio, changing repository visibility, or
claiming production readiness without the owner's direction. Do not expose
credentials or private application data in code, logs or benchmarks.
