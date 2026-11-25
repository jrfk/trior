"""Profile many simultaneously ready Trio socket file descriptors."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import time

import trio
import trio.testing


async def workload(fds: int, waves: int) -> dict[str, int]:
    pairs = [socket.socketpair() for _ in range(fds)]
    readers = [trio.socket.from_stdlib_socket(pair[0]) for pair in pairs]
    writers = [pair[1] for pair in pairs]
    completed = 0
    wave_finished = trio.Event()
    wave_latencies: list[int] = []

    async def reader(index: int) -> None:
        nonlocal completed
        for _ in range(waves):
            assert await readers[index].recv(1) == b"x"
            completed += 1
            if completed == fds:
                wave_finished.set()

    try:
        async with trio.open_nursery() as nursery:
            for index in range(fds):
                nursery.start_soon(reader, index)
            for _ in range(waves):
                # First ensure the receivers are registered and blocked.
                await trio.testing.wait_all_tasks_blocked()
                completed = 0
                wave_finished = trio.Event()
                start = time.perf_counter_ns()
                for writer in writers:
                    assert writer.send(b"x") == 1
                await wave_finished.wait()
                wave_latencies.append(time.perf_counter_ns() - start)
        assert len(wave_latencies) == waves
        return {"events": fds * waves, "fds": fds, "waves": waves,
                "wave_p99_ns": sorted(wave_latencies)[(99 * (waves - 1)) // 100]}
    finally:
        for reader in readers:
            reader.close()
        for writer in writers:
            writer.close()


def measure(fds: int, waves: int) -> dict[str, int | float]:
    cpu_start = time.process_time_ns()
    wall_start = time.perf_counter_ns()
    data = trio.run(workload, fds, waves)
    cpu_ns = time.process_time_ns() - cpu_start
    wall_ns = time.perf_counter_ns() - wall_start
    return {**data, "cpu_ns": cpu_ns, "wall_ns": wall_ns,
            "cpu_per_event_ns": cpu_ns / data["events"],
            "cpu_occupancy": cpu_ns / wall_ns}


def main() -> None:
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        print(json.dumps(measure(int(sys.argv[2]), int(sys.argv[3]))))
        return
    if len(sys.argv) != 1:
        raise SystemExit("usage: dense.py [--worker FDS WAVES]")
    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    variants = ((1, 4096), (64, 64), (256, 16))
    rows = []
    for iteration in range(7):
        for fds, waves in variants:
            result = subprocess.run(
                [sys.executable, __file__, "--worker", str(fds), str(waves)],
                capture_output=True, text=True, check=True,
            )
            rows.append({"iteration": iteration, **json.loads(result.stdout)})
    summaries = {}
    for fds, waves in variants:
        subset = [r for r in rows if (r["fds"], r["waves"]) == (fds, waves)]
        summaries[str(fds)] = {
            name: statistics.median(r[name] for r in subset)
            for name in ("cpu_ns", "wall_ns", "cpu_per_event_ns",
                         "cpu_occupancy", "wave_p99_ns")
        }
    destination = Path(__file__).resolve().parents[2] / "results" / "stage12"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "dense_io.json").write_text(json.dumps({
        "runtime": sys.version, "trio": trio.__version__, "repeats": 7,
        "summaries": summaries, "raw": rows,
    }, indent=2) + "\n")
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
