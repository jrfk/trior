"""Separate Trio socket fast, blocked, and idle paths in fresh processes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

import trio

CASES = ("ready_recv", "blocked_pingpong", "idle_read")
ITERATIONS = 4000
REPEATS = 7


def percentile_99(values: list[int]) -> int:
    return sorted(values)[(99 * (len(values) - 1)) // 100]


async def run_case(case: str) -> dict[str, int]:
    left, right = trio.socket.socketpair()
    try:
        if case == "ready_recv":
            # Preload all bytes before the first Trio receive; this exercises
            # _nonblocking_helper's immediate-success/checkpoint path.
            assert await right.send(b"x" * ITERATIONS) == ITERATIONS
            for _ in range(ITERATIONS):
                assert await left.recv(1) == b"x"
            return {"operations": ITERATIONS, "bytes": ITERATIONS}

        if case == "blocked_pingpong":
            roundtrips: list[int] = []

            async def ping() -> None:
                for _ in range(ITERATIONS):
                    start = time.perf_counter_ns()
                    assert await left.send(b"x") == 1
                    assert await left.recv(1) == b"x"
                    roundtrips.append(time.perf_counter_ns() - start)

            async def pong() -> None:
                for _ in range(ITERATIONS):
                    assert await right.recv(1) == b"x"
                    assert await right.send(b"x") == 1

            async with trio.open_nursery() as nursery:
                nursery.start_soon(ping)
                nursery.start_soon(pong)
            return {"operations": ITERATIONS, "bytes": ITERATIONS * 4,
                    "roundtrip_p99_ns": percentile_99(roundtrips)}

        assert case == "idle_read"

        async def wake() -> None:
            await trio.sleep(0.25)
            assert await right.send(b"x") == 1

        async with trio.open_nursery() as nursery:
            nursery.start_soon(wake)
            assert await left.recv(1) == b"x"
        return {"operations": 1, "bytes": 2}
    finally:
        left.close()
        right.close()


def measure(case: str) -> dict[str, object]:
    cpu_start = time.process_time_ns()
    wall_start = time.perf_counter_ns()
    result = trio.run(run_case, case)
    cpu_ns = time.process_time_ns() - cpu_start
    wall_ns = time.perf_counter_ns() - wall_start
    return {"case": case, "cpu_ns": cpu_ns, "wall_ns": wall_ns,
            "cpu_occupancy": cpu_ns / wall_ns, **result}


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        print(json.dumps(measure(sys.argv[2])))
        return
    if len(sys.argv) != 1:
        raise SystemExit("usage: bench.py [--worker CASE]")

    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    rows = []
    for iteration in range(REPEATS):
        for case in CASES:
            child = subprocess.run(
                [sys.executable, __file__, "--worker", case],
                check=True, text=True, capture_output=True,
            )
            rows.append({**json.loads(child.stdout), "iteration": iteration})
    summaries = {}
    for case in CASES:
        subset = [r for r in rows if r["case"] == case]
        summaries[case] = {
            key: statistics.median(r[key] for r in subset)
            for key in ("cpu_ns", "wall_ns", "cpu_occupancy")
        }
        if case == "blocked_pingpong":
            summaries[case]["roundtrip_p99_ns"] = statistics.median(
                r["roundtrip_p99_ns"] for r in subset
            )
    output = {"runtime": sys.version, "trio": trio.__version__,
              "iterations": ITERATIONS, "repeats": REPEATS,
              "cases": summaries, "raw": rows}
    destination = Path(__file__).resolve().parents[2] / "results" / "stage11"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "io_baseline.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
