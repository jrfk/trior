"""Paired fresh-process comparison of stock Trio and NativeTaskState overlay."""
from __future__ import annotations
import gc
import hashlib
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OVERLAY = HERE / 'overlay'
CASES = {
    'checkpoint_600': {'tasks': 600, 'steps': 100},
    'nursery_spawn': {'batches': 100, 'tasks_per_batch': 100},
    'mixed_600': {'tasks': 600, 'active_tasks': 20, 'samples': 200,
                  'probe_period_s': .002, 'worker_period_ticks': 4, 'payload_terms': 64},
}


def worker(case, mode):
    if hasattr(os, 'sched_setaffinity'):
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    import trio
    from trio._core import _run
    from workloads import execute
    if mode in ('native-task', 'native-task-opt'):
        from _native_task_state import NativeTaskState
        assert issubclass(_run.Task, NativeTaskState)
        if mode == 'native-task-opt':
            from _native_task_state import set_native_empty_check
            set_native_empty_check(True)
    else:
        assert not hasattr(_run.Task, '__native_task_state__')
    params = json.loads(os.environ['TASK_SPIKE_PARAMS']) if 'TASK_SPIKE_PARAMS' in os.environ else CASES[case]
    trio.run(execute, case, params)
    gc.collect()
    cpu0 = time.process_time_ns()
    wall0 = time.perf_counter_ns()
    counts = trio.run(execute, case, params)
    wall = time.perf_counter_ns() - wall0
    cpu = time.process_time_ns() - cpu0
    latency_p99_ns = {}
    for name, samples in counts.get('latency_samples_ns', {}).items():
        if samples:
            ordered = sorted(samples)
            latency_p99_ns[name] = ordered[max(0, (99 * len(ordered) + 99) // 100 - 1)]
    print(json.dumps({'case': case, 'mode': mode, 'cpu_ns': cpu, 'wall_ns': wall,
                      'counts': {k:v for k,v in counts.items() if k != 'latency_samples_ns'},
                      'latency_p99_ns': latency_p99_ns,
                      'pid': os.getpid(), 'trio_source': str(_run.__file__)}))


def main():
    rng = random.Random(20261107)
    compare_native = os.environ.get('TASK_SPIKE_COMPARE_EMPTY') == '1'
    baseline = 'native-task' if compare_native else 'python'
    candidate = 'native-task-opt' if compare_native else 'native-task'
    raw = []
    for round_index in range(7):
        cases = list(CASES)
        rng.shuffle(cases)
        for case in cases:
            modes = [baseline, candidate]
            rng.shuffle(modes)
            for mode in modes:
                env = dict(os.environ)
                env['PYTHONHASHSEED'] = '0'
                env['PYTHONPATH'] = str(ROOT / 'benchmarks') + (os.pathsep + str(OVERLAY) if mode != 'python' else '')
                result = subprocess.run([sys.executable, str(__file__), '--worker', case, mode],
                                        env=env, capture_output=True, text=True, timeout=120)
                if result.returncode:
                    raise RuntimeError(result.stderr[-2000:])
                item = json.loads(result.stdout)
                item['round'] = round_index
                raw.append(item)
                print(round_index+1,case,mode,round(item['cpu_ns']/1e6,2),'ms',flush=True)
    summary = {}
    for case in CASES:
        base = {r['round']:r for r in raw if r['case']==case and r['mode']==baseline}
        native = {r['round']:r for r in raw if r['case']==case and r['mode']==candidate}
        for i in range(7): assert base[i]['counts'] == native[i]['counts']
        ratios = [base[i]['cpu_ns']/native[i]['cpu_ns'] for i in range(7)]
        summary[case] = {'paired_cpu_speedup_median':statistics.median(ratios),
                         'paired_cpu_speedup_range':[min(ratios),max(ratios)],
                         'python_cpu_ms_median':statistics.median(base[i]['cpu_ns'] for i in range(7))/1e6,
                         'native_cpu_ms_median':statistics.median(native[i]['cpu_ns'] for i in range(7))/1e6,
                         'python_p99_ns_median': {name: statistics.median(base[i]['latency_p99_ns'][name] for i in range(7)) for name in base[0]['latency_p99_ns']},
                         'native_p99_ns_median': {name: statistics.median(native[i]['latency_p99_ns'][name] for i in range(7)) for name in native[0]['latency_p99_ns']}}
    out = {'status':'complete','python':sys.version,'comparison':{'baseline':baseline,'candidate':candidate},'source_sha256':{
        str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in
        (HERE / 'src/lib.rs', HERE / 'prepare_overlay.py', HERE / 'bench_overlay.py')},
        'params':CASES,'raw':raw,'summary':summary}
    path = Path(os.environ.get('TASK_SPIKE_RESULT', str(ROOT / 'results/stage6/native_task_overlay.json')))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out,indent=2)+'\n')
    print('SUMMARY',summary)


if __name__ == '__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--worker': worker(sys.argv[2], sys.argv[3])
    else: main()
