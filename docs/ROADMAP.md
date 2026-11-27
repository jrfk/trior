# Trior development roadmap

Stage 20 introduced the current native I/O reactors. Stage 20.6 added the
nursery startup handshake. Reorder planned work based on dependencies,
benchmark results and owner direction.

| Stage | Task | Status |
|---|---|---|
| 1–17 | Research, independent scheduler, cancellation, timers | Research/prototype complete |
| 18 | Synchronization primitives and package | Prototype complete |
| 19 | Unix I/O reactor and partial socket API | Prototype complete |
| 20 | epoll/kqueue and sparse/dense measurements | Reactor regression tests pass on Linux and macOS ARM64 |
| 20.5 | OSS-oriented repository structure and package separation | Complete |
| 20.6 | Nursery.start / TaskStatus | Implemented and Linux-tested |
| 21 | TCP connect, SocketStream, listeners | Next |
| 22 | Async DNS and Happy Eyeballs | Planned |
| 23 | Dense I/O optimization and registration reuse | Planned |
| 24 | Detailed cancellation / exception / cleanup parity | Planned |
| 25 | Thread bridge and wakeups | Planned |
| 26 | Port or adapt upstream Trio tests; compatibility inventory | Planned |
| 27 | AnyIO compatibility investigation | Planned |
| 28 | HTTP application benchmarks | Planned |
| 29 | Long-running 600-task mixed workload | Fixed-rate benchmark implemented. Sparse phases and cancellation churn are planned. |
| 30 | Python 3.15 and free-threaded build/runtime validation | Planned |
| 31 | Linux/macOS CI, architecture and wheel matrix | CI and initial Linux x86_64/macOS ARM64 wheels verified |
| 32 | Packaging, documentation, publication preparation | Release workflow drafted and MIT license selected |

## Stage 21 — TCP streams

Implement the numeric-IP path first, without blocking DNS. Match the relevant
Trio 0.35.0 behavior and signatures; document deviations. Start by reviewing
Trio socket and high-level networking source plus its tests and the existing
Trior lowlevel/socket/runtime files.

- Nonblocking socket.connect(): handling pending connection, SO_ERROR,
  immediate success, failure, cancellation and descriptor cleanup.
- SocketStream, SocketListener, open_tcp_stream, open_tcp_listeners:
  send_all, receive_some, send_eof, wait_send_all_might_not_block where
  applicable, accept, aclose and async context management. Export only
  implemented public APIs; document missing options.
- Preserve independent recv/send concurrency and reject conflicting operations
  according to the reference behavior. Handle partial writes, bytes-like
  inputs, EOF, backpressure, resource ownership, closed/broken errors,
  and checkpoints including fast-path success or failure.
- Use loopback TCP and socketpair local tests with deterministic coordination.
  Cover refused connection, transfer, partial writes, half-close, cancellation
  before/during connect/send/receive, simultaneous readiness/cancel, listener
  cleanup, repeated open/close, and fd leak checks. Test IPv4 first; validate
  IPv6 where supported. Avoid external services.
- Run new differential tests plus the full independent runtime suite using
  native reactor and poll on Linux. On available macOS host, run kqueue;
  otherwise label it not runtime-tested.
- Benchmark fixed-size TCP messages/echo or transfer with matched payloads,
  1/64/600 concurrent connections, sparse and dense traffic. Record CPU time,
  wall, throughput, p50/p95/p99 latency, occupancy and repeats. Use sufficient
  FD limits; distinguish setup vs steady-state. Keep both sides equivalent.
- Deliver commits, tests, raw benchmark data, docs/stage21-results.md
  (or equivalent), and updated API/status docs.

Exit criterion: basic numeric-IP streams and listeners work, tests pass, measured
results and limitations are recorded. If behavior or CPU regresses, investigate
and document before claiming improvement. DNS/Happy Eyeballs are Stage 22.

## Follow-up details

- Stage 22: nonblocking resolver, cancellation, address resolution and
  Happy Eyeballs against the reference; avoid assuming numeric-only parity.
- Stage 23: profile dense traffic; evaluate registration reuse versus ownership
  and stale-event safety, compare epoll/poll/kqueue, measure syscall counts.
- Stages 24–27: expand differential coverage for cancellation, nursery start,
  exception groups, resource lifecycle, thread wakeups and contextvars; map
  AnyIO backend expectations and report actual supported scope.
- Stages 28–29: fixed-rate realistic local networking/timer/channel workloads,
  ~600 long-lived tasks; include idle and burst periods, CPU per unit work,
  p99 latency, RSS drift, fd/task counts, cancellation latency, reproducibility.
- Stages 30–32: validate actual Python versions and architectures before
  widening package metadata; CI on real Linux/macOS, licensing and docs,
  release preparation. Publishing itself needs owner direction.

## First Codex request

Read AGENTS.md, docs/HANDOFF.md and docs/ROADMAP.md, verify the checked-out
baseline and continue Stage 21. Implement and test against Trio 0.35.0,
measure CPU time and elapsed time, document results and limitations.
Use subagents for independent work when available. Keep commits scoped and
do not claim unverified results.
