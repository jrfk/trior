"""CPU and wall time for the Trio recv variants, in paired fresh processes."""

import json
import os
import random
import statistics
import subprocess
import sys

import trio

from attribute_recv import BATCHES, PAYLOAD, sample
from bench import measure
from recv_variants import install

MODES = ("stock", "python", "rust")
CASES = ("ready_recv", "blocked_pingpong", "idle_read")


def worker(case, mode):
    install(mode)
    if case == "ready_recv":
        cpu_ns = trio.run(sample, "stock")
        return {"cpu_ns": cpu_ns, "operations": BATCHES * len(PAYLOAD)}
    return measure(case)


def main():
    if len(sys.argv) == 3:
        print(json.dumps(worker(*sys.argv[1:])))
        return

    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    rng = random.Random(31)
    rows = {case: [] for case in CASES}
    summary = {}
    for case in CASES:
        for _ in range(11):
            order = list(MODES)
            rng.shuffle(order)
            round_results = {
                mode: json.loads(subprocess.check_output(
                    [sys.executable, __file__, case, mode], timeout=20
                ))
                for mode in order
            }
            assert len({r["operations"] for r in round_results.values()}) == 1
            rows[case].append(round_results)
        summary[case] = {
            mode: {
                metric: statistics.median(row[mode][metric] for row in rows[case])
                for metric in ("cpu_ns", "wall_ns", "roundtrip_p99_ns", "cpu_occupancy")
                if metric in rows[case][0][mode]
            }
            for mode in MODES
        }
    print(json.dumps({"python": sys.version, "trio": trio.__version__,
                      "summary": summary, "raw": rows}, indent=2))


if __name__ == "__main__":
    main()
