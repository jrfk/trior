"""Check fixed work and reporting through the benchmark's public CLI."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "benchmarks" / "bench_steady_state.py"
spec = importlib.util.spec_from_file_location("bench_steady_state", SCRIPT)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def run_cli(*arguments):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        capture_output=True, text=True, timeout=30,
    )


@pytest.mark.parametrize("module", ["trio", "trior"])
def test_fixed_work_and_metrics(module):
    process = run_cli(module, "--duration", "0.1", "--hz", "20")
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["workers"] == {"timer": 200, "event": 100, "channel": 150, "socket": 150}
    assert result["ticks"] == 2
    assert result["completed"] == {"timer": 400, "event": 200, "channel": 300, "socket": 300}
    assert result["completed_total"] == result["expected_completed"] == 1200
    assert result["latency_samples"] == 1200
    assert result["equivalent_work_verified"] is True
    assert result["wall_s"] >= 0.1
    assert result["cpu_s"] > 0
    assert result["cpu_percent"] == pytest.approx(100 * result["cpu_s"] / result["wall_s"])
    assert result["cpu_per_completion_s"] == pytest.approx(result["cpu_s"] / 1200)
    assert result["peak_rss_bytes"] > 0
    latency = result["latency_ms"]
    assert 0 <= latency["p50"] <= latency["p95"] <= latency["p99"] <= latency["max"]


def test_comparison_writes_fresh_process_samples(tmp_path):
    output = tmp_path / "comparison.json"
    process = run_cli("compare", "--duration", "0.1", "--frequencies", "10", "20",
                      "--repeat", "1", "--output", str(output))
    assert process.returncode == 0, process.stderr
    report = json.loads(output.read_text())
    assert len(report["samples"]) == 4
    for hz, expected in ((10, 600), (20, 1200)):
        samples = [sample for sample in report["samples"] if sample["hz"] == hz]
        assert {sample["module"] for sample in samples} == {"trio", "trior"}
        assert all(sample["completed_total"] == expected for sample in samples)
        summary = next(row for row in report["summary"] if row["hz"] == hz)
        medians = summary["medians"]
        assert summary["cpu_reduction_percent"] == pytest.approx(
            100 * (1 - medians["trior"]["cpu_s"] / medians["trio"]["cpu_s"]))

    # Keeping the total constant must not hide a mismatch between worker types.
    sample = report["samples"][0]
    sample["completed"]["timer"] -= 1
    sample["completed"]["socket"] += 1
    with pytest.raises(RuntimeError, match="unequal completed work"):
        benchmark.summarize(report["samples"], [10, 20], 0.1)


@pytest.mark.parametrize("duration,hz", [(0, 10), (-1, 10), (1, 0), (1, -10),
                                         (0.01, 10), (0.15, 10), (float("nan"), 10),
                                         (float("inf"), 10)])
def test_invalid_schedule_rejected(duration, hz):
    with pytest.raises((ValueError, OverflowError)):
        benchmark.ticks_for(duration, hz)


def test_fractional_duration_preserves_exact_work():
    assert benchmark.ticks_for(0.1, 20) == 2
    assert benchmark.ticks_for(60, 100) == 6000
