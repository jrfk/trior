"""Paired fresh-process CPU benchmarks for the independent runtime."""

import json
import os
import random
import statistics
import subprocess
import sys
import time

import trio
from trio_rust_poc import runtime

TASKS = 600
CASES = ("checkpoint", "timers", "mixed", "idle", "deadlines")
MODES = ("trio", "rust")


async def workload(api, case):
    count = 0
    lateness = []

    async def checkpoint_worker():
        nonlocal count
        for _ in range(100):
            await api.sleep(0)
            count += 1

    async def periodic_worker():
        nonlocal count
        target = time.perf_counter()
        for _ in range(20):
            target += 0.01
            await api.sleep(max(0, target - time.perf_counter()))
            lateness.append(max(0, time.perf_counter() - target))
            count += 1

    async def deadline_worker():
        nonlocal count
        for _ in range(10):
            with api.CancelScope(deadline=api.current_time() + 0.01) as scope:
                await api.sleep_forever()
            assert scope.cancelled_caught
            count += 1

    async with api.open_nursery() as outer:
        if case == "checkpoint":
            for _ in range(TASKS):
                outer.start_soon(checkpoint_worker)
        elif case == "timers":
            for _ in range(TASKS):
                outer.start_soon(periodic_worker)
        elif case == "deadlines":
            for _ in range(TASKS):
                outer.start_soon(deadline_worker)
        else:
            active = 20 if case == "mixed" else 0
            for _ in range(TASKS - active):
                outer.start_soon(api.sleep_forever)
            if active:
                async with api.open_nursery() as inner:
                    for _ in range(active):
                        inner.start_soon(periodic_worker)
            else:
                await api.sleep(0.25)
            outer.cancel_scope.cancel()

    assert count == {"checkpoint": 60_000, "timers": 12_000, "mixed": 400, "idle": 0, "deadlines": 6000}[case]
    p99 = sorted(lateness)[99 * (len(lateness) - 1) // 100] if lateness else None
    return count, p99


def worker(case, mode):
    api = trio if mode == "trio" else runtime
    start_cpu = time.process_time_ns()
    start_wall = time.perf_counter_ns()
    count, p99 = api.run(workload, api, case)
    cpu = time.process_time_ns() - start_cpu
    wall = time.perf_counter_ns() - start_wall
    return {"count": count, "cpu_ns": cpu, "wall_ns": wall, "cpu_occupancy": cpu / wall,
            "timer_p99_ms": p99 * 1000 if p99 is not None else None}


def main():
    if len(sys.argv) == 3:
        print(json.dumps(worker(*sys.argv[1:])))
        return
    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    rng = random.Random(31)
    raw = {}
    summary = {}
    for case in CASES:
        rows = []
        for _ in range(7):
            order = list(MODES)
            rng.shuffle(order)
            rows.append({
                mode: json.loads(subprocess.check_output(
                    [sys.executable, __file__, case, mode], timeout=30
                )) for mode in order
            })
            assert rows[-1]["trio"]["count"] == rows[-1]["rust"]["count"]
        raw[case] = rows
        summary[case] = {
            mode: {key: statistics.median(row[mode][key] for row in rows)
                   for key in rows[0][mode] if rows[0][mode][key] is not None}
            for mode in MODES
        }
        summary[case]["cpu_speedup"] = statistics.median(
            row["trio"]["cpu_ns"] / row["rust"]["cpu_ns"] for row in rows
        )
    print(json.dumps({"python": sys.version, "trio": trio.__version__,
                      "raw": raw, "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
