# Trio本体の期限変更経路

Trio 0.35.0 / CPython 3.12.14 / Linux x86_64。`deadline_churn`のcProfileでは、期限ヒープ操作（`heappush`）より`_might_change_registered_deadline`と`contextlib`のenter/exitが多く実行される。3000 scope・各2更新の負荷で、contextmanagerの呼び出しと生成は各12008回。Rustのヒープだけを置き換えても、この費用は消えない。

ハッシュ照合したTrioの隔離コピーで、`CancelScope.deadline` setterから汎用`contextmanager`を呼ぶ代わりに、KI保護付きの専用メソッドで登録更新を行った。NaN検査・relative deadlineの例外は元setterに残し、KI保護は元のwith本体と同じ範囲に置いた。`finally`による登録更新、guest時の次期限の再判定、重複期限対策の元`Deadlines`実装は維持。

上流coreテスト277 passed、12 skipped、1 xfailed。7ペア新規プロセス、CPU固定、仕事量一致のCPU速度比中央値（stock / 候補、1超が改善）は以下。

| 負荷 | CPU速度比中央値 | 7ペア範囲 | CPU時間中央値 stock / 候補 |
|---|---:|---:|---:|
| deadline_churn | 1.223 | 1.136–1.380 | 23.1 / 19.1 ms |
| checkpoint_600 | 1.032 | 0.908–1.221 | 103.3 / 98.2 ms |
| mixed_600 | 1.031 | 0.978–1.134 | 43.1 / 41.5 ms |

mixedのタイマー遅れp99はstock 1.265ms、候補1.242ms、checkpoint待ちp99は0.265ms、0.266ms。共有ホストでの短い試行なので、deadline以外の小差は改善と判定しない。比較データは`deadline_setter.json`、変更生成コードは`spikes/python_deadline/prepare_overlay.py`。最初のsetter全体をKI保護した版は約1.31倍だったが、保護範囲を合わせた最終版を上表の判断に用いる。

判断：期限を頻繁に変更するTrio利用では、Python実装だけでCPU費用を減らせる有望な候補。Rustによる`Deadlines`ヒープ移植を先行する根拠は薄い。上流PR候補にする前に、通常のTrio開発環境で全suite・複数OS・CPython 3.15を確認し、専用メソッドの重複ロジックを保守しやすく整理する必要がある。実アプリや一般的なTrio負荷全体の速度向上は未確認。
