# Trio 0.35.0 の recv をRustで試作

Linux x86_64、CPython 3.12.14、Rust 1.100.0、PyO3 0.30.1。Trioの既存チェックポイントを直接yieldするRust awaitableを、標準socketの最初の受信と結果保持に使った。受信前のキャンセル確認と、最初の受信がブロックした場合の待機と再試行には既存のTrioプリミティブを使う。Python対照はrecvだけを専用化し、汎用wrapperとasync context managerを省いた。Stage 13の汎用helper試作と対象範囲が異なる。

| 負荷 | 通常のTrio | Python専用版 | Rust試作 |
|---|---:|---:|---:|
| 即時受信32,000回のCPU時間 | 138.75 ms | 114.30 ms | 120.45 ms |
| 待機を含む4,000往復のCPU時間 | 80.55 ms | 75.12 ms | 76.37 ms |
| 待機を含む通信の往復p99 | 53.20 µs | 48.29 µs | 45.40 µs |
| 0.25秒の待機条件のCPU占有率 | 0.99% | 0.92% | 0.83% |

各条件11ラウンド。実行順はシャッフルし、各モードを同じCPUに固定した新規プロセスで測定。表は測定値の中央値。Rust版の即時受信は通常版よりペアの中央値で13.2%短く、Python専用版より5.9%長かった。Python専用版はRust版より全11ラウンドで短かった。待機を含む通信のp99は各プロセスの値の中央値。即時受信のp99と、実アプリや3.15での効果は未測定。待機中のCPU時間は小さく、ラウンドごとの差も大きい。

3実装の差分テスト15件とRust版でのTrio既存socketテスト4件が通過。例外処理を含むテスト範囲での比較であり、全スイートは未実施。今回の境界では受信だけ専用化する効果が大きい。ネイティブawaitableの生成・再開コストは次の計測候補で、現時点で個別に測っていない。

既存PoCの環境を構築した後、リポジトリのルートで以下を実行する。

```sh
. .venv/bin/activate
maturin develop --release --locked
python -m pytest -q spikes/io_path/test_recv_variants.py
python spikes/io_path/compare_recv.py
```
