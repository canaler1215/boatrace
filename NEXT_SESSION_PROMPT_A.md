# 次セッション用プロンプト A — フェーズ B-3 拡張: 複勝 (place) フェーズ Step 1（DL 関数 + 試行 DL）

以下を新セッションの最初のユーザープロンプトとして貼り付けてください。

---

## プロンプト本文

boatrace プロジェクトのフェーズ B-3「馬券種転換による市場効率分析」の **拡張タスク A（複勝 / place）Step 1** に着手してほしい。

これは B-3 単勝（win）と同じ枠組みを **控除率 20% の複勝** に適用する作業。**単勝（win）が撤退確定**（2026-04-27、最善実 ROI -25.87%）した今、複勝で同じ歪み構造が控除率を破れるかを検証する保険として実施する。

### 前提（重要）

- **B-3 win（単勝）撤退確定済み**（2026-04-27）。詳細は [MARKET_EFFICIENCY_WIN_RESULTS.md](MARKET_EFFICIENCY_WIN_RESULTS.md) §6-§7
- 単勝 12 ヶ月 DL 完了済み（`data/odds/win_odds_2025{05..12}.parquet` + `2026{01..04}.parquet`、計 12 ファイル）
- **本セッションは A Step 1 のみ**（DL 関数の実装 + 1 ヶ月試行 DL）。12 ヶ月本番 DL と Step 2 集計は別セッション

作業開始前に必ず以下を読むこと:

- [MARKET_EFFICIENCY_WIN_RESULTS.md](MARKET_EFFICIENCY_WIN_RESULTS.md)（B-3 win 撤退結果。実 ROI、`ev_all_buy` 上方バイアス、実勢 overround 1.36 等の重要観察）
- [NEXT_PHASE_B3_PLAN.md](NEXT_PHASE_B3_PLAN.md) §1（券種別控除率表）
- [ml/src/collector/openapi_client.py](ml/src/collector/openapi_client.py)（既存 `fetch_win_odds`、`fetch_odds`、`fetch_trio_odds` の実装パターン）
- [ml/src/collector/odds_downloader.py](ml/src/collector/odds_downloader.py)（既存 `load_or_download_month_win_odds` 等のキャッシュパターン）
- [CLAUDE.md](CLAUDE.md)（「現行の運用方針」「現在の仕様」）
- [BET_RULE_REVIEW_202509_202512.md](BET_RULE_REVIEW_202509_202512.md) §28-32（実運用再開条件）

### これまでの経緯

| フェーズ | 内容 | 結果 |
|---|---|---|
| 3 `/inner-loop` | 購入フィルタ探索 | out-of-sample 黒字化不能、凍結 |
| 6 `/model-loop` | モデル構造改善 | 完全撤退（採用基準達成 0） |
| 7 (B-1) | 3 連単市場効率分析（控除率 25%） | 完全撤退（最高 ev=0.98 / 蒲郡 × 1 コース） |
| **B-3 win** | 単勝市場効率分析（控除率 20% 理論） | **完全撤退**（実勢 overround 1.36 = 実控除率 26%、最大 lift 1.094、最善実 ROI -25.87%） |
| **B-3 place**（本タスク）Step 1 | **複勝 DL 関数 + 1 ヶ月試行 DL** | **着手予定** |
| B-3 place Step 2（別セッション）| 12 ヶ月本番 DL + `run_market_efficiency.py --bet-type place` + 集計 | 後日 |

### B-3 win 撤退から得た構造的知見（A Step 1 設計に反映）

1. **理論控除率と実勢 overround は乖離する** — win 単勝の理論控除率 20% に対し、実勢 overround 1.36（実控除率 26%）。複勝でも同様の乖離が予想される
2. **`ev_all_buy = mean_odds × mean_hit` は実 ROI と乖離**（オッズ幅広い帯で +20〜39pp の上方バイアス、Cov(odds, hit) < 0 のため）。Step 2 集計時は **sum-aggregated 実 ROI** も併記する設計が必須
3. **歪みの振幅は券種シンプル化で減る**（trifecta max lift 1.27 → win 1.094）。複勝はさらに「3 着以内」で hit 確率高 → 歪み振幅はさらに小さい可能性
4. **複勝はオッズが範囲表記**（`"X.X-Y.Y"`）。実 ROI 計算時の odds 確定の仕方に注意（最低オッズで保守的に評価するか中点で評価するか）

### 拡張 A Step 1 で行うこと（最小スコープ）

**複勝オッズ取得関数 + DL コードのみ実装 + 1 ヶ月試行 DL**。本番 DL（12 ヶ月）と集計（`run_market_efficiency.py --bet-type place` 拡張）は別セッション。

1. `ml/src/collector/openapi_client.py` に `fetch_place_odds(stadium_id, race_date, race_no)` 追加
2. `ml/src/collector/odds_downloader.py` に `_place_cache_path` / `download_place_odds_for_races` / `load_or_download_month_place_odds` 追加
3. **試行 DL**（2025-12 推奨、単勝で取得済みの月と揃える）
4. parquet 検証 → ユーザーに 12 ヶ月本番 DL 実行可否を確認

### 開始前のチェック（必ず実行）

```bash
# 単勝 12 ヶ月 DL の完了確認
ls data/odds/win_odds_*.parquet | wc -l   # 12 を期待
```

### 着手前合意ポイント（実装前にユーザー確認）

以下の設計判断について合意を取ってから着手する:

1. **複勝オッズの保存形式**:
   - 複勝オッズは boatrace.jp で範囲表記 `"2.4-3.1"`（最低オッズ - 最高オッズ）
   - (a) `(odds_low, odds_high)` 別カラム保存 — 情報損失なし、後段で柔軟
   - (b) 中点 `odds_mid = (low + high) / 2` 1 カラム — シンプルだが情報損失
   - (c) 両方保存（low / high / mid 3 カラム）— 冗長だが安心
   - 推奨: **(a) `odds_low` / `odds_high` 2 カラム**（Step 2 集計時に「保守的評価＝low 採用 / 期待値ベース＝mid 採用」を選択可能にする）

2. **キャッシュ形式**:
   - `data/odds/place_odds_YYYYMM.parquet`、カラム `race_id, combination, odds_low, odds_high`
   - `combination` は `"1"`〜`"6"`（艇番文字列、単勝と同じ）
   - 既存 `_df_to_map` ヘルパーは odds 単一値前提なので、複勝用に新規 `_place_df_to_map` を追加
   - 推奨: 専用 `_place_df_to_map` で `{race_id: {combination: (low, high)}}` 形式

3. **`fetch_place_odds` の戻り値型**:
   - `dict[str, tuple[float, float]]`（キー: 艇番文字列、値: `(low, high)`）
   - 推奨: 上記

4. **欠場レース / 欠場艇の扱い**:
   - 単勝同様、艇数 < 6 のレースが約 5.8% 存在する見込み
   - DL 段階では取得できる艇のみ parquet に保存（行数 = 取得艇数）
   - Step 2 集計で 6 艇全揃いに filter する（`run_market_efficiency.py` 側で対応）
   - 推奨: 上記

5. **`oddstf` ページの table 判別ロジック**:
   - 既存 `fetch_win_odds` は「オッズ列が範囲表記でない方を単勝」と判別
   - 複勝は逆に「オッズ列が範囲表記の方」
   - 既存ロジックの**裏側を取る**形で `fetch_place_odds` を実装（共通の HTML パーサ抽出も検討可だが、保守性優先で別関数として独立実装）
   - 推奨: 別関数として独立実装、HTML 取得部分のみ既存 `_fetch_oddstf_html` 風の関数で共通化

6. **試行 DL の月**:
   - 2025-12（単勝で既に完了、race_id 突合可能）
   - 推奨: 上記

7. **DL タイミング・並列度**:
   - 単勝 12 ヶ月本番 DL **完了後**（既に完了済み）
   - 並列度は単勝と同等（10 ワーカー）、boatrace.jp への過負荷回避
   - 試行 DL（2025-12 単月）の所要は 75 分前後の見込み
   - 推奨: 上記

8. **コード差分のスコープ**:
   - `openapi_client.py` + `odds_downloader.py` への追加のみ
   - `run_market_efficiency.py` は本タスクで触らない（`--bet-type place` 拡張は Step 2 集計セッション）
   - 推奨: 上記

これらが合意できたら拡張 A Step 1 を実装する。

### 拡張 A Step 1 の終了条件

- `fetch_place_odds(stadium_id, race_date, race_no) -> dict[str, tuple[float, float]]` が実装され、1 レース分の動作確認 OK（例: 桐生 2025-12-01 1R で 6 艇分取得確認）
- `load_or_download_month_place_odds(year, month, race_df)` が実装される
- 試行 DL（2025-12）で `data/odds/place_odds_202512.parquet` が出る
- parquet の中身を読んで `race_id × 6 通り × (low, high)` の形式確認
- 1 レース sample で複勝 implied probability 計算（`(low + high) / 2` の逆数）と overround 観察
- 結果を `MARKET_EFFICIENCY_PLACE_RESULTS.md` に記録
- ユーザーへ 12 ヶ月本番 DL 実行可否を確認

### 拡張 A Step 1 の判定（次フェーズ進行 or 撤退）

- **取得 OK**: 試行 DL でデータが期待通り取れた
  - 実勢 overround が実勢で 3.0 近辺（理論: 3 通り当選 / 6 通り = 0.5 + 控除率 → ~3）であることを確認
  - 単勝の overround 1.36（控除率 26%）と比較し、複勝の実控除率推定値を算出
  - → ユーザー承認後、12 ヶ月本番 DL を別セッションで実施
- **取得 NG**: 範囲オッズパースに想定外の問題、または overround が想定外（控除率 30%+ 等）→ 拡張 A 撤退、複勝は今後検討対象から外す

### 厳守事項

- ❌ 既存モデル（trainer.py / predictor.py / engine.py）は触らない
- ❌ 既存 `data/odds/{odds,trio_odds,win_odds}_*.parquet` を上書きしない（**`place_odds_*.parquet` 別ファイル**で管理）
- ❌ 着手前合意ポイント（上記 1〜8）を**スキップしない**
- ❌ 本セッションで `run_market_efficiency.py` には触らない（Step 2 集計は別セッション）
- ❌ 1 ヶ月試行 DL の前に必ず単勝 12 ヶ月 DL の完了を確認（並列 DL 禁止）

### 成果物（拡張 A Step 1 完了時）

1. `ml/src/collector/openapi_client.py` に `fetch_place_odds` 追加
2. `ml/src/collector/odds_downloader.py` に `_place_cache_path` / `download_place_odds_for_races` / `load_or_download_month_place_odds` 追加（必要なら `_place_df_to_map`）
3. `data/odds/place_odds_202512.parquet`（試行 DL の結果）
4. `MARKET_EFFICIENCY_PLACE_RESULTS.md`（新規、Step 1 結果と将来の Step 2 進行 / 撤退の判定基準）
5. `AUTO_LOOP_PLAN.md` フェーズ 8 進捗更新（拡張 A Step 1 完了）

### 実行環境

- Python 3.12（`py -3.12`）
- ローカル（Windows）、DB 接続不要
- 必要キャッシュ: `data/history/` + `data/program/`（既に揃っている）
- 想定実行時間: 実装 1〜2 時間、試行 DL（1 ヶ月）= 75 分前後（単勝 DL と同等）

### A Step 2 集計フェーズで行うこと（後日、別セッション。本セッション対象外）

参考までに、A Step 1 完了後の流れを記載:

1. ユーザー承認後、12 ヶ月本番 DL（バックグラウンド、12〜24 時間）
2. `run_market_efficiency.py` に `--bet-type place` 拡張
   - `LINEAR_BINS_PLACE`（複勝向け、3 着以内なので mean_implied 0.3〜0.7 想定 → 等幅 10 ビン or 等密度）
   - `DEFAULT_TAKEOUT_PLACE = 0.20`（理論）、ただし B-3 win の教訓で実勢 overround を併記
   - 複勝のヒット判定: `combination ∈ {boat_no(1着), boat_no(2着), boat_no(3着)}`（K ファイル `finish_position ∈ {1,2,3}`）
   - **複勝は 1 レースに 3 hit（artificial multi-hit）を許容する集計が必要** — 単勝の sum-to-1 前提は使えない
   - **`ev_all_buy` の上方バイアス問題を踏まえ、sum-aggregated 実 ROI も併記**
3. 12 ヶ月集計 + lift / `ev_all_buy` / 実 ROI / bootstrap CI で採用判定
4. → Step 3（サブセグメント）進行 / B-3 place 撤退

### 参照すべきドキュメント

- [MARKET_EFFICIENCY_WIN_RESULTS.md](MARKET_EFFICIENCY_WIN_RESULTS.md) — B-3 win 全結果、実 ROI、ev_all_buy 上方バイアス、`oddstf` 構造等
- [NEXT_PHASE_B3_PLAN.md](NEXT_PHASE_B3_PLAN.md) §1 — 券種別控除率表
- [CLAUDE.md](CLAUDE.md) — 「現行の運用方針」「現在の仕様」
- [ml/src/collector/openapi_client.py](ml/src/collector/openapi_client.py) — `fetch_win_odds` を流用ベースに
- [ml/src/collector/odds_downloader.py](ml/src/collector/odds_downloader.py) — `load_or_download_month_win_odds` を流用ベースに
- [ml/src/scripts/run_market_efficiency.py](ml/src/scripts/run_market_efficiency.py) — A Step 2 集計時の拡張対象（**本セッションでは触らない**）

### 関連プロンプト（次タスク候補、参考）

- **C**: 2 連単 / 2 連複 / 拡連複 DL 関数の実装 → [NEXT_SESSION_PROMPT_C.md](NEXT_SESSION_PROMPT_C.md)（控除率 25%、組合せ 15〜30）

以上。**着手前合意ポイント 1〜8 をユーザー合意してから実装に入ってほしい**。
