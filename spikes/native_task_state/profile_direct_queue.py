"""Diagnostic interval timings for the isolated Trio 0.35 direct queue build."""
import gc
import json
import os
from pathlib import Path
import statistics
import time

if hasattr(os, 'sched_setaffinity'):
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})

import trio
import _native_task_state as native
from workloads import execute

assert '/overlay/trio/' in trio._core._run.__file__
assert hasattr(native, 'take_probe')

CASES = {
    'checkpoint_600': {'tasks': 600, 'steps': 100},
    'nursery_spawn': {'batches': 100, 'tasks_per_batch': 100},
    'mixed_600': {'tasks': 600, 'active_tasks': 20, 'samples': 200,
                  'probe_period_s': .002, 'worker_period_ticks': 4, 'payload_terms': 64},
}
names = ('prepare_ns', 'context_run_ns', 'dispatch_ns', 'finish_ns', 'task_steps',
         'shield_reschedule_ns', 'shield_reschedules')
report = {}
for case, params in CASES.items():
    runs = []
    trio.run(execute, case, params)
    for _ in range(5):
        gc.collect()
        native.take_probe()
        native.set_probe_enabled(True)
        cpu_start = time.process_time_ns()
        wall_start = time.perf_counter_ns()
        counts = trio.run(execute, case, params)
        wall_ns = time.perf_counter_ns() - wall_start
        cpu_ns = time.process_time_ns() - cpu_start
        native.set_probe_enabled(False)
        row = dict(zip(names, native.take_probe()))
        row.update(cpu_ns=cpu_ns, wall_ns=wall_ns, operations=counts['operations'])
        runs.append(row)
    report[case] = {'params': params, 'runs': runs,
                    'median': {name: statistics.median(row[name] for row in runs)
                               for name in (*names, 'cpu_ns', 'wall_ns')}}
out = Path('results/stage7/direct_queue_probe.json')
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({case: item['median'] for case, item in report.items()}, indent=2))
