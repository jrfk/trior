# Trio本体のcheckpoint経路を整理した実験

対象はTrio 0.35.0 / CPython 3.12.14 / Linux x86_64。インストール済みTrioのハッシュを照合して隔離コピーを作り、`CancelShieldedCheckpoint`から`Runner.reschedule`を呼ぶ処理を、同等の状態更新としてrun loop内に記述した。Python側での呼び出し回数を減らす仮説。元パッケージは変更しない。生成コードは`spikes/python_checkpoint/prepare_overlay.py`、比較コードは`bench.py`。

上流coreテストは277 passed、12 skipped、1 xfailed。7ペアの新規プロセス、同じCPU固定・仕事量一致を確認したCPU速度比（stock / inline、1超が改善）の中央値はcheckpoint_600が1.025（範囲0.969–1.094）、nursery_spawnが0.979（0.926–1.188）、mixed_600が1.006（0.947–1.407）。mixedのタイマー遅れp99中央値はstock 1.322ms、候補1.254ms、checkpoint待ちp99は0.267ms、0.279ms。生データは`inline_checkpoint.json`。

checkpoint専用負荷に小さな改善の兆候はあるが共有ホストの試行変動より明確に大きいとは言えず、nursery・mixedにも一貫した改善はない。公開APIの振る舞いはcoreテストの範囲で確認したのみ。現時点では上流へ提案する根拠として弱く、追加の互換性テストと独立した計測が必要。

目的はTrio本体の改善である。アプリの起床回数を減らす方針ではない。これまでのRust製Task状態＋キュー＋batch直結はCPU消費を減らさなかった。次はTrioのイベント通知・タイマー・トラップ／再スケジュールなど、Pythonへの往復が少ない塊を探す。独立したホットパスが見つかれば、Trio APIを維持したRustコアの候補として比較する。純Python版の小さな整理も対照として残す。
