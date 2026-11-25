# Rustキューの空判定：単独比較

Trio 0.35.0 / CPython 3.12.14 / Linux x86_64。`reschedule_native` で既存のPython `bool(runq)` の代わりにRustの`VecDeque::is_empty`を呼ぶ候補。候補は`set_native_empty_check(True)`で有効にし、既定動作は変更しない。7ペア、各回新規プロセス、同じCPUへの固定、仕事量一致。通常のreleaseビルドを使用。

| 負荷 | 既存Rust版 / 候補のCPU時間比中央値（1超が候補改善） | 範囲 |
|---|---:|---:|
| checkpoint_600 | 0.965 | 0.749–1.021 |
| nursery_spawn | 0.996 | 0.890–1.150 |
| mixed_600 | 1.045 | 0.872–1.205 |

mixedのp99中央値はタイマー遅れで既存1.414ms・候補1.377ms、checkpoint待ちで既存0.403ms・候補0.348ms。差が小さく共用ホストの変動もあるため改善と判定しない。候補を有効にした隔離forkでTrio core＋GCテスト277 passed、12 skipped、1 xfailed。生データは`native_empty_check.json`。

判断：この局所変更はcheckpointのCPU時間を減らせず、既定では採用しない。高頻度に通るPython操作を一個Rust呼び出しに置き換えても、PyO3の借用と分岐の費用を回収できないことがある。次に改善を狙うなら境界を跨ぐ操作をまとめる必要がある。実環境でのCPU効率は未測定。
