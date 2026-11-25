# Compatibility smoke-test scope

Run each backend in a fresh process after the package has been installed:

```sh
.venv/bin/python -m pytest tests --backend=python -q
.venv/bin/python -m pytest tests --backend=python-batch -q
.venv/bin/python -m pytest tests --backend=rust -q
```

The tests exercise public behavior rather than inspecting the native state:
ContextVar isolation, Task identity, nursery start/join, exception groups,
level cancellation and shielding, MockClock and deadline updates, cancellation
of channel operations, lowlevel abort completion, instrumentation callbacks,
thread callbacks, async-generator finalization, invalid yield messages, a basic
reference-lifetime check, and guest-mode execution.

The lowlevel Abort.FAILED tests deliberately cover two valid outcomes: delayed
cancellation, or successful completion despite a pending cancellation. They also
check that an abort callback runs once and custom_sleep_data is cleared when the
task resumes.

These smoke tests do not establish complete Trio compatibility. In particular,
the upstream suite remains necessary for coroutine detach/reattach,
KeyboardInterrupt handling, exact traceback behavior, OS-specific I/O, deep
cancellation trees, and exhaustive GC cases. No benchmark should execute while
these or the upstream tests are running.

Implementation risks relevant to the batch-loop experiment:

- Python callbacks can re-enter Trio APIs synchronously. A native scheduler must
  not hold an exclusive borrow or a non-reentrant mutex across such callbacks.
- A Python helper adds a traceback frame; a Rust call does not. Exception frame
  trimming must account for that difference without dropping user frames.
- Instrument failures are handled by Trio's instrumentation machinery. Calling
  hooks through a different path may accidentally change error handling.
- Python locals held by the last resumed coroutine or its Outcome must not be
  retained accidentally by the native batch executor.
- Guest mode calls the same scheduling generator in separate host-loop ticks.
  Assumptions that one call drives an entire trio.run() do not apply there.
