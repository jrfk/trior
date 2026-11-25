# Research and performance

All original experiments, patches, profiles, and raw measurements are preserved
in the Git branch `research/stage20` (commit `75c83cd`). This branch is included
in the distributed Git bundle. Main contains the independent runtime only.

After cloning the bundle, create a local archive branch once if it is not
already present: `git branch research/stage20 origin/research/stage20`.
Inspect past experiments without changing main:

```sh
git show research/stage20:results/stage20/RESULTS_JA.md
git show research/stage20:results/stage18/RESULTS_JA.md
git worktree add ../trior-research research/stage20
```

Early experiments replaced parts of Trio's Python scheduler with Rust.
Python-owned state and boundary overhead limited the gains, motivating the
independent scheduler and I/O reactor. Keep the archived experiments as
controls, not runtime dependencies.

## Selected historical results

Linux x86_64, CPython 3.12.14, Trio 0.35.0, Rust 1.100.0, PyO3 0.30.1.
Stage 18 CPU ratios (Trio / Trior): Event 3.29x, Lock 2.77x, Semaphore 2.31x,
memory channel(0) 2.87x, memory channel(64) 2.46x.

Stage 20 sparse I/O (one active pair, 3,000 operations, 5 runs, median):

| Pairs | Trio CPU ms | Trior poll CPU ms | Trior epoll CPU ms |
|---:|---:|---:|---:|
| 64 | 22.21 | 13.76 | 12.75 |
| 600 | 37.66 | 88.11 | 16.18 |
| 2000 | 78.88 | 307.80 | 38.50 |

At 600 pairs, epoll reduced CPU time by 57% against Trio and improved wall
time by 1.79x. Dense I/O (600 pairs, 30 rounds, 2ms sleep each): Trio CPU
115.54ms, Trior poll 53.48ms, epoll 73.32ms. Repeated epoll_ctl calls may
explain the dense-I/O difference; not yet proven.

These are short historical synthetic measurements, not a guarantee of
production performance. See docs/HANDOFF.md for more context. New benchmark
reports should document workload, hardware, Python, raw data, wall and CPU
time and relevant latency distributions.

## Stage 20.5: repository restructuring

No algorithm changes to src/runtime.rs or src/reactor*.rs. The original
implementation remains available in the archived branch.
Linux x86_64, CPython 3.12.14, Rust 1.100.0, PyO3 0.30.1.

- Before: 63 native-backend tests passed.
- After: 63 tests passed on epoll and 63 on poll; basic example passed.
- Built the release wheel and installed it into an empty Python 3.12 venv
  without dependencies. Verified import trior and trior.run(trior.sleep, 0),
  and absence of both Trio and the legacy trio_rust_poc package.
- Linux/macOS CI workflow added; remote CI and macOS runtime tests not run.

Initial unpinned 7-run comparison showed a dense CPU-time increase
(71.52 to 97.23 ms), with substantial run-to-run variability. A follow-up
paired, fresh-process, single-CPU-affinity comparison alternated before/after
order for nine repeats, 600 socket pairs, default epoll backend:

| Workload | Before wall ms | After wall ms | Before CPU ms | After CPU ms |
|---|---:|---:|---:|---:|
| Sparse | 27.16 | 27.17 | 18.07 | 18.51 |
| Dense | 99.31 | 98.17 | 83.95 | 77.49 |

There is no consistent evidence of a large regression from the restructuring;
short noisy measurements do not establish a performance improvement.

Paired raw samples (CPU milliseconds, affinity CPU 0):

- sparse baseline: 26.40, 17.91, 17.29, 16.60, 16.23, 18.07, 24.87, 18.23, 23.70
- sparse after: 21.25, 19.60, 17.44, 17.14, 18.76, 19.00, 18.51, 17.11, 18.09
- dense baseline: 98.87, 83.95, 86.53, 73.15, 84.48, 89.22, 77.70, 81.79, 70.86
- dense after: 89.46, 71.17, 72.86, 80.80, 77.49, 86.31, 68.16, 79.02, 65.10

## Stage 20.6: Nursery.start

Implemented startup handshake, return values, generic TaskStatus protocol and
TASK_STATUS_IGNORED. A provisional nursery owns errors and cancellation until
started() transfers the task subtree and its inner scopes to the target nursery.
Rust tracks provisional members rather than scanning the whole task table on
each transfer. Startup into a non-ancestor nursery is not yet supported;
full Trio parity, instrumentation and task naming remain outstanding.

Linux CPython 3.12.14: 83 tests pass on epoll and 83 on poll (20 new differential
tests). Cases include 600 retained children, descendant signaling, cancellation
during startup, failure before and after started(), duplicate/missing started,
scope transfer, and ignored status.

Sequential start of N children, which wait on a common event until all have
started. Fixed work includes startup and cleanup, seven repeats per module
in separate processes, medians (milliseconds):

| Children | Trio CPU | Trior CPU | Trio wall | Trior wall |
|---:|---:|---:|---:|---:|
| 64 | 1.756 | 0.393 | 1.755 | 0.392 |
| 600 | 15.767 | 3.642 | 15.766 | 3.640 |
| 2000 | 51.304 | 13.058 | 51.302 | 13.057 |

600 children: 4.33x CPU efficiency, 76.9% less process CPU time. The initial
full-table scan prototype regressed at 2000 children (90ms vs Trio 57ms);
the indexed implementation avoids that scan. Short synthetic benchmark,
not a proof of production throughput or complete compatibility.
Reproduce: python benchmarks/bench_nursery_start.py trio --count 600
and the same command with trior.

Raw CPU samples (ms):

- trio 64: 2.634, 1.791, 1.747, 1.756, 1.884, 1.637, 1.676
- trior 64: 0.725, 0.361, 0.715, 0.322, 0.592, 0.393, 0.362
- trio 600: 18.188, 15.071, 15.859, 14.014, 20.620, 15.767, 12.863
- trior 600: 5.177, 3.648, 3.689, 3.461, 3.642, 3.370, 3.596
- trio 2000: 56.885, 51.419, 44.316, 51.304, 45.083, 53.121, 44.278
- trior 2000: 14.420, 13.058, 12.446, 11.247, 11.794, 13.446, 14.779
