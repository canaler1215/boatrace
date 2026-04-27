# 次セッション用プロンプト C — フェーズ B-3 拡張: 2 連単 / 2 連複 / 拡連複 オッズ DL 関数の実装（着手前合意フェーズ）

以下を新セッションの最初のユーザープロンプトとして貼り付けてください。

---

## プロンプト本文

boatrace プロジェクトのフェーズ B-3「馬券種転換による市場効率分析」の **拡張タスク C** に着手してほしい。

これは控除率 25% の残り 3 券種（**2 連単 / 2 連複 / 拡連複**）のオッズ DL 関数を一括追加する作業。3 連単（B-1 撤退）と同じ控除率だが、組合せ数が少ない（30 / 15 / 15）ため、ノイズに埋もれた歪みを発見できる可能性が残されている。優先度は B（単勝 Step 2）/ A（複勝）より低いが、後で網羅的に分析するために DL 関数だけ整えておく。

作業開始前に必ず以下を読むこと:

- `MARKET_EFFICIENCY_WIN_RESULTS.md`（B-3 Step 1 結果、boatrace.jp スクレイピングの実装パターン）
- `MARKET_EFFICIENCY_PLACE_RESULTS.md`（拡張 A の結果。範囲オッズの扱いがあれば参照）
- `NEXT_PHASE_B3_PLAN.md` §1（券種別控除率表）
- `ml/src/collector/openapi_client.py`（既存 `fetch_odds` (3 連単) / `fetch_trio_odds` (3 連複) / `fetch_win_odds` (単勝) / `fetch_place_odds` (複勝) の実装パターン）
- `ml/src/collector/odds_downloader.py`（既存 `load_or_download_month_*_odds` のキャッシュパターン）
- `CLAUDE.md`「現在の仕様」「現行の運用方針」
- `BET_RULE_REVIEW_202509_202512.md` §28-32（実運用再開条件）

### これまでの経緯（要約）

| フェーズ | 内容 | 結果 |
|---|---|---|
| 3 `/inner-loop` | 購入フィルタ探索 | 凍結 |
| 6 `/model-loop` | モデル構造改善 | 完全撤退 |
| 7 (B-1) | 3 連単市場効率分析（控除率 25%） | 完全撤退（最高 ev=0.98） |
| **B-3** Step 1 | 単勝オッズ DL（控除率 20%） | 完了 |
| **B-3 拡張 A** | 複勝 DL（控除率 20%） | 完了想定 |
| **B-3 拡張 C**（本タスク）| **2 連単 / 2 連複 / 拡連複 DL（控除率 25%）** | **着手予定** |

### 拡張 C を選んだ理由（控除率 25% でも DL 関数だけは整える）

- 控除率 25% の券種は B-1 で 3 連単が撃破されているため、**2 連系で歪みが見つかる確率は限定的**
- ただし組合せ数 30 / 15 / 15 で 3 連単 (120) より粗いため、サンプルサイズの分厚さで「ノイズに埋もれた小さな歪み」を発見できる可能性は残る
- DL 関数を整えておくことで、Step 2 単勝結果を見てから「複勝で再挑戦」「2 連系で再挑戦」のどちらかを選べる柔軟性を確保
- 本タスクは **DL 関数の実装のみ**。試行 DL 実行の判断は別途

### 拡張 C で行うこと（最小スコープ）

**3 券種の DL 関数を一括追加 + 各 1 レース動作確認**（boatrace.jp の各オッズページ HTML 構造調査含む）。試行 DL（1 ヶ月）は **単勝 + 複勝の 12 ヶ月本番 DL がすべて完了していること** を確認してから実行。

1. boatrace.jp の各オッズページのエンドポイントと HTML 構造を 1 レース分ずつ調査
   - 2 連単: `/owpc/pc/race/odds2tf` (推測)
   - 2 連複: `/owpc/pc/race/odds2tf` (同ページ内で 2 連単と並列 / 別ページ)
   - 拡連複（ワイド）: `/owpc/pc/race/oddsk` (推測)
2. `ml/src/collector/openapi_client.py` に以下を追加:
   - `fetch_exacta_odds(stadium_id, race_date, race_no) -> dict[str, float]` （2 連単、30 通り）
   - `fetch_quinella_odds(stadium_id, race_date, race_no) -> dict[str, float]` （2 連複、15 通り）
   - `fetch_wide_odds(stadium_id, race_date, race_no) -> dict[str, tuple[float, float]]` （拡連複、15 通り、範囲オッズ）
3. `ml/src/collector/odds_downloader.py` に各々の `load_or_download_month_*_odds` 追加
4. キャッシュ形式:
   - `data/odds/exacta_odds_YYYYMM.parquet`（カラム: race_id, combination, odds）combination は `"1-2"` 形式（順序つき、1 着 - 2 着）
   - `data/odds/quinella_odds_YYYYMM.parquet`（同上）combination は `"1-2"` 形式（ソート済み艇番）
   - `data/odds/wide_odds_YYYYMM.parquet`（カラム: race_id, combination, odds_low, odds_high）combination はソート済み艇番

### 着手前合意ポイント（実装前にユーザー確認）

以下の設計判断について合意を取ってから着手する:

1. **対象券種の範囲**:
   - (a) 3 券種を 1 セッションで一括（2 連単 + 2 連複 + 拡連複）
   - (b) 1 セッション 1 券種ずつ別々に
   - 推奨: (a) 一括（HTML 構造調査の重複を避けるため、ただし作業量大）
2. **HTML 構造調査方法**:
   - Step 1 と同じく `artifacts/` に 1 レース分の HTML を保存して観察 → パーサー設計
   - 推奨: 上記
3. **2 連単 / 2 連複の同居判定**:
   - 多くの場合 `odds2tf` ページに両方ある（trifecta/trio が `odds3t` / `odds3f` で別ページのケースと違う可能性）
   - 同居している場合: 1 ページから両方抽出する関数 / 別関数で同ページを 2 回 GET、どちらにするか
   - 推奨: 1 ページ取得して両方抽出する内部 helper を作り、`fetch_exacta_odds` / `fetch_quinella_odds` から呼ぶ（API 呼び出し削減）
4. **combination キーのフォーマット**:
   - 2 連単: 順序つき `"1-2"`（1 着 - 2 着）
   - 2 連複: ソート済み `"1-2"`（艇番昇順、3 連複と同流儀）
   - 拡連複: ソート済み `"1-2"`（艇番昇順）
   - 推奨: 上記
5. **拡連複の範囲オッズ保存形式**:
   - 拡張 A の複勝と同じく `odds_low` / `odds_high` 別カラム
   - 推奨: 上記
6. **試行 DL タイミング**:
   - 単勝 + 複勝の 12 ヶ月本番 DL **完了後**に拡張 C の試行 DL を実行
   - 確認コマンド: `ls data/odds/win_odds_*.parquet | wc -l` (12 ファイル) + `ls data/odds/place_odds_*.parquet | wc -l` (12 ファイル)
   - 並列 DL は禁止
   - 推奨: 上記
7. **試行 DL の月**:
   - 2025-12（race_id 突合可能）
   - 推奨: 上記
8. **HTML 構造が想定と違う / API がない場合**:
   - 該当券種の DL 関数のみ撤退、他の券種は実装継続
   - 推奨: 上記
9. **コード差分のスコープ**:
   - `openapi_client.py` + `odds_downloader.py` への追加のみ
   - `run_market_efficiency.py` は本タスクで触らない（`--bet-type {exacta,quinella,wide}` 拡張は将来別タスク）
   - 推奨: 上記

これらが合意できたら拡張 C を実装する。

### 拡張 C の終了条件

- `fetch_exacta_odds` / `fetch_quinella_odds` / `fetch_wide_odds` がそれぞれ実装され、各 1 レース分の動作確認 OK
- `load_or_download_month_exacta_odds` / `load_or_download_month_quinella_odds` / `load_or_download_month_wide_odds` 実装
- 単勝 + 複勝 DL 完了確認後、試行 DL（2025-12）で 3 種類の `data/odds/*.parquet` が出る
- parquet の中身を確認（件数、組合せ数 30 / 15 / 15、欠場考慮）
- ユーザーへ 12 ヶ月本番 DL 実行可否を確認（券種別に判断）

### 拡張 C の判定

- **取得 OK**: 試行 DL でデータが期待通り取れた → 各券種の 12 ヶ月本番 DL を順次実行（並列禁止）
- **特定券種 NG**: HTML 構造が想定外 → 該当券種のみ撤退、他は継続
- **全券種 NG**: 拡張 C 全体撤退

### 厳守事項

- ❌ 既存モデル（trainer.py / predictor.py / engine.py）は触らない
- ❌ **単勝 + 複勝の 12 ヶ月本番 DL 完了前**に拡張 C の試行 DL を始めない
- ❌ 試行 DL も含め、**並列 DL 禁止**（boatrace.jp への過負荷）
- ❌ 既存 `data/odds/{odds,trio_odds,win_odds,place_odds}_*.parquet` を上書きしない（**`exacta_odds`/`quinella_odds`/`wide_odds` 別ファイル**で管理）
- ❌ 着手前合意ポイント（上記 1〜9）を**スキップしない**
- ❌ 控除率 25% は 3 連単（B-1 撤退）と同じため「DL したから期待しろ」という前提を持たない（あくまで網羅的整備のためのタスク）

### 成果物（拡張 C 完了時）

1. `ml/src/collector/openapi_client.py` に `fetch_exacta_odds` / `fetch_quinella_odds` / `fetch_wide_odds` 追加
2. `ml/src/collector/odds_downloader.py` に各 `load_or_download_month_*_odds` 追加
3. `data/odds/exacta_odds_202512.parquet` / `quinella_odds_202512.parquet` / `wide_odds_202512.parquet`（試行 DL）
4. `MARKET_EFFICIENCY_2BET_RESULTS.md`（仮、拡張 C 結果と将来の Step 2 進行 / 撤退の判定。3 券種をまとめて記載）
5. `AUTO_LOOP_PLAN.md` フェーズ 8 進捗更新（券種ごとに状態追記）

### 実行環境

- Python 3.12（`py -3.12`）
- ローカル（Windows）、DB 接続不要
- 必要キャッシュ: `data/history/` + `data/program/`
- 想定実行時間: HTML 構造調査 1 時間、実装 2〜3 時間、試行 DL（1 ヶ月 × 3 券種）= 約 4 時間（直列実行）

### 参照すべきドキュメント

- [MARKET_EFFICIENCY_WIN_RESULTS.md](MARKET_EFFICIENCY_WIN_RESULTS.md) — B-3 Step 1（単勝）DL 実装パターン
- [MARKET_EFFICIENCY_PLACE_RESULTS.md](MARKET_EFFICIENCY_PLACE_RESULTS.md) — 拡張 A（複勝）DL 実装パターン、範囲オッズの先行例
- [NEXT_PHASE_B3_PLAN.md](NEXT_PHASE_B3_PLAN.md) §1 — 券種別控除率表
- [CLAUDE.md](CLAUDE.md) — 「現行の運用方針」「現在の仕様」
- [ml/src/collector/openapi_client.py](ml/src/collector/openapi_client.py) — `fetch_odds` / `fetch_trio_odds` / `fetch_win_odds` / `fetch_place_odds` を流用ベースに
- [ml/src/collector/odds_downloader.py](ml/src/collector/odds_downloader.py) — 既存パターンを流用

以上。**着手前合意ポイント 1〜9 をユーザー合意してから実装に入ってほしい**。
