# Native Task state spike

This isolated PyO3 0.30.1 experiment confirms that a Python `attrs.define`
subclass with Trio's `NoPublicConstructor` metaclass can inherit native
get/set fields. On CPython 3.12, `test_spike.py` passes. The subclass needs
`__new__(cls, *args, **kwargs): return super().__new__(cls)` because the native
base constructor does not accept the Python Task init keywords.

`prepare_overlay.py` now makes an isolated copy of installed Trio 0.35, changes
its Task base to NativeTaskState, and routes Runner.reschedule through a Rust
helper. With `TASK_SPIKE_BATCH=1`, the copied runnable-batch loop also runs in
Rust and reads the next-send fields directly from NativeTaskState. This does
not modify the installed Trio. The Rust extension is built with
`maturin develop --release` in this directory. Run the overlay with
`PYTHONPATH=spikes/native_task_state/overlay` from the project root.

The targeted upstream suite (run, KI, instrumentation, guest mode) passes
195, skips 2, xfails 1 in both fused modes. Each benchmark uses seven paired
fresh processes. Baseline/native CPU speedup medians (above 1 is faster):

| workload | native Task + Rust reschedule | plus Rust batch direct state |
|---|---:|---:|
| checkpoint_600 | 0.817 | 0.968 |
| nursery_spawn | 0.848 | 0.897 |
| mixed_600 | 0.910 | 0.922 |

The Rust batch improves checkpoint work over the first fusion, but is still
below stock Python in these short shared-host trials. Raw data and source are
`fused-benchmark.json` and `native-batch-benchmark.json`; the earlier field-only
result is in `../../results/stage6/native_task_overlay.json`.

This is a technical spike, not a compatible replacement. A self-cycle in
`custom_sleep_data` initially leaked; explicit `__traverse__` and `__clear__`
now make `test_gc_cycle.py` pass. The full Trio suite, other operating systems,
and Python 3.15 remain untested. The core suite passes 277 tests (12 skipped,
1 xfailed) after the GC change. The post-GC paired results are in
`../../results/stage6/native_batch_gc.json`; no tested workload is faster
than the stock Python scheduler.

The stage 7 queue experiment is opt-in with `TASK_SPIKE_QUEUE=1` when
generating the overlay. Set `TASK_SPIKE_BATCH=1 TASK_SPIKE_DIRECT_QUEUE=1`
as well to hand off a whole batch from the native queue to the native task
loop without building a Python list in normal execution. The deterministic
test scheduling branch still sorts and shuffles a Python list. Results and
limitations are recorded in `../../notes/STAGE7_PLAN_JA.md`.
