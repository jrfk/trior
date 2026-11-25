"""Diagnostic Rust-loop timing; not a production benchmark or CPU profiler."""
import gc
import json
import os
import statistics
import sys
import time

import trio
from trio_rust_poc import activate, _native
from workloads import execute, parameters

activate('rust-opt')
if hasattr(os, 'sched_setaffinity'):
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})

cases = ('checkpoint_600', 'mixed_600')
labels = ('prepare_ns', 'context_run_ns', 'dispatch_ns', 'finish_ns', 'task_steps',
          'reschedule_call_ns', 'reschedule_calls')
results = {}
for name in cases:
    params = parameters(name)
    if name == 'checkpoint_600':
        params['steps'] = 100
    runs = []
    for _ in range(5):
        trio.run(execute, name, params)
        gc.collect()
        _native.take_probe()
        _native.set_probe_enabled(True)
        cpu0 = time.process_time_ns()
        wall0 = time.perf_counter_ns()
        counts = trio.run(execute, name, params)
        wall = time.perf_counter_ns() - wall0
        cpu = time.process_time_ns() - cpu0
        _native.set_probe_enabled(False)
        metrics = dict(zip(labels, _native.take_probe()))
        metrics.update(cpu_ns=cpu, wall_ns=wall, operations=counts['operations'])
        runs.append(metrics)
    results[name] = {'params': params, 'runs': runs,
                     'median': {key: statistics.median(r[key] for r in runs)
                                for key in (*labels, 'cpu_ns', 'wall_ns')}}
json.dump(results, sys.stdout, indent=2)
print()
