# Trio 0.35.0: deadline登録更新の共通化

Trio 0.35.0 / CPython 3.12.14 / Linux x86_64。Trio本体の`CancelScope.deadline` setterが使う`contextmanager`の生成とenter/exitを避ける局所的な変更。既存の登録更新処理は`_sync_registered_deadline`に一度だけ置き、元のcontextmanagerとsetterの専用KI保護メソッドから呼ぶ。公開API、NaNとrelative deadlineの検査、`finally`での登録更新、guest実行時の通知は維持する。変更そのものは`trio_deadline.patch`、再生成手順は`spikes/python_deadline/prepare_overlay.py`。

| 負荷 | CPU速度比の中央値 (stock/候補) | 7ペアの範囲 | CPU時間の中央値 stock/候補 |
|---|---:|---:|---:|
| deadline_churn: scope 3000件・deadline更新6000回 | 1.270 | 1.152–1.372 | 24.897 / 19.519 ms |
| checkpoint_600 | 1.028 | 0.945–1.338 | 106.595 / 105.163 ms |
| mixed_600 | 0.986 | 0.910–1.019 | 46.658 / 47.498 ms |

ベンチは新規プロセスで7回ペア比較、各ペアの仕事量を照合し、`process_time_ns`でCPU時間を計測。生データは`deadline_shared_helper.json`。deadline更新の全7ペアで候補が速い。一方、一般的なcheckpointやmixed負荷について速度・CPU効率の改善は確認できない。共有ホストの短い測定なので、別環境での再測定が必要。

Trioのcoreテスト: **277 passed、12 skipped、1 xfailed**。上位timeoutテスト: **6 passed、5 skipped、1 xfailed**。どちらも隔離overlayに対し実行。Python 3.15はこの環境に存在せず、検証していない。全suite・OS別動作も未検証。

判断: Trio自体への小さなPython変更として検討可能。Rust導入の妥当性を示す結果ではなく、期限を頻繁に更新する負荷に限定してCPU使用量を減らす候補。上流提案前には全suite、3.15、実アプリのCPUプロファイルと長時間ベンチを確認する。
