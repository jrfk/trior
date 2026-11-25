"""Compare sequential startup of many long-lived children."""
import argparse
import importlib
import json
import statistics
import time


def sample(api, count):
    async def main():
        release = api.Event()

        async def child(i, *, task_status):
            task_status.started(i)
            await release.wait()

        async with api.open_nursery() as nursery:
            for i in range(count):
                assert await nursery.start(child, i) == i
            release.set()

    wall, cpu = time.perf_counter(), time.process_time()
    api.run(main)
    return time.perf_counter()-wall, time.process_time()-cpu


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("module")
    parser.add_argument("--count", type=int, default=600)
    parser.add_argument("--repeat", type=int, default=7)
    args = parser.parse_args()
    api = importlib.import_module(args.module)
    samples = [sample(api, args.count) for _ in range(args.repeat)]
    print(json.dumps({
        "module": args.module,
        "count": args.count,
        "wall_s": statistics.median(x[0] for x in samples),
        "cpu_s": statistics.median(x[1] for x in samples),
        "samples": samples,
    }))
