"""Check fixed work and reporting through the benchmark's public CLI."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

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
    for field in ("dispatch_start_delay_ms", "dispatch_finish_delay_ms"):
        delays = result[field]
        assert 0 <= delays["p50"] <= delays["p95"] <= delays["p99"] <= delays["max"]
    for field in ("dispatch_start_missed_ticks", "dispatch_finish_missed_ticks"):
        assert isinstance(result[field], int)
        assert 0 <= result[field] <= result["ticks"]
    assert result["fixed_rate_maintained"] is (
        result["dispatch_start_missed_ticks"] == 0
        and result["dispatch_finish_missed_ticks"] == 0
    )


@pytest.mark.parametrize("module", ["trio", "trior"])
def test_single_trial_output_file(module, tmp_path):
    output = tmp_path / "trial.json"
    process = run_cli(module, "--duration", "0.1", "--hz", "20", "--output", str(output))
    assert process.returncode == 0, process.stderr
    assert process.stdout == ""
    result = json.loads(output.read_text())
    assert result["module"] == module
    assert result["completed_total"] == 1200


def test_comparison_writes_fresh_process_samples(tmp_path):
    output = tmp_path / "comparison.json"
    process = run_cli("compare", "--duration", "0.1", "--frequencies", "10", "20",
                      "--repeat", "1", "--output", str(output))
    assert process.returncode == 0, process.stderr
    report = json.loads(output.read_text())
    assert process.stdout == ""
    assert report["complete"] is True
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


def test_comparison_preserves_completed_trials_after_failure(tmp_path, monkeypatch):
    output = tmp_path / "partial.json"
    output.write_text('{"complete": true, "samples": ["old run"]}')
    args = SimpleNamespace(duration=0.1, frequencies=[10], repeat=1, output=output)
    calls = 0
    monkeypatch.setattr(benchmark, "environment", lambda: {})

    def run(command, **kwargs):
        nonlocal calls
        checkpoint = json.loads(output.read_text())
        assert checkpoint["complete"] is False
        if calls == 0:
            assert checkpoint["samples"] == []
            calls += 1
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "module": "trio", "hz": 10, "cpu_percent": 1.0,
                "completed_total": 600, "fixed_rate_maintained": True,
            }))
        assert len(checkpoint["samples"]) == 1
        assert checkpoint["samples"][0]["completed_total"] == 600
        calls += 1
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(benchmark.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        benchmark.compare(args)
    assert calls == 2
    checkpoint = json.loads(output.read_text())
    assert checkpoint["complete"] is False
    assert len(checkpoint["samples"]) == 1
    assert checkpoint["samples"][0]["module"] == "trio"
    assert checkpoint["samples"][0]["repeat"] == 0


def test_invalid_output_prevents_trial_launch(tmp_path, monkeypatch):
    output = tmp_path / "directory"
    output.mkdir()
    args = SimpleNamespace(duration=0.1, frequencies=[10], repeat=1, output=output)
    monkeypatch.setattr(benchmark, "environment", lambda: {})

    def unexpected_trial(*args, **kwargs):
        pytest.fail("trial launched before validating the output destination")

    monkeypatch.setattr(benchmark.subprocess, "run", unexpected_trial)
    with pytest.raises(OSError):
        benchmark.compare(args)
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("starts,finishes,start_misses,finish_misses", [
    ([0.001, 0.002], [0.003, 0.004], 0, 0),
    ([0.001, 0.011], [0.003, 0.012], 1, 1),
    ([0.001, 0.002], [0.003, 0.012], 0, 1),
])
def test_dispatch_overrun_detection(starts, finishes, start_misses, finish_misses):
    result = benchmark.dispatch_metrics(starts, finishes, 0.01)
    assert result["dispatch_start_missed_ticks"] == start_misses
    assert result["dispatch_finish_missed_ticks"] == finish_misses
    assert result["fixed_rate_maintained"] is (start_misses == finish_misses == 0)
    assert result["dispatch_start_delay_ms"]["max"] == pytest.approx(max(starts) * 1000)
    assert result["dispatch_finish_delay_ms"]["max"] == pytest.approx(max(finishes) * 1000)


def test_atomic_output_preserves_previous_report_on_replace_failure(tmp_path, monkeypatch):
    output = tmp_path / "report.json"
    original = '{"complete": false, "samples": []}\n'
    output.write_text(original)

    def failed_replace(source, destination):
        assert json.loads(source.read_text()) == {"complete": True}
        assert destination.read_text() == original
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(Path, "replace", failed_replace)
    with pytest.raises(OSError, match="simulated replacement failure"):
        benchmark.write_json(output, {"complete": True})
    assert output.read_text() == original
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("duration,hz", [(0, 10), (-1, 10), (1, 0), (1, -10),
                                         (0.01, 10), (0.15, 10), (float("nan"), 10),
                                         (float("inf"), 10)])
def test_invalid_schedule_rejected(duration, hz):
    with pytest.raises((ValueError, OverflowError)):
        benchmark.ticks_for(duration, hz)


def test_fractional_duration_preserves_exact_work():
    assert benchmark.ticks_for(0.1, 20) == 2
    assert benchmark.ticks_for(60, 100) == 6000
