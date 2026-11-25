# Trio Rust化・第1段階の検証結果

2026-11-07 JST。CPython 3.12.14、Trio 0.35.0、Rust 1.99.1、PyO3 0.30.1、Linux x86_64。

今回の移植では高速化できなかった。Python側のTask状態を保持したまま、実行可能タスクを再開するbatchループだけをRustへ移した実験であり、Rustで状態まで持つscheduler全体の評価ではない。

3種類を比較：無変更Python、同じループを関数へ切り出したPython、Rust版。各負荷7回、毎回新しいプロセス、CPU固定、ウォームアップあり、同一仕事量、実行順をランダム化。ビルドはrelease。全189回の生データはresults/normal.json。

| 負荷 | Rust版のCPU時間倍率（通常版=1） |
|---|---:|
| checkpoint_1 | 1.63倍 |
| checkpoint_600 | 1.68倍 |
| checkpoint_deep | 1.24倍 |
| channel_0 | 1.57倍 |
| channel_64 | 1.53倍 |
| nursery_spawn | 1.33倍 |
| deadline_churn | 1.02倍 |
| cancel_fanout | 1.19倍 |
| mixed_600 | 1.24倍 |

倍率は各ペアの時間比の中央値から計算。大きいほど遅い。Python関数切り出し版はおおむね通常版と同程度。混合負荷は600タスクの合成データで、実機のワークロードではない。共用ホストなので小さな差やp99差の一般化は避ける。

基本互換テストは3種類とも16件通過。上流test_run/test_ki/test_instrumentation/test_guest_modeは3種類とも195 passed、2 skipped、1 xfailed。全上流suiteや全OSの互換性を保証する結果ではない。ログはresults/tests-*とresults/upstream-*。

原因候補は、Rust側からPython属性・メソッドへ頻繁にアクセスするコスト。PythonからRustへのバッチ単位の呼び出しだけでなく、RustからPythonオブジェクトを操作する経路が大量に残る。これは実装構造からの推測で、native profileによる内訳の測定は未実施。

次の実験案：Taskの内部状態とready queueをRustへまとめて移し、Python API呼び出しを減らす。最初に今回の経路をprofileして主な費用を特定する。単純移植のまま移植範囲を広げる方針は採らない。実機・旧Python環境への適用は未検証。

再現方法はREADME.md、測定定義はbenchmarks/README.md。現在の成果は検証用PoCであり、本番用Trio置換ではない。

## 第2段階：RustからPythonへ渡す属性名のキャッシュ

同じPython-owned Taskと同じbatchループを維持し、PyO3から渡す属性・メソッド名だけを `intern!` に変更した `rust-opt` を追加した。元のRust版は比較用に保持。第1段階と同じ9ケースを、Python・Rust・rust-optの3方式で各7回、新規プロセスとCPU固定で再測定した（189回）。同一ラウンドで各方式の仕事量カウンタが一致することを確認した。生データ、試行順、校正値、ハッシュは `results/stage2/normal.json`。

| 負荷 | Python CPU中央値 | 元Rust CPU中央値 | rust-opt CPU中央値 | rust-opt / 元Rust 高速化 | rust-opt / Python 高速化 |
|---|---:|---:|---:|---:|---:|
| checkpoint_1 | 180.0 ms | 330.3 ms | 225.5 ms | 1.48倍 | 0.80倍 |
| checkpoint_600 | 187.0 ms | 327.3 ms | 208.4 ms | 1.56倍 | 0.90倍 |
| checkpoint_deep | 203.0 ms | 256.4 ms | 214.6 ms | 1.21倍 | 0.95倍 |
| channel_0 | 206.5 ms | 344.8 ms | 236.8 ms | 1.45倍 | 0.88倍 |
| channel_64 | 211.3 ms | 363.9 ms | 244.7 ms | 1.49倍 | 0.88倍 |
| nursery_spawn | 216.8 ms | 298.1 ms | 228.4 ms | 1.32倍 | 0.95倍 |
| deadline_churn | 209.0 ms | 222.8 ms | 213.7 ms | 1.04倍 | 0.97倍 |
| cancel_fanout | 219.3 ms | 265.8 ms | 224.0 ms | 1.19倍 | 0.97倍 |
| mixed_600 | 40.7 ms | 51.2 ms | 44.3 ms | 1.17倍 | 0.93倍 |

「高速化」は同一ラウンドのCPU時間比の中央値であり、表のCPU中央値を割った値とは多少異なる。`mixed_600` はスリープを含むためCPU時間で比較した。いずれも合成負荷かつ共用ホストでの観測であり、特に小さな差は確証ではない。

`rust-opt` は全ケースで元Rust版より短時間だったが、Python版に対しては全ケースで遅かった。属性名生成がこのPoCの大きな費用だったことを示唆する。ただし `intern!` は属性参照・Pythonメソッド呼び出し自体を消さないため、この結果だけで全費用の内訳は特定できない。

追加の互換テストは `rust-opt` で16 passed。Trio上流の `test_run.py`, `test_ki.py`, `test_instrumentation.py`, `test_guest_mode.py` は195 passed、2 skipped、1 xfailed（`results/stage2/upstream-rust-opt.txt`）。全suite、別Pythonバージョン、別OS、実機については引き続き未検証。

次はPythonとの境界を減らす設計に進む前に、CPython/PyO3境界のnative profileと、Task/ready queueをRust側へ移す最小設計を検討する。現在のPoCはTrio APIを維持した内部差し替えの実験であり、配布用の代替実装ではない。

## 第3段階：CPU使用率と区間計測

CPU主体の負荷は3方式とも1コアを約100%使用。600タスク（580待機・20周期処理）の合成混合負荷では、同一プロセスのCPU時間÷壁時計時間でPython 9.9%、元Rust 12.4%、rust-opt 10.8%（1コア=100%、各7回の中央値）。対応するCPU時間は40.7、51.2、44.3 ms。診断用別ビルドのRustループ区間計測と次の移植設計は `results/stage3/PROFILE_JA.md`。実機の常時600コルーチンでのCPU使用率を示す値ではない。

## 第4段階：再スケジュール経路の検討

診断用ビルドで `runner.reschedule()` がcheckpoint集約負荷のCPU区間の大きな部分を占めると分かったため、処理をRustへ展開した `rust-fast` を試作した。しかし重点11回の比較では `checkpoint_600` と `nursery_spawn` で従来の `rust-opt` より遅く、混合負荷での差はばらつきの範囲だった。結論、CPU使用率、互換性リスク、次の設計条件は `results/stage4/RESULTS_JA.md` を参照。

## 第6段階：Rust製Task状態を持つ隔離fork

Trio 0.35 / Python 3.12でRust製Task状態、Rust再スケジュール、Rust batchの直接アクセスを順に検証した。対象上流テストとTrio coreテストは通過し、自己循環参照のGC漏れも修正した。7回の合成負荷比較では最終候補のPython比CPU高速化比はcheckpoint_600が0.95倍、混合600タスクが0.92倍で、まだ高速化していない。詳細は `results/stage6/RESULTS_JA.md`。

## 第5段階：Trio 0.35 / Python 3.15 の実負荷計測準備

実アプリにフックを入れずにLinuxの対象PIDからCPU使用率・RSS・スレッド数を記録する計測器を追加。計測器の合成負荷smokeは通過。Trio 0.35とPyO3 0.30.1の3.15対応は公式資料で確認したが、この環境にPython 3.15を取得できず、3.15上のPoC動作と実負荷は未検証。実行手順と次の判断条件は `results/stage5/README_JA.md`。
