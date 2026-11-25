"""Fixed-rate 600-worker comparison; every scheduled operation must complete.

Run `python benchmarks/bench_steady_state.py compare --output /tmp/steady.json`.
Each sample runs in a fresh process. CPU occupancy uses one core = 100%.
"""
import argparse
from array import array
import importlib
import json
import math
import os
import platform
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path

COUNTS = {"timer": 200, "event": 100, "channel": 150, "socket": 150}
WORKERS = sum(COUNTS.values())


def ticks_for(duration, hz):
    if not math.isfinite(duration) or duration <= 0 or hz <= 0:
        raise ValueError("duration and frequency must be positive")
    ticks = round(duration * hz)
    if ticks < 1:
        raise ValueError("duration and frequency must be positive with at least one tick")
    if not math.isclose(ticks, duration * hz, rel_tol=0, abs_tol=1e-8):
        raise ValueError("duration * frequency must be an integer")
    return ticks


def peak_rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def ensure_socket_capacity():
    # Reserve descriptors for both ends of each pair and runtime overhead.
    required = 2 * COUNTS["socket"] + 32
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft != resource.RLIM_INFINITY and soft < required:
        if hard != resource.RLIM_INFINITY and hard < required:
            raise RuntimeError(f"benchmark needs an open-file limit of at least {required}")
        resource.setrlimit(resource.RLIMIT_NOFILE, (required, hard))


def percentile(values, fraction):
    return values[max(0, math.ceil(len(values) * fraction) - 1)]


async def workload(api, duration, hz):
    ticks = ticks_for(duration, hz)
    # Keep each release observable even when a worker falls behind.
    events = [api.Event() for _ in range(ticks)]
    channels = [api.open_memory_channel(ticks) for _ in range(COUNTS["channel"])]
    pairs = [api.socket.socketpair() for _ in range(COUNTS["socket"])]
    samples = {kind: [array("d", [0.0]) * ticks for _ in range(count)]
               for kind, count in COUNTS.items()}
    completed = {kind: [0] * count for kind, count in COUNTS.items()}
    ready = api.Event()
    start = api.Event()
    arrived = 0
    epoch = 0.0

    async def worker(kind, index):
        nonlocal arrived
        arrived += 1
        if arrived == WORKERS:
            ready.set()
        await start.wait()
        for tick in range(ticks):
            deadline = epoch + (tick + 1) / hz
            if kind == "timer":
                await api.sleep_until(deadline)
            elif kind == "event":
                await events[tick].wait()
            elif kind == "channel":
                value = await channels[index][1].receive()
                if value != tick:
                    raise RuntimeError("channel sequence mismatch")
            else:
                if await pairs[index][0].recv(1) != b"x":
                    raise RuntimeError("socket payload mismatch")
            samples[kind][index][tick] = max(0.0, api.current_time() - deadline)
            completed[kind][index] += 1

    try:
        async with api.open_nursery() as nursery:
            for kind, count in COUNTS.items():
                for index in range(count):
                    nursery.start_soon(worker, kind, index)
            await ready.wait()
            cpu_start = time.process_time()
            wall_start = time.perf_counter()
            epoch = api.current_time()
            start.set()
            for tick in range(ticks):
                await api.sleep_until(epoch + (tick + 1) / hz)
                events[tick].set()
                for send, _ in channels:
                    send.send_nowait(tick)
                for _, send in pairs:
                    # The async facade handles backpressure without dropping work.
                    if await send.send(b"x") != 1:
                        raise RuntimeError("short socket send")
        wall = time.perf_counter() - wall_start
        cpu = time.process_time() - cpu_start
        rss = peak_rss_bytes()
    finally:
        for pair in pairs:
            for sock in pair:
                sock.close()
        for pair in channels:
            for channel in pair:
                channel.close()
    if any(value != ticks for counts in completed.values() for value in counts):
        raise RuntimeError("incomplete work")
    latency = sorted(
        value for workers in samples.values() for values in workers for value in values
    )
    expected = WORKERS * ticks
    return dict(duration_s=duration, hz=hz, ticks=ticks, workers=COUNTS,
                completed={kind: sum(values) for kind, values in completed.items()},
                expected_completed=expected, completed_total=sum(map(sum, completed.values())),
                equivalent_work_verified=True, wall_s=wall, cpu_s=cpu,
                cpu_percent=100 * cpu / wall, cpu_per_completion_s=cpu / expected,
                drain_s=max(0, wall - duration), throughput=expected / wall,
                latency_samples=len(latency),
                latency_ms={name: percentile(latency, q)*1000 for name, q in
                            (("p50", .5), ("p95", .95), ("p99", .99), ("max", 1))},
                peak_rss_bytes=rss)


def environment():
    return dict(python=sys.version, platform=platform.platform(), machine=platform.machine(),
                affinity=sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
                reactor=os.environ.get("TRIOR_REACTOR", "platform default"))


def summarize(samples, frequencies, duration):
    summary = []
    for hz in frequencies:
        ticks = ticks_for(duration, hz)
        expected = {kind: count * ticks for kind, count in COUNTS.items()}
        medians = {}
        for module in ("trio", "trior"):
            group = [s for s in samples if s["module"] == module and s["hz"] == hz]
            if not group or any(
                s["completed"] != expected or s["completed_total"] != sum(expected.values())
                or s["ticks"] != ticks or s["duration_s"] != duration
                or not s["equivalent_work_verified"]
                for s in group
            ):
                raise RuntimeError(f"{module} {hz}Hz: unequal completed work")
            metrics = ("cpu_s", "cpu_percent", "wall_s", "peak_rss_bytes",
                       "cpu_per_completion_s", "drain_s", "throughput")
            medians[module] = {key: statistics.median(s[key] for s in group) for key in metrics}
            medians[module]["latency_ms"] = {
                key: statistics.median(s["latency_ms"][key] for s in group)
                for key in ("p50", "p95", "p99", "max")
            }
        trio, trior = medians["trio"], medians["trior"]
        summary.append(dict(
            hz=hz, medians=medians, completed_total=sum(expected.values()),
            cpu_reduction_percent=100 * (1 - trior["cpu_s"] / trio["cpu_s"]),
            occupancy_reduction_percent=100 * (1 - trior["cpu_percent"] / trio["cpu_percent"]),
        ))
    return summary


def compare(args):
    samples = []
    script = str(Path(__file__).resolve())
    for repeat in range(args.repeat):
        order = ("trio", "trior") if repeat % 2 == 0 else ("trior", "trio")
        for hz in args.frequencies:
            for module in order:
                command = [sys.executable, script, module,
                           "--duration", str(args.duration), "--hz", str(hz)]
                result = subprocess.run(command, text=True, stdout=subprocess.PIPE, check=True,
                                        timeout=args.duration * 3 + 60)
                sample = json.loads(result.stdout)
                sample["repeat"] = repeat
                samples.append(sample)
                print(f"{module} {hz}Hz repeat {repeat + 1}: {sample['cpu_percent']:.2f}% CPU",
                      file=sys.stderr)
    summary = summarize(samples, args.frequencies, args.duration)
    report = dict(environment=environment(), samples=samples, summary=summary)
    data = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(data + "\n")
    else:
        print(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module", choices=("trio", "trior", "compare"))
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--hz", type=int, default=10)
    parser.add_argument("--frequencies", type=int, nargs="+", default=[10, 20, 50, 100])
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.repeat < 1:
            raise ValueError("repeat must be positive")
        if args.module == "compare" and len(set(args.frequencies)) != len(args.frequencies):
            raise ValueError("frequencies must be unique")
        for hz in args.frequencies if args.module == "compare" else [args.hz]:
            ticks_for(args.duration, hz)
    except (ValueError, OverflowError) as error:
        parser.error(str(error))
    if args.module == "compare":
        compare(args)
    else:
        ensure_socket_capacity()
        api = importlib.import_module(args.module)
        if args.module == "trio" and api.__version__ != "0.35.0":
            raise RuntimeError("reference Trio must be 0.35.0")
        result = api.run(workload, api, args.duration, args.hz)
        result.update(module=args.module, environment=environment())
        print(json.dumps(result))


if __name__ == "__main__":
    main()
