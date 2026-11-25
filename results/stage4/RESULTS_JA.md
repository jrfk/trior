# 第4段階：再スケジュール経路の計測と小さなRust実装

2026-11-07。Trio 0.35.0 / CPython 3.12.14 / PyO3 0.30.1 / Linux x86_64。各方式は新規プロセス、同一CPU固定、同じ仕事量、ウォームアップあり。生データは `normal.json`（9負荷×7回×3方式）と `focused.json`（3負荷×11回×3方式、CPU負荷の校正目標0.5秒）。各ラウンドで方式の順序をランダム化し、仕事量カウンタの一致を確認した。

## 何を測ったか

計時を挿入した診断用Rustビルドで、`CancelShieldedCheckpoint` から呼ぶPythonの `Runner.reschedule()` に要する時間を計測した。`checkpoint_600` は1試行約60,001回、呼び出し区間47.2 ms（yield処理区間の82%、同試行のCPU時間に対して約27%に相当）。`mixed_600` は約1,201回、1.7 ms（yield処理区間の27%、CPU時間に対して約2.5%に相当）。5回の中央値。診断用の壁時計による区間計測で、native命令別プロファイルでも通常ビルドのCPU時間でもない。`native_probe.json` に生データを保存。

次に `rust-fast` を作り、batch内の通常チェックポイントでだけ `Runner.reschedule()` の処理をRust側へ展開した。Task状態の設定、guest modeの起床、runqへのappend、`task_scheduled` instrumentの順序を元実装に合わせた。外部から呼ぶ `trio.lowlevel.reschedule` はPythonのまま。`rust-opt` は従来のPyO3属性名キャッシュ版を比較対象として保持。

## 測定結果

最初の9負荷×7回では、`rust-fast / rust-opt` のCPU高速化比の中央値が checkpoint_600で1.074倍、nursery_spawnで1.092倍、mixed_600で1.034倍だった。ただし同じペアの比に大きなばらつき（checkpoint_600は0.922〜1.842倍）があり、方向を確定できない。他の負荷では改善は見えなかった。

重点3負荷を11回で再測定した結果は次のとおり。高速化比は同一ラウンドの `rust-opt CPU時間 / rust-fast CPU時間` の中央値。1を超えたときだけfastが速い。

| 負荷 | Python CPU中央値 | rust-opt CPU中央値 | rust-fast CPU中央値 | fast / opt高速化比 | fast / Python高速化比 |
|---|---:|---:|---:|---:|---:|
| checkpoint_600 | 448.1 ms | 490.3 ms | 542.8 ms | 0.923倍 | 0.806倍 |
| nursery_spawn | 530.9 ms | 555.0 ms | 590.7 ms | 0.938倍 | 0.904倍 |
| mixed_600 | 56.6 ms | 61.4 ms | 59.6 ms | 1.032倍 | 0.925倍 |

`mixed_600` のCPU使用率中央値（1コア=100%、プロセスCPU時間÷壁時計時間）はPython 13.7%、rust-opt 14.9%、rust-fast 14.3%。これは約0.4秒の合成試験の平均であり、実機の常駐CPU使用率ではない。混合負荷のfast/opt比は0.850〜1.264倍で、3%程度の差から改善とは判断しない。初回と追加試験の差が大きいため、共用ホストの測定を一般化しない。

基本互換テストはPython、rust-opt、rust-fastとも17件通過。新しいテストは、チェックポイントの再スケジュールをinstrumentが観測した時点でTaskがrunqに入り、次回送信状態が正しく設定されていることを確認する。対象のTrio上流テストはrust-fastで195 passed、2 skipped、1 xfailed。全suiteや異なるOS・Python環境は未検証。

## 判断と次の設計

`Runner.reschedule()` をそのままRustへ展開する案は採用しない。呼び出し自体はcheckpoint集約負荷の費用を占めるものの、RustからPython属性の読み書きやメソッド呼び出しを逐次行う構造が残り、重点試験ではCPU時間が増えた。混合負荷でこの経路が占める割合も小さい。

次に高速化を狙うならTaskの `_next_send_fn`, `_next_send`, `_abort_func` とready queueの更新を一緒に設計する必要がある。ただしPythonからTask属性が観測・変更され、キャンセルとinstrumentが再入するため、Rust-owned状態だけを追加しても同期コストが増える。先に公開lowlevel API、guest mode、instrumentの動的登録と例外、キャンセル・shield、batch境界の公平性を維持する境界を設計し、最小試作で同じpaired試験を行う。現段階では「Trio APIを維持して裏側をRustへ移せば高速化する」という仮説は実証されていない。

実験用 `rust-fast` は研究用にコードに残した。Python実装の `Runner.reschedule` を動的に差し替える利用では、それを経由しないなど未検証の互換性リスクがある。実運用の候補は引き続き通常のTrio。
