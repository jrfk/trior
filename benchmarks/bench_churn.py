"""Measure repeated task/scope completion inside a single run."""
import json
import sys
import time
from pathlib import Path

import trio
from trior import _runtime as runtime


def rss_kib():
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    raise RuntimeError("VmRSS unavailable")


async def workload(api):
    snapshots = []
    count = 0
    native = runtime._runtime.get() if api is runtime else None

    async def child():
        nonlocal count
        with api.CancelScope() as scope:
            for offset in range(10):
                scope.deadline = api.current_time() + 60 + offset
            await api.sleep(0)
        count += 1

    with api.CancelScope(deadline=api.current_time() + 60):
        for batch in range(1000):
            async with api.open_nursery() as nursery:
                for _ in range(100):
                    nursery.start_soon(child)
            if batch % 100 == 0 or batch == 999:
                snapshots.append({"completed": count, "rss_kib": rss_kib(),
                                  "native_counts": native.resource_counts() if native else None})
    assert count == 100000
    return snapshots


if __name__ == "__main__":
    api = trio if sys.argv[1] == "trio" else runtime
    start = time.process_time()
    snapshots = api.run(workload, api)
    print(json.dumps({"mode": sys.argv[1], "cpu_seconds": time.process_time()-start,
                      "snapshots": snapshots}, indent=2))
