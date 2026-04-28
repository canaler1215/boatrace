# 次セッション用プロンプト — フェーズ B-3 拡張 A R3: 12 ヶ月集計 + 補正後 ev で控除率破壊判定

以下を新セッションの最初のユーザープロンプトとして貼り付けてください。

---

## プロンプト本文

boatrace プロジェクトのフェーズ B-3「拡張 A 複勝市場効率分析」の **R3 フェーズ（12 ヶ月集計 + R2 補正後評価）** に着手してほしい。

### 前提（重要）

前セッション（2026-04-28）で R1 / R2 を完了済み:

- **R1 完了**: 競艇複勝の **top-2 仕様**を公式確認、`run_market_efficiency.py --bet-type place` を top-2 仕様に修正、2025-12 単月 smoke test 完了
- **R2 完了**: `fetch_place_payouts` 実装、50 races / 100 hit boats で実 payout 取得 → **pos_in_range mean = 0.245** の補正係数確立（実 payout は odds_low に偏る）

本セッションでは **R3 = R2 補正係数を反映した 12 ヶ月集計を実行 → 採用判定 → Step 3 進行 / 拡張 A 撤退** まで完了させる。

作業開始前に必ず以下を読むこと:

- [MARKET_EFFICIENCY_PLACE_RESULTS.md](MARKET_EFFICIENCY_PLACE_RESULTS.md) §9-§12（**R1 / R2 結果と訂正、本タスクの直接の起点**）
- [MARKET_EFFICIENCY_WIN_RESULTS.md](MARKET_EFFICIENCY_WIN_RESULTS.md) §6-§7（B-3 win 撤退結果、流儀参照）
- [ml/src/scripts/run_market_efficiency.py](ml/src/scripts/run_market_efficiency.py)（拡張対象、`bin_summary_place` / `bootstrap_lift_ci_place` / `evaluate_place_distortion`）
- [ml/src/collector/openapi_client.py](ml/src/collector/openapi_client.py)（`fetch_place_payouts` 実装済み）
- [ml/src/scripts/sample_place_payouts.py](ml/src/scripts/sample_place_payouts.py)（R2 sample スクリプト、再現用）
- [CLAUDE.md](CLAUDE.md) §現行の運用方針（B-3 拡張 A Step 1 + 12 ヶ月 DL 完了状態）

> ⚠️ 旧 [NEXT_SESSION_PROMPT_A.md](NEXT_SESSION_PROMPT_A.md) は **top-3 誤認定**前提で書かれている。参考程度。

### これまでの経緯（要約）

| フェーズ | 内容 | 結果 |
|---|---|---|
| 3 `/inner-loop` | 購入フィルタ探索 | 凍結 |
| 6 `/model-loop` | モデル構造改善 | 完全撤退 |
| 7 (B-1) | 3 連単市場効率分析（控除率 25%） | 完全撤退 |
| **B-3 win** | 単勝市場効率分析（控除率 20%） | 完全撤退（最善 ev=0.964） |
| **B-3 拡張 A** Step 1 / 12 ヶ月 DL | 複勝オッズ DL | 完了（54,277 races / 0 empty） |
| **B-3 拡張 A** R1 | top-2 修正、2025-12 単月 smoke test | 完了（lift 全 bin < 1.0、ev_all_buy_low < 1.0） |
| **B-3 拡張 A** R2 | 50 races 実 payout sample、構造分析 | 完了（pos_in_range = 0.245、補正係数確立） |
| **B-3 拡張 A R3**（本タスク）| **12 ヶ月集計 + 補正後評価 + 採用判定** | **着手予定** |

### R1 / R2 で確定した重要事実

1. **競艇複勝 = top-2 (1〜2 着)**（公式: BOAT RACE オフィシャル「複勝は1着か2着に入る艇を当てるもの」）
2. **odds_low / odds_high は条件付き payout の範囲**（pari-mutuel メカニズムで「もう 1 艇」の人気度に依存）
   - 100% in_range で `odds_low ≤ 実 payout ≤ odds_high` が成立（R2 sample 確認済み）
   - `(1 - takeout) / odds_<mode>` の sum は 1 や 2 に収束しない（条件付き確率の合計のため）
3. **実 payout の分布**: pos_in_range mean = **0.245**、median = 0.0
   - 半数以上のレースで実 payout = odds_low ピッタリ
   - 実 ev ≈ **0.755 × ev_actual_low + 0.245 × ev_actual_high** で近似可能
   - bin 別ばらつき小（0.23〜0.31）→ 全 bin 一様補正で十分
4. **R1 単月（2025-12）の smoke test**:
   - lift 全 bin < 1.0 (0.71〜0.89)
   - ev_actual_low 全 bin < 0.715
   - ev_all_buy_mid が 4 bin で 1.0 超 → ただし R2 で「mid は楽観的すぎ」と判明
   - flagged 1 bin (secondary)、ただし実 payout 補正で再評価必要

### 開始前のチェック（必ず実行）

```bash
ls data/odds/place_odds_*.parquet | wc -l   # 12 を期待
ls artifacts/place_payouts_sample_2025-12.parquet  # R2 成果物が存在
```

### R3 で行うこと（最小スコープ）

1. **`bin_summary_place` に補正後 ev を追加**:
   - `ev_actual_corrected = 0.755 × ev_actual_low + 0.245 × ev_actual_high`
   - 補正係数は定数 `POS_IN_RANGE_R2 = 0.245` として `run_market_efficiency.py` 冒頭に配置
2. **`bootstrap_lift_ci_place` を拡張**:
   - bootstrap 内で `0.755 × mean(odds_low × hit) + 0.245 × mean(odds_high × hit)` を計算
   - `ev_corrected_boot_lo / boot_hi` 列を追加
3. **`evaluate_place_distortion` を補正後 ev ベースに変更**:
   - 主基準: `ev_actual_corrected > 1.0` かつ `ev_corrected_boot_lo > 1.0`（控除率破壊の確信）
   - 補助基準は廃止（mid ベース基準は R2 で無効化された）
4. **`segment_summary_within_focus` / `bootstrap_segment_lift_ci` も補正後 ev に対応**（place 専用ロジック追加）
5. **12 ヶ月集計実行**:
   ```bash
   py -3.12 ml/src/scripts/run_market_efficiency.py \
     --start 2025-05 --end 2026-04 --bet-type place \
     --split-halves --bootstrap 2000 \
     --group-by stadium --group-by-2axis stadium,odds_band \
     --focus-bin-lower 0.10 --focus-bin-upper 0.50
   ```
6. **採用判定 → 結果ドキュメント更新**

### 着手前合意ポイント（実装前にユーザー確認）

以下の設計判断について合意を取ってから着手する:

1. **補正係数の固定値 vs bin 別**:
   - (a) **全 bin 一様で `pos_in_range = 0.245`** — R2 sample で bin 別ばらつき小（0.23〜0.31）を観察、シンプル
   - (b) bin 別補正係数を R2 sample から学習 — sample 50 races では bin 別 n が小さく信頼性低
   - 推奨: **(a) 全 bin 一様 0.245**

2. **採用判定基準**:
   - 主基準: `n ≥ 1,000` かつ `ev_actual_corrected > 1.0` かつ `ev_corrected_boot_lo > 1.0`
   - 補助基準: **廃止**（R2 で「mid > 1.05」基準が無効化された）
   - 前後半同方向チェック維持
   - 推奨: 上記

3. **R2 補正の bootstrap 実装**:
   - (a) 各 bootstrap iter で `0.755 × bin_payout_low + 0.245 × bin_payout_high` を計算 → CI を直接得る
   - (b) `ev_actual_low_boot` と `ev_actual_high_boot` を別々に計算 → 後で重み付き合成
   - 推奨: **(a) iter 内で直接合成**（CI が正しく狭まる）

4. **追加 sample DL の有無**:
   - R2 は 50 races sample で pos_in_range mean = 0.245、std = 0.36
   - 12 ヶ月本番 payout DL（13 時間）は不要（R3 で採用判定が確定すれば）
   - 推奨: **sample 拡張せず、R2 の補正係数で進行**。撤退判定が確定すれば追加 DL 不要

5. **撤退判定後のドキュメント整備**:
   - `MARKET_EFFICIENCY_PLACE_RESULTS.md` に §13「R3 集計結果」§14「採用判定」追記
   - `CLAUDE.md` 現行運用方針を「B-3 拡張 A 撤退確定」に更新
   - `AUTO_LOOP_PLAN.md` フェーズ 8 拡張 A の Step 2 状態更新
   - メモリ `project_p4_phase.md` を撤退状態に更新
   - 推奨: 上記、加えて `NEXT_SESSION_PROMPT_C_R1.md` で次候補 C（連系券種）への移行プロンプトを準備

6. **採用基準達成（控除率破壊あり）の場合の追加検証**:
   - もし `ev_actual_corrected > 1.0` セグメントが見つかった場合、12 ヶ月本番 payout DL（13 時間）を回して **実 payout ベースで完全集計**する必要あり（R2 補正は近似なので、本物の控除率破壊は実 payout で確認すべき）
   - 推奨: 採用基準達成セグメントが出たら **必ず 12 ヶ月実 payout DL** 提案 → ユーザー判断仰ぐ

7. **出力ファイル名**:
   - `artifacts/market_efficiency_2025-05_2026-04_place.csv`
   - `artifacts/market_efficiency_2025-05_2026-04_place.png`
   - `artifacts/market_efficiency_segment_stadium_focus_<focus>_2025-05_2026-04_place.csv`
   - 推奨: 上記、win / trifecta と並列の命名

### R3 の終了条件

- `run_market_efficiency.py --bet-type place --start 2025-05 --end 2026-04` が補正後 ev を出力してエラーなく完走
- `artifacts/market_efficiency_2025-05_2026-04_place.csv` 出力、`ev_actual_corrected` / `ev_corrected_boot_lo / boot_hi` 列が存在
- 採用判定（`ev_actual_corrected` ベース）の集計レポートが `MARKET_EFFICIENCY_PLACE_RESULTS.md` §13-14 に追記され、Step 3 進行 / 拡張 A 撤退の判定がつく

### R3 の判定

- **R3 合格**（採用基準達成セグメント ≥ 1）→ 12 ヶ月本番 payout DL → 完全集計（再ユーザー承認後）
- **R3 不合格**（全セグメントで `ev_actual_corrected < 1.0`）→ **B-3 拡張 A 撤退確定** → ドキュメント整備 → 次候補 C（連系券種）or 完全凍結へ

### 厳守事項

- ❌ 既存モデル（trainer.py / predictor.py / engine.py）は触らない
- ❌ R2 結果（`pos_in_range = 0.245`）を疑わずに進める前提（追加 sample DL 必要時はユーザー承認）
- ❌ 着手前合意ポイント（上記 1〜7）を**スキップしない**
- ❌ 既存 trifecta / win の集計コードを破壊しない（`--bet-type {trifecta,win,place}` の互換維持）
- ❌ 既存出力ファイル `artifacts/market_efficiency_*_trifecta.*` / `artifacts/market_efficiency_*_win.*` を上書きしない
- ❌ 採用基準達成セグメントが出ても、**実 payout DL せずに採用宣言しない**（R2 は 50 races の近似補正にすぎない）

### 成果物（R3 完了時）

1. `ml/src/scripts/run_market_efficiency.py` 拡張:
   - `POS_IN_RANGE_R2 = 0.245` 定数追加
   - `bin_summary_place` / `bootstrap_lift_ci_place` / `evaluate_place_distortion` を補正後 ev 対応
2. 12 ヶ月集計の実行結果:
   - `artifacts/market_efficiency_2025-05_2026-04_place.csv`（補正後 ev 列含む）
   - `artifacts/market_efficiency_2025-05_2026-04_place.png`
3. segment 分析の実行結果:
   - `artifacts/market_efficiency_segment_stadium_focus_*_2025-05_2026-04_place.csv`
   - `artifacts/market_efficiency_segment_stadiumXodds_band_focus_*_2025-05_2026-04_place.csv`
4. `MARKET_EFFICIENCY_PLACE_RESULTS.md` §13「R3 集計結果」§14「R3 採用判定」追記
5. 撤退時: `CLAUDE.md` / `AUTO_LOOP_PLAN.md` / memory 更新、`NEXT_SESSION_PROMPT_C_R1.md` 次候補プロンプト整備
6. 採用時: 12 ヶ月本番 payout DL 提案（実装は別セッション）

### 実行環境

- Python 3.12（`py -3.12`）
- ローカル（Windows）、DB 接続不要
- 必要キャッシュ: `data/history/` + `data/program/` + `data/odds/place_odds_2025{05..12}.parquet` + `data/odds/place_odds_2026{01..04}.parquet` + `artifacts/place_payouts_sample_2025-12.parquet`
- 想定実行時間: 実装 1-2h + 集計 1-2 分 + segment 1-2 分（bootstrap 込み） + レポート作成 30 分

### 参照すべきドキュメント

- [MARKET_EFFICIENCY_PLACE_RESULTS.md](MARKET_EFFICIENCY_PLACE_RESULTS.md) §9-§12 — **本タスクの直接の起点（必読）**
- [MARKET_EFFICIENCY_WIN_RESULTS.md](MARKET_EFFICIENCY_WIN_RESULTS.md) §6-§7 — B-3 win 撤退結果
- [NEXT_PHASE_B3_PLAN.md](NEXT_PHASE_B3_PLAN.md) — B-3 全体計画
- [MARKET_EFFICIENCY_RESULTS.md](MARKET_EFFICIENCY_RESULTS.md) — B-1 trifecta 集計、流儀参照
- [MARKET_EFFICIENCY_SEGMENT_RESULTS.md](MARKET_EFFICIENCY_SEGMENT_RESULTS.md) — B-1 segment 結果、Step 3 準備
- [CLAUDE.md](CLAUDE.md) — 「現行の運用方針」「現在の仕様」
- [BET_RULE_REVIEW_202509_202512.md](BET_RULE_REVIEW_202509_202512.md) — 実運用再開条件
- [ml/src/scripts/run_market_efficiency.py](ml/src/scripts/run_market_efficiency.py) — 拡張対象
- [ml/src/collector/openapi_client.py](ml/src/collector/openapi_client.py) — `fetch_place_payouts` 実装済み
- [ml/src/scripts/sample_place_payouts.py](ml/src/scripts/sample_place_payouts.py) — R2 再現用

### A 完了後の関連プロンプト（参考）

| 次タスク | プロンプト | 前提 |
|---|---|---|
| **C**: 2 連単 / 2 連複 / 拡連複 DL 関数の実装 | [NEXT_SESSION_PROMPT_C.md](NEXT_SESSION_PROMPT_C.md) | A R3 完了後 |

以上。**着手前合意ポイント 1〜7 をユーザー合意してから実装に入ってほしい**。
