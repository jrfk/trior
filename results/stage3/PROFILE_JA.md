# 第3段階：CPU占有率とRustループの区間計測

2026-11-07。CPython 3.12.14、Trio 0.35.0、PyO3 0.30.1、Linux x86_64。第2段階の通常ビルドに基づくCPU使用率は `cpu_utilization.md` にまとめた。全試行を許可された同一CPUに固定し、プロセスCPU時間÷壁時計時間を1コア=100%として計算した。マシン全体の使用率や実機使用率ではない。

- CPU主体の8負荷：Python、元Rust、rust-optとも約100%。同じ仕事の完了時間と総CPU消費量の違いを `../stage2/normal.json` で比較する。
- 600タスクの混合負荷：Python 9.9%、元Rust 12.4%、rust-opt 10.8%（各7回の中央値）。対応するCPU時間中央値は40.7、51.2、44.3 ms。約0.41秒の試行中に占有した1コアの平均割合であり、常駐時の値ではない。
- cgroupのCPU quotaは8コア相当だが、ベンチマークは1コアに固定しており、ホスト全体のCPU%に換算しない。

## 診断用の別ビルド

`notes/lib_probe.rs` は `rust-opt` 内に `Instant` による区間計測を追加した診断用ソース。`benchmarks/native_probe.py` で5回測った中央値は以下。元の `src/lib.rs` は計時処理を含まない通常版へ戻してある。

| 負荷 | Rustループ内の総時間 | Task準備 | context.runとアプリ処理 | yield処理・再スケジュール | Task終了処理 |
|---|---:|---:|---:|---:|---:|
| checkpoint_600 | 134.3 ms | 17.3 ms (13%) | 63.1 ms (47%) | 43.2 ms (32%) | 10.8 ms (8%) |
| mixed_600 | 39.5 ms | 1.8 ms (5%) | 31.6 ms (80%) | 5.1 ms (13%) | 1.0 ms (3%) |

ここは壁時計による区間内訳であり、nativeの命令別CPUプロファイルではない。`context.run` はPythonコルーチン、アプリの仕事、チェックポイント処理を含む。yield処理はPython側の `runner.reschedule()` 等を含む。区間の計時処理自体が速度に影響するため、上表の絶対時間や割合を通常ビルドのベンチマークに混ぜない。生データは `native_probe.json`。

計時入りビルドでも同じ仕事量で3負荷×7回の追加測定を行い、`rust-opt` のPython比高速化倍率（大きいほど速い）は checkpoint_600: 0.852倍、channel_0: 0.880倍、mixed_600: 0.958倍。短い共用ホスト測定であり、計時なし版との細かな差を原因と結びつけない。`normal.json` に原データを残した。

## 次に試す最小構造

1. まず `CancelShieldedCheckpoint` の頻出経路で `runner.reschedule()` が占める時間を個別に計測する。yield処理32%は上限であり、全量が高速化可能とは限らない。
2. 高頻度の再スケジュール経路と次回送信の状態更新を同じ所有者に置く案を設計する。ready queueだけRustへ移しても、Pythonの `Runner.reschedule` からRustへの呼び出しが増えるため、単独の高速化は仮定しない。
3. 公開 `trio.lowlevel.reschedule` と `current_task` の振る舞い、同一batch中に再スケジュールされたTaskは次のbatchへ回す順序、instrumentのフックと動的登録、キャンセルとshield、guest modeのタイミングを保つ。Pythonから見えるTask参照と例外伝播を維持して小さく置き換える。
4. 互換テストと上流対象テストを通し、CPU消費量、混合負荷の占有率、p99レイテンシを同じpaired条件で測る。これでPythonより有意に良くならなければ、この狭い移植方針は止める。

この結果は、Trio全体をRust化したときの速度を予測するものではない。Linuxのnative sampling profiler（perf等）はこの環境で利用可能な実行ファイルがなく、PyO3呼び出しの命令別内訳は未測定。
