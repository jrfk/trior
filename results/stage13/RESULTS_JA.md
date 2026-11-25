# Stage 13 受信処理のCPU時間を切り分ける

Trio 0.35.0、CPython 3.12.14、Linux x86_64。各測定でsocketpairに4000バイトずつ事前投入し、1バイトの受信を計32000回行った。単一CPUに固定した新規プロセスで各7回測定し、各ラウンドで実行順を入れ替えた。計測には投入と結果確認も含む。

| 受信経路 | CPU時間中央値 |
|---|---:|
| 標準socketのみ | 7.3 ms |
| 標準socketとTrioのキャンセル確認・チェックポイント | 111.1 ms |
| 通常のTrio socket | 145.6 ms |
| Trioの非ブロッキング処理からasync context managerを外した試作 | 130.4 ms |

標準socketのみの条件にはキャンセル確認とスケジューリングがない。チェックポイント付き条件は受信が即時成功する経路の対照であり、全入力でのAPI互換を検証するものではない。試作はキャンセル確認、成功時と例外時のshielded checkpoint、待機後の再試行を残した。通常版に対し7ラウンドすべてでCPU時間が短く、ペア削減率の中央値は約10%。既存socketテスト4件（non_blocking_paths、send_recv_variants、socketpair_simple、interrupted_by_close）が通過。全スイート、混合負荷、実アプリ、CPython 3.15は未計測。
