# Stage 20 — epoll / kqueue

Linux x86_64 / CPython 3.12.14 / Trio 0.35.0 / Rust 1.100.0 / PyO3 0.30.1.
Linux は epoll、macOS は kqueue を既定の readiness backend とする。
TRIOR_REACTOR=poll で Stage19 の比較用実装を選べる。

## 実装

- OS側の監視登録を保持し、ready event だけを取り出す。
- 方向別 waiter、登録単位の単調増加 token による古いイベントの無効化。
- close/cancellation で監視解除、RAII による reactor fd 解放。
- タイマーとスケジューラーの統合は Stage19 のまま、GILを解放して待つ。
- epoll は 256 件ずつ取得し、level-triggered。kqueue では read/write filter を使用。

## スパースI/O

固定回数: 多数のソケットペアを作り、うち1ペアだけ3000回 readiness 待機・受信。
残りは待機したまま最後にキャンセル。10msの開始待機とセットアップ・後処理を含む。
5回の中央値、別プロセス。CPU時間はプロセス全体。

| ペア数 | Trio wall ms | poll wall ms | epoll wall ms | Trio CPU ms | poll CPU ms | epoll CPU ms |
|---:|---:|---:|---:|---:|---:|---:|
| 64 | 32.31 | 23.67 | 22.83 | 22.21 | 13.76 | 12.75 |
| 600 | 45.76 | 98.45 | 25.50 | 37.66 | 88.11 | 16.18 |
| 2000 | 79.44 | 318.98 | 44.24 | 78.88 | 307.80 | 38.50 |

600ペアで Trio 比 wall 1.79倍、CPU時間57.0%削減。
poll 比 wall 3.86倍、CPU時間81.6%削減。
2000ペアで Trio 比 wall 1.80倍、CPU時間51.2%削減。
poll 比 wall 7.21倍、CPU時間87.5%削減。

## デンスI/O

600ペアに30回ずつ、各ラウンド2ms sleepを含む (Stage19と同じベンチ)。

| backend | wall ms | CPU ms | CPU/ wall |
|---|---:|---:|---:|
| Trio | 115.73 | 115.54 | 99.8% |
| Trior poll | 85.75 | 53.48 | 62.4% |
| Trior epoll | 98.91 | 73.32 | 74.1% |

epoll は Trio 比 wall 1.17倍、CPU時間36.5%削減だが、pollよりCPU時間37.1%増加。
高密度では readiness ごとの epoll_ctl ADD/DEL のコストがあると考えられる。
原因の確定には syscall profiling が必要。次は登録の再利用を検討する。
固定仕事量の短時間マイクロベンチであり、実際の600コルーチン環境のCPU使用率を保証しない。

## 検証

- Linux epoll / poll ともに63テスト成功（既存57 + 追加6）。
- macOS ARM64: PyO3 cross-target cargo check 成功。実機でのリンク、実行、測定は未実施。
- Python 3.15未検証。Windows未対応。notify_closingなしの外部close、別スレッド操作、FD複製、シグナルと異常時の終了処理は未検証。
- 次: TCP connect、SocketStream、open_tcp_stream と、epoll_ctl削減の検証。
