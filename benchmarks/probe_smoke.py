"""Smoke-check CPU sampler and optional Trio hooks on the synthetic 600-task case."""
from pathlib import Path
import sys

import trio
from production_cpu_probe import ProcessCpuSampler, TrioStepCounter, summarize
from workloads import execute, parameters

output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('results/stage5/probe-smoke.jsonl')
with ProcessCpuSampler(output, interval=0.05):
    counts = trio.run(execute, 'mixed_600', parameters('mixed_600', quick=True))
assert counts['operations'] > 0
summary = summarize(output)
assert summary['complete_windows'] >= 2
assert summary['cpu_seconds'] > 0
counter = TrioStepCounter()
trio.run(execute, 'checkpoint_1', {'tasks': 1, 'steps': 20}, instruments=[counter])
assert counter.steps >= 20
assert counter.scheduled >= 20
print(summary)
print('instrument counts:', counter.snapshot())
