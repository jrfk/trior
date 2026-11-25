# 第11段階: Rust移植候補のためのI/O基準測定

Trio 0.35.0 / CPython 3.12.14 / Linux x86_64。`spikes/io_path/bench.py`で新規プロセス7回ずつ、親のCPU affinityを子に継承し、Python版Trio本体のsocket経路を測定。Rust版はまだ実装していない。生データ: `io_baseline.json`。

| 負荷 | 仕事量 | CPU中央値 | wall中央値 | 1コア占有率中央値 | 遅延 |
|---|---:|---:|---:|---:|---:|
| ready_recv | 4000バイト・4000 recv、初めから受信可能 | 20.619 ms | 20.620 ms | 100.0% | — |
| blocked_pingpong | socketpairで4000往復・送受信16000回 | 87.485 ms | 87.487 ms | 100.0% | 往復p99 0.109 ms |
| idle_read | 0.25秒後に1バイト送信 | 1.408 ms | 251.684 ms | 0.56% | — |

CPythonのcProfile診断ではready_recv 0.064秒・約17.5万calls、blocked_pingpong 0.276秒・約65万calls。後者で`_socket.wrapper`累積0.136秒、`_nonblocking_helper`累積0.125秒、`_io_epoll.process_events`累積0.014秒、`_io_epoll._update_registrations`累積0.005秒、`epoll.poll`累積0.005秒。累積時間は呼出し関係で重複するため合算しない。cProfile自身の大きなオーバーヘッドがあるので非計測時の割合・Amdahl上限と同一視しない。コードは`src/trio/_socket.py`のwrapperと非ブロッキング・チェックポイント処理、`src/trio/_core/_io_epoll.py`の待機登録、イベント振分と再登録、`src/trio/_core/_run.py`の`context.run`とrescheduleが関係する。

判断: 今回のI/O経路ではepoll.pollもイベント振分も単独Rust化の第一候補とは言えない。socket操作、即時成功時のチェックポイント、待機登録と起床の境界が主な検討対象。stdlib socket自体は既にCなので、Rustから同じPython socketを呼ぶだけでは高速化を仮定できない。Trioのcancel・shield・KI・guest・instrumentを維持する必要がある。待機時の低いCPU占有率はこの短い試験の結果であり、実アプリの常駐CPU使用率とは異なる。

次は少数のソケットと同時に多数のfdがreadyになる負荷を分ける。実アプリに近い負荷でサンプリング計測を行い、socket経路が全CPU時間の有意な割合を占める場合のみ、小さなRust境界設計に進む。CPU/operation、idle占有率、p99を既存Python実装と同じ条件で比較する。
