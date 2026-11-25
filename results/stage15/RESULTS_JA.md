# 第15段階 独立Rustランタイムの最小PoC

従来の部分移植から構造を変え、Rustがタスク、ready queue、タイマーヒープ、キャンセルスコープ、nurseryの子タスク数と終了待ちを所有する。PythonコルーチンはCPythonのcontext.runとsend/throwで再開する。APIは実験用のtrio_rust_poc.runtimeに置き、同じアプリケーションをモジュールの差し替えで比較する。

## 結果

Linux x86_64 / CPython 3.12.14 / Trio 0.35.0 / Rust 1.100.0 / PyO3 0.30.1。新規プロセス7ペア、実行順シャッフル、同一CPU affinity。CPU時間の比は各ペアの比の中央値。

| 負荷 | Trio CPU時間中央値 | Rust CPU時間中央値 | CPU速度比 | p99タイマー遅延 Trio / Rust |
|---|---:|---:|---:|---:|
| 600タスク・60,000チェックポイント | 109.56 ms | 26.24 ms | 4.11x | — |
| 600タスク・10 ms周期20回 | 201.91 ms | 15.10 ms | 13.33x | 14.44 / 0.427 ms |
| 580待機＋20周期タスク・10 ms周期20回 | 16.67 ms | 2.67 ms | 6.17x | 1.35 / 0.138 ms |
| 600待機タスク・0.25秒後にキャンセル | 9.47 ms | 1.72 ms | 5.54x | — |

全負荷で7ペアともRust版のCPU時間が少なかった。混合負荷のCPU占有率中央値は7.98%から1.33%、600周期タスク負荷では93.32%から7.46%。占有率はプロセスCPU時間を壁時計時間で除した値（1コア=100%）。タイマー遅延は各周期タスクのperf_counterによる目標時刻から実際の起床までの遅れ。各プロセスのp99の中央値を報告した。タスクの起床開始時刻は各タスクで決める。

## 検証済み範囲

run、open_nursery、start_soon、sleep、sleep_forever、checkpoint、CancelScopeによるレベルキャンセル、固定shield、子例外のExceptionGroup、ContextVarの基本的な伝播を実装。両実装を同じAPIで比較する12件のテストが通過。前段階の受信比較15件も通過。

このPoCはTrioの基本的なスケジューリングの費用を比較するためのもの。I/O、Event、Lock、MemoryChannel、CancelScopeのdeadlineや動的shield更新、任意のClock、instrumentation、KeyboardInterrupt保護、guest mode、公開lowlevel API、nursery.start、完全な例外・キャンセルの意味論は未実装または未検証。実装は単一実行スレッドを想定する。タスク/スコープの管理領域はrunの間に単調に増えるため、長時間運転や参照循環、異常終了時のリソース解放の検証も必要。CPython 3.15、ARM64および実アプリでの性能も未検証。

したがって表は限定された機能を実装したPoCの実測であり、完全互換実装の性能予測ではない。次の優先事項はdeadlineと動的shield、タスクの再利用とライフサイクル管理、公開lowlevel APIの互換テスト、I/Oの統合。追加機能による性能変化を同じベンチで追跡する。

## 再現

既存プロジェクトのvenvを準備してルートから実行する。

```sh
. .venv/bin/activate
maturin develop --release --locked
python -m pytest -q spikes/runtime/test_runtime.py
python spikes/runtime/bench_runtime.py
```

実装はsrc/runtime.rsとpython/trio_rust_poc/runtime.py。測定生データはruntime_comparison.json。
