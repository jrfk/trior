"""Paired fresh-process benchmark for an isolated stock Trio change."""
import gc
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CASES = {'checkpoint_600': {'tasks': 600, 'steps': 100},
         'nursery_spawn': {'batches': 100, 'tasks_per_batch': 100},
         'mixed_600': {'tasks': 600, 'active_tasks': 20, 'samples': 200,
                       'probe_period_s': .002, 'worker_period_ticks': 4,
                       'payload_terms': 64}}


def worker(case, mode):
    if hasattr(os, 'sched_setaffinity'):
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    import trio
    from trio._core import _run
    from workloads import execute
    assert ('/overlay/' in _run.__file__) == (mode == 'inline')
    params = CASES[case]
    _run._r.seed(17)
    trio.run(execute, case, params)
    gc.collect()
    _run._r.seed(17)
    cpu0 = time.process_time_ns()
    wall0 = time.perf_counter_ns()
    counts = trio.run(execute, case, params)
    cpu = time.process_time_ns() - cpu0
    wall = time.perf_counter_ns() - wall0
    latency = {name: sorted(values)[max(0, (99 * len(values) + 99) // 100 - 1)]
               for name, values in counts.get('latency_samples_ns', {}).items()}
    print(json.dumps({'case': case, 'mode': mode, 'cpu_ns': cpu, 'wall_ns': wall,
                      'counts': {k: v for k, v in counts.items() if k != 'latency_samples_ns'},
                      'latency_p99_ns': latency, 'trio_source': str(_run.__file__)}))


def main():
    rng = random.Random(20261108)
    rows = []
    for iteration in range(7):
        cases = list(CASES)
        rng.shuffle(cases)
        for case in cases:
            modes = ['stock', 'inline']
            rng.shuffle(modes)
            for mode in modes:
                env = dict(os.environ)
                env['PYTHONHASHSEED'] = '0'
                env['PYTHONPATH'] = str(ROOT / 'benchmarks') + (os.pathsep + str(HERE / 'overlay') if mode == 'inline' else '')
                p = subprocess.run([sys.executable, str(__file__), '--worker', case, mode],
                                   env=env, capture_output=True, text=True, timeout=120)
                if p.returncode:
                    raise RuntimeError(p.stderr[-2500:])
                row = json.loads(p.stdout)
                row['iteration'] = iteration
                rows.append(row)
                print(iteration + 1, case, mode, round(row['cpu_ns'] / 1e6, 2), flush=True)
    summary = {}
    for case in CASES:
        a = {r['iteration']: r for r in rows if r['case'] == case and r['mode'] == 'stock'}
        b = {r['iteration']: r for r in rows if r['case'] == case and r['mode'] == 'inline'}
        for i in range(7):
            assert a[i]['counts'] == b[i]['counts']
        ratios = [a[i]['cpu_ns'] / b[i]['cpu_ns'] for i in range(7)]
        summary[case] = {'paired_cpu_speedup_median': statistics.median(ratios),
                         'paired_cpu_speedup_range': [min(ratios), max(ratios)],
                         'stock_cpu_ms_median': statistics.median(a[i]['cpu_ns'] for i in range(7)) / 1e6,
                         'inline_cpu_ms_median': statistics.median(b[i]['cpu_ns'] for i in range(7)) / 1e6,
                         'stock_p99_ms': {k: statistics.median(a[i]['latency_p99_ns'][k] for i in range(7)) / 1e6 for k in a[0]['latency_p99_ns']},
                         'inline_p99_ms': {k: statistics.median(b[i]['latency_p99_ns'][k] for i in range(7)) / 1e6 for k in b[0]['latency_p99_ns']}}
    out = ROOT / 'results' / 'stage8' / 'inline_checkpoint.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'params': CASES, 'raw': rows, 'summary': summary}, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        worker(sys.argv[2], sys.argv[3])
    else:
        main()
