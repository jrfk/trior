#!/usr/bin/env python3
"""Fresh-process, paired benchmark runner for the Trio Rust batch PoC.

Run from the project root with the extension installed and PYTHONPATH=python.
The worker uses only stdlib, Trio, and trio_rust_poc.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import time
from typing import Any


HERE = Path(__file__).resolve().parent
MODES = ("python", "python-batch", "rust", "rust-opt", "rust-fast")


def describe_environment() -> dict[str, Any]:
    cpu_model = None
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu_model = line.partition(":")[2].strip()
                break
    except OSError:
        pass
    cgroup = {}
    for name in ("cpu.max", "cpuset.cpus.effective"):
        try:
            cgroup[name] = Path("/sys/fs/cgroup", name).read_text().strip()
        except OSError:
            pass
    return {
        "python": sys.version, "implementation": platform.python_implementation(),
        "executable": sys.executable, "platform": platform.platform(),
        "machine": platform.machine(), "cpu_count": os.cpu_count(), "cpu_model": cpu_model,
        "affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "cgroup": cgroup, "gc_enabled": gc.isenabled(), "gc_threshold": gc.get_threshold(),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
        "clock": {name: vars(time.get_clock_info(name)) for name in ("perf_counter", "process_time")},
        "harness_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in (HERE / "run.py", HERE / "workloads.py")},
        "source_sha256": {str(p.relative_to(HERE.parent)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (HERE.parent / "src/lib.rs", HERE.parent / "python/trio_rust_poc/__init__.py")},
    }


def quantile(values: list[float], fraction: float) -> float:
    """Linearly interpolated empirical quantile; definition retained in metadata."""
    if not values:
        raise ValueError("No samples")
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def distribution(values: list[float]) -> dict[str, Any]:
    median = statistics.median(values)
    return {
        "n": len(values), "median": median, "min": min(values), "max": max(values),
        "mean": statistics.mean(values), "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "mad": statistics.median(abs(value - median) for value in values),
    }


def worker(spec: dict[str, Any]) -> dict[str, Any]:
    cpu = spec.get("cpu")
    if cpu is not None:
        os.sched_setaffinity(0, {cpu})
    import trio
    from trio_rust_poc import activate
    from workloads import execute

    activate(spec["mode"])
    # Keep stock scheduling policy; only seed its random batch reversal.
    # Do not enable Trio's Hypothesis-specific deterministic scheduling mode.
    from trio._core import _run

    for index in range(spec["warmups"]):
        _run._r.seed(spec["scheduler_seed"] + index)
        trio.run(execute, spec["workload"], spec["params"])
    gc.collect()
    _run._r.seed(spec["scheduler_seed"])
    cpu_start = time.process_time_ns()
    wall_start = time.perf_counter_ns()
    counts = trio.run(execute, spec["workload"], spec["params"])
    wall_ns = time.perf_counter_ns() - wall_start
    cpu_ns = time.process_time_ns() - cpu_start
    latencies = {}
    for name, values in counts.get("latency_samples_ns", {}).items():
        latencies[name] = {
            "n": len(values), "p50_ns": quantile(values, .50), "p95_ns": quantile(values, .95),
            "p99_ns": quantile(values, .99), "max_ns": max(values),
        }
    return {
        "status": "ok", "mode": spec["mode"], "workload": spec["workload"],
        "params": spec["params"], "scheduler_seed": spec["scheduler_seed"],
        "warmups": spec["warmups"], "wall_ns": wall_ns, "cpu_ns": cpu_ns,
        "counts": counts, "latency": latencies, "pid": os.getpid(),
        "trio_version": trio.__version__,
        "affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
    }


def invoke(spec: dict[str, Any], timeout: float) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    child = subprocess.run(
        [sys.executable, str(HERE / "run.py"), "--worker"], input=json.dumps(spec),
        capture_output=True, text=True, env=env, timeout=timeout,
    )
    if child.returncode:
        raise RuntimeError(
            f"{spec['workload']}/{spec['mode']} failed ({child.returncode})\n"
            f"{child.stdout[-4000:]}\n{child.stderr[-12000:]}"
        )
    try:
        result = json.loads(child.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Worker emitted invalid JSON: {child.stdout[-4000:]}") from exc
    if child.stderr:
        result["stderr"] = child.stderr
    return result


def summarize(raw: list[dict[str, Any]], cases: list[str], modes: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for case in cases:
        selected = [row for row in raw if row["workload"] == case]
        if not selected:
            continue
        by_mode = {}
        baseline = {row["round"]: row for row in selected if row["mode"] == "python"}
        for mode in modes:
            rows = [row for row in selected if row["mode"] == mode]
            if not rows:
                continue
            values: dict[str, Any] = {
                "wall_ns": distribution([row["wall_ns"] for row in rows]),
                "cpu_ns": distribution([row["cpu_ns"] for row in rows]),
                "operations_per_cpu_second": distribution([
                    row["counts"]["operations"] * 1e9 / row["cpu_ns"] for row in rows
                ]),
            }
            if mode != "python":
                paired = [row for row in rows if row["round"] in baseline]
                if paired:
                    for metric in ("cpu_ns", "wall_ns"):
                        values[f"paired_{metric}_speedup"] = distribution([
                            baseline[row["round"]][metric] / row[metric] for row in paired
                        ])
            latency = {}
            for name in rows[0]["latency"]:
                latency[name] = {p: distribution([row["latency"][name][p] for row in rows])
                                 for p in ("p50_ns", "p95_ns", "p99_ns", "max_ns")}
            values["latency_quantiles_across_trials"] = latency
            by_mode[mode] = values
        summary[case] = {"params": selected[0]["params"], "unit": selected[0]["counts"]["unit"],
                         "modes": by_mode}
    return summary


def write_results(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = ["# Trio Rust PoC benchmark results", "", f"Status: {payload['status']}", "",
             "Speedup is baseline time / candidate time; values greater than 1 favor the candidate.",
             "Ratios are medians of paired fresh-process trials, not independent-median ratios.", "",
             "| Workload | Mode | CPU median (ms) | Wall median (ms) | Paired CPU speedup | CPU ratio range |",
             "| --- | --- | ---: | ---: | ---: | --- |"]
    for case, data in payload.get("summary", {}).items():
        for mode, result in data["modes"].items():
            ratio = result.get("paired_cpu_ns_speedup")
            speed = f"{ratio['median']:.3f}x" if ratio else "baseline"
            interval = f"{ratio['min']:.3f}–{ratio['max']:.3f}x" if ratio else "—"
            lines.append(f"| {case} | {mode} | {result['cpu_ns']['median']/1e6:.3f} | "
                         f"{result['wall_ns']['median']/1e6:.3f} | {speed} | {interval} |")
    lines.extend(["", "## Latency", "",
                  "Shown values are medians of each trial's quantile; raw per-probe samples are in JSON.", "",
                  "| Workload | Mode | Metric | p50 (µs) | p95 (µs) | p99 (µs) |",
                  "| --- | --- | --- | ---: | ---: | ---: |"])
    for case, data in payload.get("summary", {}).items():
        for mode, result in data["modes"].items():
            for name, latency in result["latency_quantiles_across_trials"].items():
                vals = [latency[p]["median"] / 1000 for p in ("p50_ns", "p95_ns", "p99_ns")]
                lines.append(f"| {case} | {mode} | {name} | {vals[0]:.3f} | {vals[1]:.3f} | {vals[2]:.3f} |")
    lines.extend(["", "## Scope", "",
                  "Synthetic local measurements on a shared execution host. No claim of robot or production performance.",
                  "mixed_600 wall time deliberately includes sleeping; use CPU time and latency rather than wall-time speedup.",
                  "The range is observed trial variability, not a confidence interval. A small difference or overlap is inconclusive.",
                  "Warmups, import/build time exclusions, calibration, affinity, environment, and trial order are retained in JSON."])
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--quick", action="store_true", help="3 trials, 80ms target, 80 latency probes")
    parser.add_argument("--normal", action="store_true", help="7 trials, 200ms target, 200 latency probes (default)")
    parser.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    parser.add_argument("--cases", nargs="+", help="Case names; use --list to see them")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--repeats", type=int)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--target-seconds", type=float)
    parser.add_argument("--no-calibrate", action="store_true", help="Use fixed base work counts")
    parser.add_argument("--seed", type=int, default=20261107)
    parser.add_argument("--cpu", default="auto", help="auto pins children to first allowed CPU; none disables pinning")
    parser.add_argument("--worker-timeout", type=float, default=120)
    parser.add_argument("--output", type=Path, default=Path("results/benchmark.json"))
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(json.load(sys.stdin))))
        return 0
    from workloads import CASES, parameters

    if args.list:
        for name, case in CASES.items():
            print(f"{name}: {case['description']}")
        return 0
    if args.quick and args.normal:
        parser.error("Choose either --quick or --normal")
    cases = args.cases or list(CASES)
    if any(case not in CASES for case in cases):
        parser.error("Unknown workload; use --list")
    repeats = args.repeats if args.repeats is not None else (3 if args.quick else 7)
    target = args.target_seconds if args.target_seconds is not None else (.08 if args.quick else .2)
    if repeats < 1 or args.warmups < 0 or target <= 0:
        parser.error("Require repeats >= 1, warmups >= 0, target-seconds > 0")
    if args.cpu == "none" or not hasattr(os, "sched_setaffinity"):
        cpu = None
    else:
        cpu = min(os.sched_getaffinity(0)) if args.cpu == "auto" else int(args.cpu)
        if cpu not in os.sched_getaffinity(0):
            parser.error(f"CPU {cpu} is outside this process's permitted affinity")
    metadata = describe_environment()
    metadata.update({
        "started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "modes": args.modes, "cases": cases, "repeats": repeats, "warmups": args.warmups,
        "preset": "quick" if args.quick else "normal", "calibration_target_wall_s": target,
        "cpu_pin": cpu, "order_seed": args.seed,
        "timing_scope": "trio.run including setup/cleanup; excludes imports, activate, gc.collect and warmup",
        "gc_policy": "enabled at interpreter default thresholds; explicit collection before timed run",
        "quantile_method": "linear interpolation at (n - 1) * q",
        "scheduler_rng": "Trio _run._r seeded; stock scheduling policy retained",
        "notes": ["Shared host; no isolation guarantee", "Mixed load is synthetic, not production replay",
                  "Calibration chooses one baseline-derived work count used by every mode",
                  "Fresh process for every calibration and measured trial; warmups run in that trial process"],
    })
    payload: dict[str, Any] = {"schema_version": 1, "status": "running", "metadata": metadata,
                               "calibration": {}, "raw_runs": [], "summary": {}}
    write_results(args.output, payload)
    chosen: dict[str, dict[str, Any]] = {}
    rng = random.Random(args.seed)
    try:
        for case in cases:
            params = parameters(case, quick=args.quick)
            entry: dict[str, Any] = {"scale": 1, "base_params": params}
            if CASES[case]["kind"] == "cpu" and not args.no_calibrate:
                spec = {"mode": "python", "workload": case, "params": params,
                        "warmups": args.warmups, "scheduler_seed": args.seed, "cpu": cpu}
                sample = invoke(spec, args.worker_timeout)
                scale = max(1, min(100, math.ceil(target * 1e9 / sample["wall_ns"])))
                entry.update({"sample": sample, "scale": scale})
                params = parameters(case, scale=scale, quick=args.quick)
            chosen[case] = params
            entry["selected_params"] = params
            payload["calibration"][case] = entry
            write_results(args.output, payload)
        sequence = 0
        for round_index in range(repeats):
            round_cases = list(cases)
            rng.shuffle(round_cases)
            for case in round_cases:
                ordered_modes = list(args.modes)
                rng.shuffle(ordered_modes)
                for mode in ordered_modes:
                    spec = {"mode": mode, "workload": case, "params": chosen[case],
                            "warmups": args.warmups, "scheduler_seed": args.seed + round_index,
                            "cpu": cpu}
                    result = invoke(spec, args.worker_timeout)
                    result.update({"round": round_index, "sequence": sequence,
                                   "pair_id": f"{round_index}:{case}"})
                    sequence += 1
                    # Equal counters across the three modes are part of validation.
                    peers = [row for row in payload["raw_runs"] if row["pair_id"] == result["pair_id"]]
                    for peer in peers:
                        a = {k: v for k, v in peer["counts"].items() if k != "latency_samples_ns"}
                        b = {k: v for k, v in result["counts"].items() if k != "latency_samples_ns"}
                        if a != b:
                            raise RuntimeError(f"Work counters differ for {case}: {peer['mode']} vs {mode}")
                    payload["raw_runs"].append(result)
                    payload["summary"] = summarize(payload["raw_runs"], cases, args.modes)
                    write_results(args.output, payload)
                    print(f"{round_index + 1}/{repeats} {case} {mode}: "
                          f"cpu={result['cpu_ns']/1e6:.2f}ms wall={result['wall_ns']/1e6:.2f}ms",
                          flush=True)
        payload["status"] = "complete"
    except (RuntimeError, subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        payload["status"] = "failed"
        payload["error"] = str(exc)
        raise
    finally:
        payload["metadata"]["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        write_results(args.output, payload)
        write_markdown(args.output.with_suffix(".summary.md"), payload)
    print(f"Saved {args.output} and {args.output.with_suffix('.summary.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
