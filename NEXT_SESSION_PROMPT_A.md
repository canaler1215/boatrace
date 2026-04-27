# 次セッション用プロンプト A — フェーズ B-3 拡張: 複勝 (place) オッズ DL 関数の実装（着手前合意フェーズ）

以下を新セッションの最初のユーザープロンプトとして貼り付けてください。

---

## プロンプト本文

boatrace プロジェクトのフェーズ B-3「馬券種転換による市場効率分析」の **拡張タスク A** に着手してほしい。

これは B-3 Step 1（単勝オッズ DL 関数）と同じ枠組みで、**控除率 20% の複勝 (place)** のオッズ DL 関数を追加する作業。単勝 (B-3) で歪みが控除率を破れなかった場合の保険として、複勝での再挑戦に備える。

作業開始前に必ず以下を読むこと:

- `MARKET_EFFICIENCY_WIN_RESULTS.md`（B-3 Step 1 結果、`oddstf` ページの table[2] が複勝表で範囲オッズ "X.X-Y.Y" であることを確認済み）
- `NEXT_PHASE_B3_PLAN.md` §1（券種別控除率表、複勝の位置付け）
- `ml/src/collector/openapi_client.py`（既存 `fetch_win_odds`、`fetch_odds`、`fetch_trio_odds` の実装パターン）
- `ml/src/collector/odds_downloader.py`（既存 `load_or_download_month_win_odds` 等のキャッシュパターン）
- `CLAUDE.md`「現在の仕様」「現行の運用方針」（全フェーズ撤退状態 + B-3 進行中）
- `BET_RULE_REVIEW_202509_202512.md` §28-32（実運用再開条件）

### これまでの経緯（要約）

| フェーズ | 内容 | 結果 |
|---|---|---|
| 3 `/inner-loop` | 購入フィルタ探索 | out-of-sample 黒字化不能、凍結 |
| 6 `/model-loop` | モデル構造改善 | 完全撤退（採用基準達成 0） |
| 7 (B-1) | 3 連単市場効率分析（控除率 25%） | 完全撤退（最高 ev=0.98 / 蒲郡 × 1 コース） |
| **B-3** Step 1 | 単勝オッズ DL 関数 + 試行 DL（控除率 20%） | 完了（4,771 races / 100% 取得、実勢 overround 1.36） |
| **B-3 拡張 A**（本タスク）| **複勝 (place) DL 関数の実装のみ** | **着手予定** |

### 拡張 A を選んだ理由

- 単勝 (B-3) と同じ控除率 20%、黒字化に必要な lift も同じ ≥ 1.25
- 複勝は「3 着以内」判定で hit 確率が高く、ROI 分散が小さい可能性
- 単勝で歪みが見つからなくても複勝で再挑戦できる構造的保険
- HTML は既に取得済み（`oddstf` の table[2] が複勝表、Step 1 で構造確認済み）

### 拡張 A で行うこと（最小スコープ）

**複勝オッズ取得関数 + DL コードのみ実装**。試行 DL（1 ヶ月）は **単勝 12 ヶ月本番 DL が完了していること** を確認してから実行（並列 DL は boatrace.jp への過負荷で禁止）。

1. `ml/src/collector/openapi_client.py` に `fetch_place_odds(stadium_id, race_date, race_no)` 追加
2. `ml/src/collector/odds_downloader.py` に `_place_cache_path` / `download_place_odds_for_races` / `load_or_download_month_place_odds` 追加
3. **単勝 DL 完了確認後に**試行 DL（2025-12 推奨）
4. parquet 検証 → ユーザーに 12 ヶ月本番 DL 実行可否を確認

### 着手前合意ポイント（実装前にユーザー確認）

以下の設計判断について合意を取ってから着手する:

1. **複勝オッズの保存形式**:
   - 複勝オッズは boatrace.jp で範囲表記 `"2.4-3.1"`（最低オッズ - 最高オッズ）
   - (a) `(odds_low, odds_high)` 別カラム保存 — 情報損失なし、後段で柔軟
   - (b) 中点 `odds_mid = (low + high) / 2` 1 カラム — シンプルだが情報損失
   - (c) 両方保存（low / high / mid 3 カラム）— 冗長だが安心
   - 推奨: (a) `odds_low` / `odds_high` 2 カラム
2. **キャッシュ形式**:
   - `data/odds/place_odds_YYYYMM.parquet`、カラム `race_id, combination, odds_low, odds_high`
   - `combination` は `"1"`〜`"6"`（艇番文字列、単勝と同じ）
   - 既存 `_df_to_map` ヘルパーは odds 単一値前提なので、複勝用に新規 `_place_df_to_map` を追加するか流用するか
   - 推奨: 専用 `_place_df_to_map` を追加して `{race_id: {combination: (low, high)}}` 形式に
3. **fetch_place_odds の戻り値型**:
   - `dict[str, tuple[float, float]]`（キー: 艇番、値: (low, high)）
   - 推奨: 上記
4. **試行 DL の月**:
   - 2025-12（単勝で既に試行 DL 完了、race_id 突合可能）
   - 推奨: 上記
5. **DL タイミング**:
   - 単勝 12 ヶ月本番 DL 完了**後** に試行 DL 実行
   - 開始前に `ls data/odds/win_odds_2025{05..11}.parquet data/odds/win_odds_2026{01..04}.parquet | wc -l` で 11 ファイル確認
   - 並列実行禁止
   - 推奨: 上記
6. **本番 DL 実行可否**:
   - 試行 DL 結果が問題なければユーザーに 12 ヶ月本番 DL の実行確認を取る
   - 推奨時間帯: 単勝 DL と同程度（12〜24 時間バックグラウンド）
   - 推奨: 上記
7. **コード差分のスコープ**:
   - `openapi_client.py` + `odds_downloader.py` への追加のみ
   - `run_market_efficiency.py` は本タスクで触らない（`--bet-type place` 拡張は将来別タスク）
   - 推奨: 上記

これらが合意できたら拡張 A を実装する。

### 拡張 A の終了条件

- `fetch_place_odds(stadium_id, race_date, race_no) -> dict[str, tuple[float, float]]` が実装され、1 レース分の動作確認 OK
- `load_or_download_month_place_odds(year, month, race_df)` が実装される
- 単勝 DL 完了確認後、試行 DL（2025-12）で `data/odds/place_odds_202512.parquet` が出る
- parquet の中身を読んで `race_id × 6 通り × (low, high)` の形式確認
- ユーザーへ 12 ヶ月本番 DL 実行可否を確認

### 拡張 A の判定

- **取得 OK**: 試行 DL でデータが期待通り取れた → 12 ヶ月本番 DL に進む or 単勝 Step 2 結果を待ってから判断
- **取得 NG**: 範囲オッズパースに想定外の問題 → 拡張 A 撤退、複勝は今後検討対象から外す

### 厳守事項

- ❌ 既存モデル（trainer.py / predictor.py / engine.py）は触らない
- ❌ **単勝 12 ヶ月本番 DL 完了前**に複勝の試行 DL を始めない（並列 DL は boatrace.jp への過負荷）
- ❌ 既存 `data/odds/{odds,trio_odds,win_odds}_*.parquet` を上書きしない（**`place_odds_*.parquet` 別ファイル**で管理）
- ❌ 着手前合意ポイント（上記 1〜7）を**スキップしない**

### 成果物（拡張 A 完了時）

1. `ml/src/collector/openapi_client.py` に `fetch_place_odds` 追加
2. `ml/src/collector/odds_downloader.py` に `_place_cache_path` / `download_place_odds_for_races` / `load_or_download_month_place_odds` 追加（必要なら `_place_df_to_map`）
3. `data/odds/place_odds_202512.parquet`（試行 DL の結果）
4. `MARKET_EFFICIENCY_PLACE_RESULTS.md`（仮、拡張 A 結果と将来の Step 2 進行 / 撤退の判定）
5. `AUTO_LOOP_PLAN.md` フェーズ 8 進捗更新

### 実行環境

- Python 3.12（`py -3.12`）
- ローカル（Windows）、DB 接続不要
- 必要キャッシュ: `data/history/` + `data/program/`
- 想定実行時間: 実装 1〜2 時間、試行 DL（1 ヶ月）= 75 分（単勝 DL と同等）

### 参照すべきドキュメント

- [MARKET_EFFICIENCY_WIN_RESULTS.md](MARKET_EFFICIENCY_WIN_RESULTS.md) — Step 1 結果、`oddstf` 構造確認済み
- [NEXT_PHASE_B3_PLAN.md](NEXT_PHASE_B3_PLAN.md) §1 — 券種別控除率表
- [CLAUDE.md](CLAUDE.md) — 「現行の運用方針」「現在の仕様」
- [ml/src/collector/openapi_client.py](ml/src/collector/openapi_client.py) — `fetch_win_odds` を流用ベースに
- [ml/src/collector/odds_downloader.py](ml/src/collector/odds_downloader.py) — `load_or_download_month_win_odds` を流用ベースに

以上。**着手前合意ポイント 1〜7 をユーザー合意してから実装に入ってほしい**。
