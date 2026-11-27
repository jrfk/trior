# Trior

Trior is an experimental async runtime for CPython 3.12. Python runs the
coroutines and Rust handles scheduling, timers, cancellation and I/O readiness.
The public API implements a subset of Trio 0.35.0, including nurseries,
synchronization primitives, memory channels and basic socket operations.

## CPU occupancy with 600 workers

The benchmark ran timers, events, memory channels and local socket I/O on
macOS ARM64 with CPython 3.12.13. Each value is the median of three
60-second trials with equal completed work. One CPU core is 100%.

| Scheduled rate | Trio 0.35.0 | Trior |
|---:|---:|---:|
| 10 Hz | 13.71% | 6.46% |
| 20 Hz | 20.76% | 11.61% |
| 50 Hz | 39.58% | 26.65% |
| 100 Hz | 53.47% | 45.91% |

The [API guide](https://github.com/jrfk/trior/blob/main/docs/api.md)
lists implemented and planned features. The
[benchmark report](https://github.com/jrfk/trior/blob/main/docs/steady-state-results.md)
includes the measurement protocol, variability and latency results.
