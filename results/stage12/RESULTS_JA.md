# 第12段階: 多数のfdが同時にreadyになる負荷

Trio 0.35.0 / CPython 3.12.14 / Linux x86_64。`spikes/io_path/dense.py`で1、64、256個のsocketpairの読み手を待機させ、書き手から同期的にまとめて送信した。各条件で4096イベント。新規プロセス7回、CPU affinity固定、`process_time_ns`。`trio.testing.wait_all_tasks_blocked()`を各wave前に呼んで全readersの待機を保証するため、その費用もCPU時間に含む。生データは`dense_io.json`。

| 同時ready fd | wave数 | CPU時間中央値 | CPU/イベント中央値 | wave完了p99中央値 |
|---:|---:|---:|---:|---:|
| 1 | 4096 | 90.08 ms | 21.99 µs | 0.076 ms |
| 64 | 64 | 35.33 ms | 8.63 µs | 0.728 ms |
| 256 | 16 | 40.78 ms | 9.96 µs | 2.494 ms |

p99は各wave内の送信開始から全readersの処理完了までで、1イベントの遅延ではない。特に256 fdは16 waveしかなく、p99の推定精度は低い。各条件の処理形態とwave数が異なり、1対64のCPU/イベント比をRust化による高速化可能幅と解釈しない。

別途1回ずつcProfileで診断。256 fdでは `_socket._nonblocking_helper`自己時間約9 ms、`_io_epoll._epoll_wait`約9 ms、`_run.unrolled_run`約7 ms、`_io_epoll.process_events`約2 ms、`_io_epoll._update_registrations`約2 ms、`epoll.modify`約2 ms（計測負荷込みで全体約95 ms）。累積時間にはネストした処理が含まれ、cProfileのオーバーヘッドもある。測定時の自己時間を非計測時の正確なCPU配分とみなさない。

判断: 256 fdが同時readyになる負荷でも`process_events`単独は支配的ではなく、Rust製epollイベント振り分けだけを実装する根拠は弱い。Trioは既にC実装の`epoll.poll`とstdlib socket syscallを利用する。Rust化の狙いはTrioがその前後で行う非ブロッキング・checkpoint・待機登録・起床のPython処理をまとめて減らすことだが、Task状態・キュー・batch直結の既存試作はPython版を超えていない。次のネイティブ試作は、実アプリでsocket経路がCPUの主要因と示され、Python API/低レベルAPIの互換境界と呼出し削減量が定義できた場合に着手する。現在の合成試験だけでは広範なRust移植を推奨しない。
