"""Paired benchmark of synchronization primitives."""
import json
import os
import random
import statistics
import subprocess
import sys
import time

import trio
from trior import _runtime as runtime

CASES = ("event", "lock", "semaphore", "channel0", "channel64")


async def workload(api, case):
    completed = 0
    if case == "event":
        for _ in range(20):
            event = api.Event()
            async def worker():
                nonlocal completed
                await event.wait()
                completed += 1
            async with api.open_nursery() as nursery:
                for _ in range(600):
                    nursery.start_soon(worker)
                await api.sleep(0)
                event.set()
        assert completed == 12000
    elif case in ("lock", "semaphore"):
        primitive = api.Lock() if case == "lock" else api.Semaphore(8)
        async def worker():
            nonlocal completed
            for _ in range(20):
                async with primitive:
                    completed += 1
        async with api.open_nursery() as nursery:
            for _ in range(600):
                nursery.start_soon(worker)
        assert completed == 12000
    else:
        send, receive = api.open_memory_channel(0 if case == "channel0" else 64)
        async def producer():
            async with send:
                for n in range(12000):
                    await send.send(n)
        async with api.open_nursery() as nursery:
            nursery.start_soon(producer)
            async with receive:
                async for value in receive:
                    assert value == completed
                    completed += 1
        assert completed == 12000
    return completed


def main():
    if len(sys.argv) == 3:
        api = trio if sys.argv[2] == "trio" else runtime
        start = time.process_time_ns()
        count = api.run(workload, api, sys.argv[1])
        print(json.dumps({"cpu_ns": time.process_time_ns()-start, "count": count}))
        return
    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    raw, summary = {}, {}
    rng = random.Random(31)
    for case in CASES:
        rows = []
        for _ in range(7):
            order = ["trio", "rust"]
            rng.shuffle(order)
            rows.append({mode: json.loads(subprocess.check_output(
                [sys.executable, __file__, case, mode], timeout=30)) for mode in order})
        raw[case] = rows
        summary[case] = {mode: statistics.median(row[mode]["cpu_ns"] for row in rows)
                         for mode in ("trio", "rust")}
        summary[case]["speedup"] = statistics.median(
            row["trio"]["cpu_ns"]/row["rust"]["cpu_ns"] for row in rows)
    print(json.dumps({"summary": summary, "raw": raw}, indent=2))


if __name__ == "__main__":
    main()
