"""Sample a Linux process from outside it; no changes to the Trio application.

Example: python sample_pid_cpu.py PID --duration 300 --output cpu.jsonl
A target running CPython 3.15 does not need this script or any dependency.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import statistics
import sys
import time


def read_process(pid: int, ticks_per_second: int, page_size: int) -> dict:
    raw = Path(f'/proc/{pid}/stat').read_text()
    # comm may contain spaces or closing parentheses; the last ") " ends it.
    end = raw.rfind(') ')
    if end < 0:
        raise ValueError('invalid /proc stat')
    fields = raw[end + 2:].split()  # fields[0] is proc stat field 3 (state)
    return {
        'start_ticks': int(fields[19]),
        'cpu_seconds': (int(fields[11]) + int(fields[12])) / ticks_per_second,
        'rss_bytes': int(fields[21]) * page_size,
        'threads': int(fields[17]),
    }


def sample(pid: int, output: Path, interval: float, duration: float) -> None:
    if interval <= 0 or duration <= 0:
        raise ValueError('interval and duration must be positive')
    ticks = os.sysconf('SC_CLK_TCK')
    pages = os.sysconf('SC_PAGE_SIZE')
    initial = read_process(pid, ticks, pages)
    metadata = {
        'type': 'metadata', 'schema_version': 1, 'pid': pid,
        'process_start_ticks': initial['start_ticks'],
        'sampler_python': sys.version, 'interval_seconds': interval,
        'cpu_percent_definition': '100 * delta process CPU seconds / elapsed seconds; one core = 100%',
        'scope': 'target process (all its threads), not children or entire host',
        'clk_tck': ticks, 'page_size': pages,
    }
    try:
        metadata['cgroup_cpu_max'] = Path('/sys/fs/cgroup/cpu.max').read_text().strip()
    except OSError:
        pass
    output.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + duration
    previous_wall = time.perf_counter()
    previous_cpu = initial['cpu_seconds']
    with output.open('w', encoding='utf-8') as stream:
        stream.write(json.dumps(metadata) + '\n')
        next_sample = time.monotonic() + interval
        while True:
            remaining = min(next_sample, deadline) - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            now = time.perf_counter()
            try:
                current = read_process(pid, ticks, pages)
            except FileNotFoundError:
                stream.write(json.dumps({'type': 'stopped', 'reason': 'process exited'}) + '\n')
                break
            if current['start_ticks'] != initial['start_ticks']:
                stream.write(json.dumps({'type': 'stopped', 'reason': 'pid reused'}) + '\n')
                break
            elapsed = now - previous_wall
            used = current['cpu_seconds'] - previous_cpu
            stream.write(json.dumps({
                'type': 'sample', 'timestamp_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                'elapsed_seconds': elapsed, 'process_cpu_seconds': used,
                'cpu_percent_one_core': 100 * used / elapsed,
                'rss_bytes': current['rss_bytes'], 'threads': current['threads'],
            }) + '\n')
            stream.flush()
            previous_wall, previous_cpu = now, current['cpu_seconds']
            if time.monotonic() >= deadline:
                break
            next_sample += interval


def summarize(path: Path, skip_first: int = 0) -> dict:
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    meta = rows[0]
    if meta['type'] != 'metadata':
        raise ValueError('missing metadata')
    windows = [x for x in rows[1:] if x['type'] == 'sample'
               and x['elapsed_seconds'] >= meta['interval_seconds'] * 0.75]
    windows = windows[skip_first:]
    if not windows:
        raise ValueError('no full windows remain')
    cpu = sum(x['process_cpu_seconds'] for x in windows)
    elapsed = sum(x['elapsed_seconds'] for x in windows)
    return {
        'pid': meta['pid'], 'full_windows': len(windows),
        'elapsed_seconds': elapsed, 'cpu_seconds': cpu,
        'weighted_cpu_percent_one_core': 100 * cpu / elapsed,
        'median_window_percent': statistics.median(x['cpu_percent_one_core'] for x in windows),
        'max_window_percent': max(x['cpu_percent_one_core'] for x in windows),
        'rss_mib_median': statistics.median(x['rss_bytes'] for x in windows) / 2**20,
        'thread_count_median': statistics.median(x['threads'] for x in windows),
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pid', type=int, nargs='?')
    parser.add_argument('--output', type=Path, default=Path('trio-process-cpu.jsonl'))
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--duration', type=float, default=300.0)
    parser.add_argument('--summary', type=Path)
    parser.add_argument('--skip-first', type=int, default=0)
    args = parser.parse_args()
    if args.summary:
        print(json.dumps(summarize(args.summary, args.skip_first), indent=2))
    elif args.pid is not None:
        sample(args.pid, args.output, args.interval, args.duration)
        print(json.dumps(summarize(args.output), indent=2))
    else:
        parser.error('PID is required unless --summary is used')
