# 第5段階：Trio 0.35 / Python 3.15 の実負荷CPU計測準備

対象をTrio 0.35、標準のGIL付きCPython 3.15とする。Trio 0.35のリリースノートは3.15対応を明記し、PyO3 0.30.1のchangelogにも3.15 final対応がある。既存のRust PoC本体はまだCPython 3.12専用のバージョンガードとパッケージ設定を持つ。今回の計測器はアプリから独立して動き、3.15のTrioプロセスを対象にできるが、この作業環境では3.15を取得できず、3.15での動作やRust拡張のwheelは未検証。

## まず外から測る（Linux）

`benchmarks/sample_pid_cpu.py` は対象アプリのコード変更と追加パッケージを必要としない。**対象と同じPID名前空間**で実行し、正しいPIDを指定する。1秒おきに `/proc/PID/stat` からユーザー＋システムCPU時間、RSS、スレッド数をJSONLへ記録する。CPU使用率は1コアを100%とし、複数スレッドで100%を超え得る。子プロセスのCPUは含まない。Docker等ではホストPIDとコンテナ内PIDを取り違えない。

```sh
python benchmarks/sample_pid_cpu.py <PID> --interval 1 --duration 300 --output results/real-baseline.jsonl
python benchmarks/sample_pid_cpu.py --summary results/real-baseline.jsonl --skip-first 30
```

通常の仕事量で5分、同じ操作と条件で少なくとも3回採る。起動直後を除外する `--skip-first 30` は必要に応じて変える。アプリの1秒あたり処理件数や入力負荷も別途記録し、CPU%だけの比較を避ける。アイドル時とピーク時を分けて採る。機密データやタスク名はこの計測器には記録しない。

## 任意の診断実行

`benchmarks/production_cpu_probe.py` はアプリ内で `trio.run` を囲む計測器。Linux以外の環境でもプロセスCPU時間を採れる。通常の実負荷計測は外部PID方式を優先する。

```python
from production_cpu_probe import ProcessCpuSampler

with ProcessCpuSampler('cpu.jsonl', interval=1.0):
    trio.run(main)
```

同じファイルに `TrioStepCounter` を用意した。`trio.run(main, instruments=[counter])` に渡せば `task_steps`、`task_scheduled`、`io_waits` を数えられる。ただし各タスク実行にPythonコールバックを足すため、この診断実行のCPU%をフックなしベースラインと直接比較しない。ステップ数だけではCPU消費場所を特定できない。scheduler内部かアプリ処理かの判定には、同じ仕事量の別実行でPython profilerのcall treeを確認する。

## この環境での動作確認

Trio 0.35 / CPython 3.12.14で、内部計測器と任意フックを合成600タスク負荷でsmoke検証した。外部PID計測器は600タスク（580待機、20周期処理）を約2秒観測して4.0%／1コア、CPU連続実行プロセスを約1秒観測して100.0%／1コアとなった。これらは検出動作の確認であり、実負荷の性能値ではない。生データは `external-smoke.jsonl` と `cpu-smoke.jsonl`。

## 次のGo/No-Go

1. Python 3.15 / Trio 0.35 の実アプリで、まず無改造のまま外部PID計測を実施する。利用可能なら同条件のCPU profilerで、Trio scheduler自身の処理とアプリ側処理を分ける。
2. schedulerが主要なCPU消費先と確認できた場合だけ、`Task` の次回送信状態と `Runner.reschedule` を同一Rust拡張型へ移すforkを試す。Pythonから見えるTask属性、`custom_sleep_data`、instrumentの順序、guest mode、キャンセルと例外処理は保持する。ready queueの移植はその後に判断する。
3. forkを3.15でreleaseビルドし、対象上流テストと全suite、同一仕事量のpaired CPU時間、混合負荷のCPU使用率、p99遅延を比較する。単なる属性アクセスのRust化が遅かった前回の結果を踏まえ、値を同期するだけのRust sidecarは採用しない。

今回は実アプリのプロセスがこの環境にないため、実負荷測定とforkの性能判断は未実施。

公式資料: [Trio 0.35 release](https://github.com/python-trio/trio/releases/tag/v0.35.0)、[PyO3 0.30.1 changelog](https://pyo3.rs/v0.30.1/changelog)。
