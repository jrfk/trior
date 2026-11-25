"""Summarize observed single-core process CPU occupancy from benchmark JSON."""
import json
import statistics
import sys
from pathlib import Path

source = Path(sys.argv[1])
result = json.loads(source.read_text())
assert result['status'] == 'complete'
lines = [
    '# CPU使用率（第2段階の通常ビルド）', '',
    'CPU使用率は同じ試行の `process_time_ns / perf_counter_ns × 100` の中央値。',
    '1コア=100%。全モード同一CPUに固定した測定で、ホスト全体のCPU使用率ではない。',
    '計算主体の負荷は仕事量固定のため処理時間が異なり、ほぼ1コアを使い切る。', '',
    '| 負荷 | Python | 元Rust | rust-opt |', '|---|---:|---:|---:|',
]
for case in result['metadata']['cases']:
    values=[]
    for mode in ('python', 'rust', 'rust-opt'):
        rows=[x for x in result['raw_runs'] if x['workload']==case and x['mode']==mode]
        values.append(f"{statistics.median(100*x['cpu_ns']/x['wall_ns'] for x in rows):.1f}%")
    lines.append(f"| {case} | {' | '.join(values)} |")
lines += [
    '', '混合負荷 `mixed_600` は各試行約0.41秒の待機を含む。',
    '実際に消費したCPU時間の中央値はPython 40.7 ms、元Rust 51.2 ms、rust-opt 44.3 ms。',
    'このCPU使用率は、同じ仕事を実行したときの実行区間内の平均であり、電力や実機の使用率ではない。',
    '7回の短い合成試行、共用ホストでの測定。実際の常駐600タスクでのCPU占有率は測っていない。',
]
output=Path(sys.argv[2]); output.write_text('\n'.join(lines)+'\n')
