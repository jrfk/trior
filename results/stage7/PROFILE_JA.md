# 第7段階：キュー直結版の区間診断

Trio 0.35.0 / CPython 3.12.14 / Linux x86_64。`spikes/native_task_state` の `probe` feature 付き別ビルドで5回繰り返した中央値。実行可能キューとTask状態はRust実装、決定的スケジューリングのテスト時のみPythonのlistを使う。通常ビルドの性能値と混ぜない。生データは `direct_queue_probe.json`。

| 負荷 | 総CPU時間 | Task準備 | `context.run`（コルーチンと内部処理を含む） | yield処理 | 後始末 | shield再スケジュール（yield処理の内数） |
|---|---:|---:|---:|---:|---:|---:|
| checkpoint_600 | 125.4 ms | 10.7 ms | 56.0 ms | 43.0 ms | 8.6 ms | 35.9 ms / 60,001回 |
| nursery_spawn | 81.8 ms | 3.4 ms | 49.3 ms | 21.8 ms | 3.2 ms | 5.5 ms / 10,001回 |
| mixed_600 | 59.1 ms | 1.0 ms | 28.0 ms | 4.2 ms | 0.8 ms | 1.1 ms / 1,201回 |

区間は `Instant` の経過時間の合計であり、CPU命令の帰属ではない。診断処理の計時・集計自体が速度を変える。区間合計と総CPU時間の差にはbatch外のTrio処理、起床や計時の費用などが含まれる。`context.run` はアプリケーション側の計算だけでなく、Pythonのチェックポイント処理も含む。

checkpoint負荷ではshield再スケジュールが診断時CPU時間の約29%を占める。第4段階ではこの経路を単純にRustへ展開しても改善しなかった。今回はRustキューへの追加まで一体化しているが、`coro.send`の取得、`Value(None)`生成、guest判定、instrument判定などPython操作が毎回残る。次の候補はこの経路のPython操作を分類し、同じ公開動作のもとで再利用または省略できるものを一箇所ずつ実験する。mixed負荷ではshield再スケジュールは総CPUの約2%であり、普段のCPU効率を改善するには起床と`context.run`側の実負荷プロファイルが必要。

計測後は `probe` feature なしの通常ビルドへ戻し、core＋GCテスト277 passed、12 skipped、1 xfailedを再確認した。Python 3.15、実アプリ、他OSの性能は未測定。
