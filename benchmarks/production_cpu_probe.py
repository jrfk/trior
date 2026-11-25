"""Low-frequency CPU sampling for a real Trio 0.35 process.

Use from your application:

    from production_cpu_probe import ProcessCpuSampler
    with ProcessCpuSampler('trio-cpu.jsonl', interval=1.0):
        trio.run(main)

For step counts, run separately with ``TrioStepCounter`` as an instrument.
That mode adds Python callbacks on every task step and changes performance.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import threading
import time

import trio


class ProcessCpuSampler:
    """Measure process CPU time / elapsed time; 100% means one full core."""

    def __init__(self, output_path: str | Path, interval: float = 1.0) -> None:
        if interval <= 0:
            raise ValueError('interval must be positive')
        self.output_path = Path(output_path)
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self._file = None
        self._previous: tuple[int, int] | None = None

    def start(self) -> ProcessCpuSampler:
        if self._thread is not None:
            raise RuntimeError('sampler already started')
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.output_path.open('w', encoding='utf-8')
        meta = {
            'type': 'metadata', 'schema_version': 1, 'python': sys.version,
            'trio': trio.__version__, 'pid': os.getpid(), 'platform': platform.platform(),
            'cpu_count': os.cpu_count(), 'interval_seconds': self.interval,
            'cpu_percent_definition': '100 * process CPU nanoseconds / elapsed nanoseconds; one core = 100%',
        }
        if hasattr(os, 'sched_getaffinity'):
            meta['affinity'] = sorted(os.sched_getaffinity(0))
        try:
            meta['cgroup_cpu_max'] = Path('/sys/fs/cgroup/cpu.max').read_text().strip()
        except OSError:
            pass
        self._write(meta)
        self._previous = (time.perf_counter_ns(), time.process_time_ns())
        self._thread = threading.Thread(target=self._sample_loop, name='trio-cpu-probe', daemon=True)
        self._thread.start()
        return self

    def _write(self, row: dict) -> None:
        assert self._file is not None
        self._file.write(json.dumps(row, ensure_ascii=False) + '\n')
        self._file.flush()

    def _sample(self) -> None:
        wall = time.perf_counter_ns()
        cpu = time.process_time_ns()
        assert self._previous is not None
        previous_wall, previous_cpu = self._previous
        delta_wall = wall - previous_wall
        delta_cpu = cpu - previous_cpu
        self._previous = (wall, cpu)
        if delta_wall <= 0:
            return
        self._write({
            'type': 'sample', 'timestamp_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'elapsed_ns': delta_wall, 'process_cpu_ns': delta_cpu,
            'cpu_percent_one_core': 100.0 * delta_cpu / delta_wall,
        })

    def _sample_loop(self) -> None:
        try:
            while not self._stop.wait(self.interval):
                self._sample()
        except BaseException as exc:
            self._error = exc

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join()
        try:
            if self._error is None:
                self._sample()  # Include a final partial window, identified by elapsed_ns.
        finally:
            assert self._file is not None
            self._file.close()
            self._file = None
            self._thread = None
        if self._error is not None:
            raise RuntimeError('CPU sampling failed') from self._error

    def __enter__(self) -> ProcessCpuSampler:
        return self.start()

    def __exit__(self, _type, _value, _traceback) -> None:
        self.stop()


class TrioStepCounter(trio.abc.Instrument):
    """Separate diagnostic run: hook callbacks alter scheduler CPU cost."""

    def __init__(self) -> None:
        self.steps = 0
        self.scheduled = 0
        self.io_waits = 0

    def before_task_step(self, task: trio.lowlevel.Task) -> None:
        self.steps += 1

    def task_scheduled(self, task: trio.lowlevel.Task) -> None:
        self.scheduled += 1

    def before_io_wait(self, timeout: float) -> None:
        self.io_waits += 1

    def snapshot(self) -> dict[str, int]:
        return {'task_steps': self.steps, 'task_scheduled': self.scheduled,
                'io_waits': self.io_waits}


def summarize(path: Path, skip_first: int = 0) -> dict:
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    meta = rows[0]
    if meta['type'] != 'metadata':
        raise ValueError('missing metadata')
    samples = [x for x in rows[1:] if x['type'] == 'sample'
               and x['elapsed_ns'] >= meta['interval_seconds'] * 0.75e9]
    samples = samples[skip_first:]
    if not samples:
        raise ValueError('no complete samples after skip_first')
    rates = [x['cpu_percent_one_core'] for x in samples]
    elapsed = sum(x['elapsed_ns'] for x in samples)
    cpu = sum(x['process_cpu_ns'] for x in samples)
    return {'complete_windows': len(samples), 'elapsed_seconds': elapsed / 1e9,
            'cpu_seconds': cpu / 1e9, 'weighted_cpu_percent_one_core': 100 * cpu / elapsed,
            'median_window_percent': statistics.median(rates),
            'max_window_percent': max(rates), 'python': meta['python'],
            'trio': meta['trio'], 'affinity': meta.get('affinity')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sample_file', type=Path)
    parser.add_argument('--skip-first', type=int, default=0, help='ignore warmup windows')
    args = parser.parse_args()
    print(json.dumps(summarize(args.sample_file, args.skip_first), indent=2))
