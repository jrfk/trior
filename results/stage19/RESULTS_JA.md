# Stage 19 — Rust I/O Reactor

Linux x86_64 / CPython 3.12.14 / Trio 0.35.0 / Rust 1.100.0 / PyO3 0.30.1.
独立 Rust ランタイムの初期実装。Trio 本体には変更なし。

## 実装

- Rust が fd ごとに read/write waiter を保持。Unix poll の level-triggered readiness。
- 実行可能タスクがない場合、次のタイマー期限まで GIL を解放してブロック。
- ready queue が連続していても最大64 task step ごとに非ブロッキング poll。
- キャンセル時登録解除、同方向の重複待機を拒否、notify_closing による待機解除。
- trior.lowlevel.wait_readable / wait_writable / notify_closing。
- trior.socket.socket / socketpair / from_stdlib_socket、recv / recv_into / send / accept。
- Python の socket オブジェクトと coroutine 実行は CPython 上。

## 計測

各ペアに1 byteを30回配送、各ラウンド送信前に2ms sleep、5回の中央値。
socketpair 作成・破棄と run 全体を含む。CPU% = process CPU time / wall time × 100。
各バックエンドは別プロセス。詳細は io.jsonl。

| pair数 | Trio wall ms | Trior wall ms | Trio CPU ms | Trior CPU ms | CPU削減 |
|---:|---:|---:|---:|---:|---:|
| 1 | 66.27 | 63.98 | 4.09 | 1.87 | 54.4% |
| 64 | 79.09 | 69.53 | 17.18 | 7.55 | 56.1% |
| 600 | 126.66 | 95.57 | 126.63 | 68.59 | 45.8% |

600ペアでは wall 1.33倍、CPU時間1.85倍効率化。
CPU使用率は99.98%から71.76%（1コア相当）。
この測定は同じ固定回数のワークロードであって、厳密な一定送信レートではない。
Triorの600ペア測定にばらつきがある。実運用CPU使用率への一般化は不可。

## テスト

57 passed（既存45 + Trio/Trior比較12）。
readiness、deadline cancellation と再登録、close、重複待機、
socketpair 転送、ready-load 下のI/O、同一ソケット別方向待機。

## 制限と次段階

poll は待機fd数に比例してスキャンする。多数のidle fdに少数のイベントが届く
ワークロードでは epoll (Linux) / kqueue (macOS) を比較すべき。
2ms sleep を含むためこの結果だけから純粋な reactor throughput は測定できない。
外部からの close/FD再利用、別スレッド wakeup、シグナル、Windows、
async DNS、connect、SocketStream、完全な Trio socket 互換性は未検証・未実装。
CPython 3.15も未検証。
