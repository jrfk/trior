# 第7段階：実行可能キューとTask状態の統合

対象はTrio 0.35.0の隔離fork。実測環境はまずCPython 3.12.14 / Linux x86_64。Python 3.15は実行環境を確保した時点で同じ手順を再実行する。

## 成功条件

- 公開Trio APIの振る舞いを変えず、既存のcoreテスト、guest mode、キャンセル、instrument、GCの検証を通す。
- 同じ仕事量で純Python版よりCPU時間を減らす。checkpoint_600、nursery_spawn、mixed_600の対応するペア試行を複数プロセスで比較する。改善が測定のばらつきより大きいことを確認する。
- mixed_600では周期・仕事量とp99遅延を維持したうえでCPU時間とCPU使用率を下げる。CPU使用率単体は合格条件にしない。
- 実負荷へ導入する前に、実アプリに近いタスク数・起床頻度で同じ比較をする。合成負荷のみの改善を一般化しない。

## 順番

1. Rustで所有するFIFOキューを隔離forkに導入し、Trioのbatch境界とguest tickを守る。順序・計数・GC・coreテストを確認する。この段階単体の速度向上は必須にしない。
2. RustキューにTaskの実行状態を接続する。再スケジュール時にPythonの`runq.append`とTask getter/setterを経由しない。Taskを取り出すまでPythonオブジェクトへの往復を減らす。
3. キューからTaskを取り出した後の再開・終了・待機をまとめ、instrument、`context.run`、例外・キャンセルの意味を保つ。
4. 上記の互換性が通った候補について、同じCPUに固定してCPU時間・wall時間・p99遅延・同一仕事量を計測。改善しない場合はプロファイルから原因を特定して次の一箇所を選ぶ。
5. 合格後に期限・I/O・キャンセルの状態管理を候補にし、Python 3.15と実負荷で再検証する。

現在の第6段階ではGC修正後のCPU速度比がcheckpoint 0.951、nursery 0.879、mixed 0.921（1超が改善）であり、この第7段階の効果は未検証。実装後もこの数値を更新結果として扱わない。

## 手順1の実測（2026-11-07）

Rustの`VecDeque`にPython Task参照を保持し、`reschedule_native`で直接追加、各周回では`take_batch`で全件取り出す。guest tick判定、FIFO、次周回へ追加されるTaskの区別を維持した。`TASK_SPIKE_QUEUE=1 TASK_SPIKE_BATCH=1`で隔離forkを作成。Trio core＋GCテストは277 passed、12 skipped、1 xfailed。

7ペアのCPU時間比（純Python/候補、1超が改善）はcheckpoint 0.956、nursery 0.831、mixed 0.990。mixedは0.941〜1.365とばらつきが大きく、改善とは判定できない。生データは`results/stage7/native_queue.json`。この段階で高速化の目標は未達。次はバッチのPython list化をなくし、Rust側のキューからTaskを直接取り出して状態処理とつなげる。

## 手順2の実測（2026-11-07）

通常実行時にキューをRust側で切り離し、Python listを作らずRustのbatch処理にTaskを渡す。`_ALLOW_DETERMINISTIC_SCHEDULING`のテスト経路では従来のsort/shuffle処理を維持。バッチ中に追加されたTaskは次の周回へ残す。`TASK_SPIKE_QUEUE=1 TASK_SPIKE_BATCH=1 TASK_SPIKE_DIRECT_QUEUE=1`で作成した隔離forkでcore＋GCテスト277 passed、12 skipped、1 xfailed。

7ペアのCPU速度比はcheckpoint 0.926、nursery 0.873、mixed 0.950（`results/stage7/direct_queue.json`）。遅延p99を追加して別途7ペアで再測定するとcheckpoint 0.941、nursery 0.839、mixed 0.923（`results/stage7/direct_queue_with_latency.json`）。mixedのp99中央値はタイマー遅れでPython 1.339ms、候補1.389ms、checkpoint待ちでPython 0.324ms、候補0.338ms。共有ホスト上の短い合成試行であり、差を実環境へ一般化できない。CPU時間の改善は確認できず、手順3ではRustループ内のPythonオブジェクト操作と`context.run`の割合を計測し、対象を絞る。

## 手順3の診断

Rust側の `probe` feature を別ビルドとして追加し、checkpoint・nursery・mixedを5回ずつ区間計測した。結果と解釈は `results/stage7/PROFILE_JA.md`。checkpointではshield再スケジュールが診断時の総CPUの約29%を占めたが、mixedでは約2%。次はshield経路に残るPython操作を最小単位で比較し、mixedのCPU効率は実負荷で起床とコルーチン処理を確認して判断する。

## 手順4の最初の候補

キュー空判定をRustの`VecDeque::is_empty`へ切り替える実験を行った。7ペアではcheckpoint 0.965、nursery 0.996、mixed 1.045（既存Rust版/候補版のCPU時間比、1超が改善）。改善の証拠がないため既定では有効化しない。詳細は`results/stage7/EMPTY_CHECK_JA.md`。次は実負荷に近い起床頻度とCPU使用率を確認し、境界をまとめる対象を再選択する。

## 活動率を変えたCPU・遅延の結果

600タスク中20、100、599タスクを動かし、CPU時間・占有率・タイマー遅延p99を同一条件で比較。少数活動の20・100ではRust版のCPU消費が増加、599では両者が飽和しp99が約0.5秒に達した。詳細は`results/stage7/ACTIVITY_MATRIX_JA.md`。この構造の拡張は実アプリのプロファイルを得るまで保留し、Rust側でまとめて処理できる別のホットパスを探す。
