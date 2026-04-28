# 次セッション用プロンプト — フェーズ B-3 拡張 A Step 2 集計: `run_market_efficiency.py --bet-type place` 拡張（着手前合意フェーズ）

以下を新セッションの最初のユーザープロンプトとして貼り付けてください。

---

## プロンプト本文

boatrace プロジェクトのフェーズ B-3「馬券種転換による市場効率分析」の **拡張 A Step 2 集計フェーズ（複勝 / place）** に着手してほしい。

### 前提（重要）

- **拡張 A Step 1 完了済み**（2026-04-27）: 複勝オッズ DL 関数 (`fetch_place_odds` / `load_or_download_month_place_odds`) 実装 + 試行 DL（2025-12）成功
- **12 ヶ月本番 DL 完了済み**（2026-04-28 01:23）: 2025-05〜2026-04 で **54,277 races / 12 ヶ月 / 0 empty / 0 partial 残存**（12.9 時間、エラーなし）。単勝側で見られた江戸川 12-09 集中の empty 22 件は複勝では再現せず、より安定して取得
- **B-3 win 撤退確定済み**（2026-04-27）: 単勝で採用基準達成 0 / 24 stadium、最善 ev_all_buy=0.964 で控除率 20% を破れず
- 本セッションでは **`run_market_efficiency.py` に `--bet-type place` を追加し、12 ヶ月集計で lift / 実 ROI ベース `ev_all_buy` / bootstrap CI を計算、採用判定（Step 3 進行 or B-3 拡張 A 撤退）** まで完了させる

作業開始前に必ず以下を読むこと:

- `MARKET_EFFICIENCY_PLACE_RESULTS.md`（Step 1 結果 + 12 ヶ月 DL 結果、複勝 overround の構造的特殊性 / range 表記 / 5 サンプル中 1 件の win-place 不整合観察等）
- `MARKET_EFFICIENCY_WIN_RESULTS.md`（B-3 win 撤退結果。**実 ROI vs `ev_all_buy = mean(odds × hit)` の上方バイアス +20〜39pp** 観察、Step 2 で同じ過ちを避けるため必読）
- `NEXT_PHASE_B3_PLAN.md` §1 券種別控除率表
- `MARKET_EFFICIENCY_RESULTS.md`（B-1 trifecta 集計結果、流儀の参照元）
- `MARKET_EFFICIENCY_SEGMENT_RESULTS.md`（B-1 segment 結果、Step 3 流儀の参照元）
- `ml/src/scripts/run_market_efficiency.py`（trifecta + win 用の現行実装、`--bet-type place` 拡張対象）
- `ml/src/collector/openapi_client.py`（`fetch_place_odds`、`fetch_race_result_full` 含む）
- `ml/src/collector/odds_downloader.py`（`load_or_download_month_place_odds` 含む、Step 1 で追加済み）
- `CLAUDE.md`「現在の仕様」「現行の運用方針」（B-3 拡張 A Step 1 + 12 ヶ月 DL 完了状態）
- `BET_RULE_REVIEW_202509_202512.md` §28-32（実運用再開条件）

### これまでの経緯（要約）

| フェーズ | 内容 | 結果 |
|---|---|---|
| 3 `/inner-loop` | 購入フィルタ探索 | 凍結 |
| 6 `/model-loop` | モデル構造改善 | 完全撤退 |
| 7 (B-1) | 3 連単市場効率分析（控除率 25%） | 完全撤退（最高 ev=0.98 / 蒲郡 × 1 コース） |
| **B-3 win** | 単勝市場効率分析（控除率 20% 理論） | **完全撤退**（最大 lift 1.094、最善 ev_all_buy=0.964 / 福岡） |
| **B-3 拡張 A** Step 1 | 複勝オッズ DL 関数 + 試行 DL | 完了（2026-04-27） |
| **B-3 拡張 A** 12 ヶ月 DL | 2025-05〜2026-04 複勝 12 ヶ月分 | 完了（54,277 races / 0 empty） |
| **B-3 拡張 A Step 2 集計**（本タスク）| **`--bet-type place` 拡張 + 12 ヶ月集計 + 採用判定** | **着手予定** |

### B-3 win 撤退から得た構造的知見（拡張 A Step 2 に反映）

1. **理論控除率と実勢 overround は乖離する** — win 単勝の理論控除率 20% に対し、実勢 overround 1.36（実控除率 26%）。複勝でも別の構造的バイアスが存在する見込み
2. **`ev_all_buy = mean_odds × mean_hit` は実 ROI と乖離**（オッズ幅広い帯で +20〜39pp の上方バイアス、Cov(odds, hit) < 0 のため）。**Step 2 集計時は sum-aggregated 実 ROI を主指標とし、`ev_all_buy` は補助観察**
3. **歪みの振幅は券種シンプル化で減る**（trifecta max lift 1.27 → win 1.094）。複勝はさらに「3 着以内」で hit 確率高 → 歪み振幅はさらに小さい可能性
4. **複勝はオッズが範囲表記**（`(odds_low, odds_high)`）。実 ROI 計算時の odds 確定の仕方に注意（最低オッズで保守的に評価するか中点で評価するか実払戻で評価するか）

### 開始前のチェック（必ず実行）

```bash
ls data/odds/place_odds_*.parquet | wc -l   # 12 を期待
```

12 ファイル揃っていない場合は DL 完了状態を再確認（ヘルパー: `load_or_download_month_place_odds(year, month, race_df)` を呼べば未取得月のみ DL）。

### Step 2 集計で行うこと（最小スコープ）

1. `run_market_efficiency.py` に `--bet-type place` 追加（trifecta / win 既存挙動はデフォルトで維持）
2. 複勝の implied probability 計算（odds 評価モード 3 通り併記、合意点 2 参照）
3. 複勝のヒット判定（**艇 i が finish_position ∈ {1, 2, 3} なら hit** — 1 レースに 3 hit を許容）
4. ビニング（合意点 1 参照）
5. **実 payout 取得方法の決定**（合意点 3 参照） — B-3 win 教訓を踏まえ、`mean(odds × hit)` でなく **sum-aggregated 実 ROI** を主指標とする
6. 既存 segment 分析（B-1 / win で実装済み）の place 対応
7. bootstrap 90% CI（n_resamples=2000、レース単位 stratify）
8. 12 ヶ月集計を実行 → 採用判定 → 結果ドキュメントに追記

### 着手前合意ポイント（実装前にユーザー確認）

以下の設計判断について合意を取ってから着手する:

1. **ビニング方式**:
   - 複勝の implied prob 範囲は単勝より狭い（mid ベース 0.10〜0.80 想定、人気艇は 0.6+ に集中）
   - (a) 等幅 10 ビン `[0, 0.1, 0.2, ..., 1.0)` — win / trifecta と統一
   - (b) 等密度 quantile（10 ビン）— サンプル数が均等
   - (c) 複勝特化の等幅 8 ビン `[0, 0.1, 0.2, ..., 0.8)` — 0.8 以上は稀
   - 推奨: **(a) 等幅 10 ビン**（win との比較容易性優先）

2. **odds 評価モード**（複勝特有、最重要設計判断）:
   - 複勝オッズは `(odds_low, odds_high)` の range 表記
   - (a) **保守的評価 = `odds_low` 採用**（最低保証払戻、bet 主に最も厳しい）
   - (b) **中点評価 = `odds_mid = (low+high)/2` 採用**（期待値ベース）
   - (c) **楽観評価 = `odds_high` 採用**（最高払戻、bet 主に最も有利）
   - (d) 全 3 モードで集計、CSV に併記
   - 推奨: **(d) 全 3 モード併記、判定は (a) 保守的評価ベース**（控除率 20% を確実に破ると主張するための保守的根拠）

3. **実 payout 取得方法**（実 ROI 計算の根幹）:
   - (a) `raceresult` ページから複勝実払戻金を取得 — `fetch_race_result_full` の拡張が必要（複勝 3 艇分の payout 取得）
   - (b) `odds_low` / `odds_mid` / `odds_high` 近似 × hit で payout 推定 — 取得済みデータのみで完結
   - (c) (a) を主、(b) で sanity check
   - 推奨: **(b) 近似ベースで開始**、Step 3 で必要に応じて (a) 実払戻取得を検討
   - 理由: B-3 win では実払戻取得を行わずとも Step 2 段階で撤退判定がついた。複勝も Step 2 で「lift / ev_all_buy_low / ev_all_buy_mid / ev_all_buy_high が控除率 20% を破るか」を確認するだけで判定可能

4. **ヒット判定**:
   - 単純な「3 着以内に入れば hit」（K ファイル `finish_position ∈ {1, 2, 3}`）
   - **1 レースに 3 hit を許容する集計設計**（sum-to-1 前提は使えない）
   - 各 bet（艇 × レース）を独立イベントとして集計、レース単位 stratify は bootstrap でも維持
   - 推奨: 上記
   - 補足: 通常の市場効率分析は「prob_implied 帯ごとの実勝率」を見る → 単勝の sum_to_1 前提なしでも成立

5. **採用基準**（控除率 20% 破壊閾値）:
   - 複勝の理論控除率 20% → 単純な lift 閾値 ≥ 1.25 が黒字化必要条件
   - **ただし複勝オッズの実勢 payout 構造は range のため、`ev_all_buy_<mode> > 1.0` を主指標**
   - Step 2 合格条件案:
     - 「ある暗黙確率帯（n ≥ 1,000）で `ev_all_buy_low > 1.0` 」（保守的評価で黒字成立）
     - 「90% bootstrap CI 下限 > 1.0」
     - 「前半 6 ヶ月 / 後半 6 ヶ月で同方向」
   - 推奨: 上記、ただし `ev_all_buy_mid > 1.05` も補助合格基準とする（保守は厳しすぎる場合）

6. **segment 分析の対象**:
   - 全期間ビン（10 等幅）
   - 場別（24 場、6 艇全揃いレースのみ）
   - 場 × 暗黙確率帯（B-1 / win と同じ）
   - 推奨: 上記 3 軸、コース別は単勝同様除外（艇番 = combination キー）

7. **出力ファイル名規約**:
   - `artifacts/market_efficiency_2025-05_2026-04_place.csv`
   - `artifacts/market_efficiency_2025-05_2026-04_place.png`
   - `artifacts/market_efficiency_segment_stadium_focus_<focus_band>_2025-05_2026-04_place.csv`
   - 推奨: 上記、`_trifecta.csv` / `_win.csv` と並列の命名

8. **欠場レースの扱い**:
   - 6 艇全揃い（93.5%、12 ヶ月で約 50,750 レース）のみ集計対象
   - 艇数 5 / 4 / 3（6.5%、約 3,500 レース）は除外
   - 推奨: 上記

9. **win-place 不整合（5 サンプル中 1 件 = 20%）の扱い**:
   - Step 1 で観察: 桐生 1R 等で boat 1 win=1.7 vs place=2.4-3.1（mathematically inconsistent）
   - 出場辞退 / 表示ラグの可能性
   - (a) Step 2 では特別扱いせず、生 odds で集計（バイアスは hit_rate に吸収される）
   - (b) 不整合レース（win prob > place prob_max）は事前 filter で除外
   - 推奨: **(a)** — bias は集計上自然に吸収される。Step 3 でサブセグメント検出されたら詳細追究

これらが合意できたら拡張 A Step 2 集計を実装する。

### 拡張 A Step 2 集計の終了条件

- `run_market_efficiency.py --bet-type place --start 2025-05 --end 2026-04` がエラーなく完走
- `artifacts/market_efficiency_2025-05_2026-04_place.csv` 出力（odds 評価モード 3 通り併記）
- 採用判定（lift / `ev_all_buy_<low|mid|high>` / bootstrap CI）の集計レポートが `MARKET_EFFICIENCY_PLACE_RESULTS.md` に追記され、Step 3 進行 / B-3 拡張 A 撤退の判定がつく

### 拡張 A Step 2 集計の判定

- **Step 2 合格** → Step 3（サブセグメント分析）に進む
- **Step 2 不合格**（全 implied_p 帯にわたり lift が 0.95〜1.05、ev_all_buy が 1.0 を超えない）→ **B-3 拡張 A 撤退**

### 厳守事項

- ❌ 既存モデル（trainer.py / predictor.py / engine.py）は触らない
- ❌ Step 4 のバックテスト前に Step 2-3 の歪み確認を完了する（フェーズ 6 + B-1 + B-3 win の教訓）
- ❌ 着手前合意ポイント（上記 1〜9）を**スキップしない**
- ❌ 既存 trifecta / win の集計コードを破壊しない（`--bet-type {trifecta,win,place}` の互換は維持）
- ❌ 既存出力ファイル `artifacts/market_efficiency_*_trifecta.*` / `artifacts/market_efficiency_*_win.*` を上書きしない
- ❌ B-3 win で確認した `ev_all_buy = mean(odds × hit)` の上方バイアスを忘れない — **sum-aggregated 実 ROI 主指標**

### 成果物（拡張 A Step 2 集計完了時）

1. `ml/src/scripts/run_market_efficiency.py` に `--bet-type place` 拡張（trifecta / win 既存挙動を維持）
2. 複勝集計用の helper 関数追加（implied probability 計算 × 3 モード、ヒット判定 multi-hit、ビニング）
3. 12 ヶ月集計の実行結果:
   - `artifacts/market_efficiency_2025-05_2026-04_place.csv`
   - `artifacts/market_efficiency_2025-05_2026-04_place.png`
4. segment 分析の実行結果:
   - `artifacts/market_efficiency_segment_stadium_focus_*_2025-05_2026-04_place.csv`
   - `artifacts/market_efficiency_segment_stadiumXodds_band_focus_*_2025-05_2026-04_place.csv`
5. `MARKET_EFFICIENCY_PLACE_RESULTS.md` に「§6 Step 2 集計結果」「§7 Step 2 判定」を追記
6. `AUTO_LOOP_PLAN.md` フェーズ 8 拡張 A の Step 2 集計状態更新

### 実行環境

- Python 3.12（`py -3.12`）
- ローカル（Windows）、DB 接続不要
- 必要キャッシュ: `data/history/` + `data/program/` + `data/odds/place_odds_2025{05..12}.parquet` + `data/odds/place_odds_2026{01..04}.parquet`
- 想定実行時間: 集計 1〜2 分（B-1 trifecta / win と同等）+ 実装 4〜6 時間 + レポート作成 30 分

### 参照すべきドキュメント

- [MARKET_EFFICIENCY_PLACE_RESULTS.md](MARKET_EFFICIENCY_PLACE_RESULTS.md) — Step 1 結果 + 12 ヶ月 DL 結果、本タスクの起点
- [MARKET_EFFICIENCY_WIN_RESULTS.md](MARKET_EFFICIENCY_WIN_RESULTS.md) — B-3 win 撤退結果、`ev_all_buy` 上方バイアスの観察
- [NEXT_PHASE_B3_PLAN.md](NEXT_PHASE_B3_PLAN.md) — B-3 全体計画
- [MARKET_EFFICIENCY_RESULTS.md](MARKET_EFFICIENCY_RESULTS.md) — B-1 trifecta 集計、流儀参照
- [MARKET_EFFICIENCY_SEGMENT_RESULTS.md](MARKET_EFFICIENCY_SEGMENT_RESULTS.md) — B-1 segment 結果、Step 3 準備
- [CLAUDE.md](CLAUDE.md) — 「現行の運用方針」「現在の仕様」
- [BET_RULE_REVIEW_202509_202512.md](BET_RULE_REVIEW_202509_202512.md) — 実運用再開条件
- [ml/src/scripts/run_market_efficiency.py](ml/src/scripts/run_market_efficiency.py) — 拡張対象
- [ml/src/collector/odds_downloader.py](ml/src/collector/odds_downloader.py) — `load_or_download_month_place_odds`
- [ml/src/collector/openapi_client.py](ml/src/collector/openapi_client.py) — `fetch_place_odds` / `fetch_race_result_full`

### A 完了後の関連プロンプト（参考）

| 次タスク | プロンプト | 前提 |
|---|---|---|
| **C**: 2 連単 / 2 連複 / 拡連複 DL 関数の実装 | [NEXT_SESSION_PROMPT_C.md](NEXT_SESSION_PROMPT_C.md) | A Step 2 完了後 |

以上。**着手前合意ポイント 1〜9 をユーザー合意してから実装に入ってほしい**。
