# 第6段階：Rust製Task状態を持つ隔離Trio fork

対象はTrio 0.35.0 / CPython 3.12.14 / PyO3 0.30.1 / Linux x86_64。この環境には3.15の実行ファイルがなく、`uv python install 3.15` は releases.astral.sh の取得に失敗し、GitHub fallbackも使用できなかった。これは3.15をTrioやPyO3がサポートしないという意味ではない。今回の実測は全て3.12。

`spikes/native_task_state` に独立したPyO3拡張を実装。インストール済みTrio 0.35のハッシュを照合し、隔離コピーへTask基底型の変更を適用する。元のTrioパッケージや本体PoCは変更しない。Pythonから見えるTaskと `attrs` の既存フィールドを残し、`_next_send_fn`, `_next_send`, `_abort_func`, `custom_sleep_data` をRust側の拡張型に置いた。次に `Runner.reschedule` をRustへ、最後にbatchループからTask状態への直接アクセスを加えた。ready queueはPythonのdequeのまま。

| 方式 | checkpoint_600 | nursery_spawn | mixed_600 |
|---|---:|---:|---:|
| Rust製Task属性のみ | 0.904倍 | 0.891倍 | 0.982倍 |
| 加えて再スケジュールもRust | 0.817倍 | 0.848倍 | 0.910倍 |
| 加えてRust batchから状態を直接参照 | 0.968倍 | 0.897倍 | 0.922倍 |
| GC修正後に直接参照版を再測定 | 0.951倍 | 0.879倍 | 0.921倍 |

値は各負荷7回の新規プロセスによるペアCPU時間比の中央値（Python CPU時間 / 候補CPU時間）。1より大きいほどRust版が速い。仕事量は方式間で一致を検証し、同一CPUへ固定した。共用ホストでの短い試行なので、0.968と0.951の差のような小差を解釈しない。修正後の混合負荷のCPU使用率中央値はPython 14.9%、候補16.4%（1コア=100%）。合成負荷であり実アプリではない。生データは `spikes/native_task_state/field-only-benchmark.json`, `fused-benchmark.json`, `native-batch-benchmark.json` と `results/stage6/native_batch_gc.json`。

PyO3のTask状態がTask自身への参照を持つと、当初は `gc.collect()` 後もTaskが残ることを確認した。`__traverse__` と `__clear__` を追加し、`test_gc_cycle.py` の自己循環が回収されることを確認。修正後の隔離forkでTrio coreテストは277 passed、12 skipped、1 xfailed。対象のrun/KI/instrumentation/guest modeは修正前195 passed、2 skipped、1 xfailedで、修正後はcoreに含まれる部分を再確認した。

広いTrio上流suiteは、依存パッケージ不足（yaml等）によるcollection失敗、ネットワーク等の環境制限と追加の失敗があり、全件通過は確認できていない。別OS、3.15、実負荷についても未検証。

判断：Python側から見えるTask属性をPyO3のgetter/setterに置き換えるだけではコストが増える。batchと再スケジュールもRust側で扱うとcheckpointでは回復したが、元のPython版を超えなかった。ready queueまでの移植は広範な互換性と保守費用を伴うため、現時点の合成負荷結果だけで進めない。実負荷のCPUプロファイルでschedulerが主要な費用と示された場合に改めて判断する。
