"""Paired CPU, occupancy, and latency comparison at different active task counts."""
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PARAMS = {
    f'active_{n}': {'tasks': 600, 'active_tasks': n, 'samples': 200,
                    'probe_period_s': .002, 'worker_period_ticks': 4,
                    'payload_terms': 64}
    for n in (20, 100, 599)
}


def median(rows, key):
    return statistics.median(row[key] for row in rows)


def main():
    rng = random.Random(20261108)
    rows = []
    for iteration in range(7):
        cases = list(PARAMS)
        rng.shuffle(cases)
        for case in cases:
            modes = ['python', 'native-task']
            rng.shuffle(modes)
            for mode in modes:
                env = dict(os.environ)
                env['PYTHONHASHSEED'] = '0'
                env['TASK_SPIKE_PARAMS'] = json.dumps(PARAMS[case])
                env['PYTHONPATH'] = str(ROOT / 'benchmarks') + (
                    os.pathsep + str(HERE / 'overlay') if mode == 'native-task' else '')
                result = subprocess.run(
                    [sys.executable, str(HERE / 'bench_overlay.py'), '--worker',
                     'mixed_600', mode], env=env, capture_output=True, text=True, timeout=120)
                if result.returncode:
                    raise RuntimeError(result.stderr[-3000:])
                row = json.loads(result.stdout)
                row.update(case=case, iteration=iteration,
                           occupancy_pct=100 * row['cpu_ns'] / row['wall_ns'])
                rows.append(row)
                print(iteration + 1, case, mode,
                      round(row['cpu_ns'] / 1e6, 1), 'cpu ms', flush=True)
    summary = {}
    for case in PARAMS:
        base = {r['iteration']: r for r in rows if r['case'] == case and r['mode'] == 'python'}
        native = {r['iteration']: r for r in rows if r['case'] == case and r['mode'] == 'native-task'}
        for i in range(7):
            assert base[i]['counts'] == native[i]['counts']
        summary[case] = {
            'paired_cpu_speedup_median': statistics.median(base[i]['cpu_ns'] / native[i]['cpu_ns'] for i in range(7)),
            'paired_cpu_speedup_range': [min(base[i]['cpu_ns'] / native[i]['cpu_ns'] for i in range(7)),
                                         max(base[i]['cpu_ns'] / native[i]['cpu_ns'] for i in range(7))],
            'python_cpu_ms': median(base.values(), 'cpu_ns') / 1e6,
            'native_cpu_ms': median(native.values(), 'cpu_ns') / 1e6,
            'python_occupancy_pct': median(base.values(), 'occupancy_pct'),
            'native_occupancy_pct': median(native.values(), 'occupancy_pct'),
            'python_timer_p99_ms': statistics.median(row['latency_p99_ns']['timer_lateness'] for row in base.values()) / 1e6,
            'native_timer_p99_ms': statistics.median(row['latency_p99_ns']['timer_lateness'] for row in native.values()) / 1e6,
            'python_checkpoint_p99_ms': statistics.median(row['latency_p99_ns']['checkpoint'] for row in base.values()) / 1e6,
            'native_checkpoint_p99_ms': statistics.median(row['latency_p99_ns']['checkpoint'] for row in native.values()) / 1e6,
        }
    out = Path('results/stage7/activity_matrix.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'params': PARAMS, 'raw': rows, 'summary': summary}, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
