# MODEL_LOOP_RESULTS — 本番 10 trial 実行結果

最終更新: 2026-04-25
対象: `trials/pending/T00〜T09`（[MODEL_LOOP_PLAN.md §4 タスク 4](MODEL_LOOP_PLAN.md) 準拠、2026-04-24 改訂版）

## 実行条件

- Walk-Forward: 2025-05 〜 2026-04（12 ヶ月）、`retrain_interval=3`、`real_odds=true`
- `strategy` 全 trial 統一: `prob_threshold=0.07`, `ev_threshold=2.0`, `min_odds=100.0`,
  `exclude_stadiums=[2,3,4,9,11,14,16,17,21,23]`, `bet_amount=100`, `max_bets=5`, `bet_type=trifecta`
- 実行場所: ローカル（Windows / Python 3.12）
- 実行方法: `py -3.12 ml/src/scripts/run_model_loop.py`
- エラー: 0（全 10 trial `status=success`）
- primary_score 定義: `roi_total + 0.5 * cvar20_month_roi - 10 * broken_months`（[MODEL_LOOP_PLAN §3-4](MODEL_LOOP_PLAN.md)）
- verdict 判定: `pass` = ROI≥+10% かつ broken=0 かつ plus_ratio≥0.60 かつ CI 下限 ≥ 0（同 §3-5）

## 結果テーブル（primary_score 降順）

| trial_id | verdict | primary_score | ROI | worst_month | plus_ratio | broken | CI 下限 (90%) | CI 上限 (90%) | ECE(cal) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **T07_window_2024_plus_weight** | **pass** | **+1.59** | **+15.30%** | **-35.16%** | **66.7%** | **0** | **+1.94** | +28.94 | 0.00121 |
| T09_baseline_seed2 | marginal | -9.10 | +2.51% | -36.17% | 50.0% | 0 | -6.16 | +11.61 | 0.00132 |
| T00_baseline | fail | -24.96 | -6.64% | -43.17% | 50.0% | 0 | -13.34 | +2.63 | 0.00164 |
| T03_sample_weight_recency | fail | -32.00 | -2.03% | -54.77% | 41.7% | 1 | -12.71 | +7.05 | 0.00115 |
| T06_feature_subsample | fail | -34.95 | -1.17% | -61.30% | 41.7% | 1 | -12.18 | +11.30 | 0.00113 |
| T01_window_2024 | marginal | -37.59 | +8.58% | -61.28% | 58.3% | 2 | -3.64 | +19.47 | 0.00162 |
| T08_baseline_seed1 | fail | -43.62 | -6.80% | -62.52% | 41.7% | 1 | -28.03 | +14.94 | 0.00107 |
| T04_lgbm_regularized | fail | -49.15 | -12.91% | -66.05% | 41.7% | 1 | -31.70 | +6.86 | 0.00118 |
| T02_window_2025 | fail | -58.22 | -12.71% | -53.08% | 33.3% | 2 | -27.87 | +1.57 | 0.00146 |
| T05_lgbm_conservative_lr | fail | -65.80 | -1.79% | -81.65% | 50.0% | 3 | -20.40 | +18.61 | 0.00111 |

## 主要所見

### 1. T07 のみ verdict=pass（ただし seed ガチャの可能性）

T07_window_2024_plus_weight は CLAUDE.md の実運用再開条件（通算 ROI ≥ +10% かつ最悪月 > -50%）を
満たす唯一の trial。設計 §3-5 の pass 4 条件（ROI / broken / plus_ratio / CI 下限）をすべて通過。

ただし seed 感度が想像以上に大きく（下記 §2）、単独の pass だけで本採用は判断できない。
設計書 §5 に従い、近傍 2〜3 本で確証を取る必要がある。

### 2. seed 変動が極めて大きい（T00 / T08 / T09 の比較）

同設定で `lgb_params.seed` のみ変えた 3 本の分散:

| trial | seed | ROI | worst | plus_ratio | broken | verdict |
|---|---|---:|---:|---:|---:|---|
| T00_baseline | デフォルト | -6.64% | -43.17% | 50.0% | 0 | fail |
| T08_baseline_seed1 | 1 | -6.80% | -62.52% | 41.7% | 1 | fail |
| T09_baseline_seed2 | 2 | +2.51% | -36.17% | 50.0% | 0 | marginal |

統計:
- ROI: mean -3.64%, std 5.33pp, **range 9.31pp**
- worst: mean -47.29%, std 13.65pp, **range 26.35pp**

seed だけで verdict が fail/marginal を行き来するレベルの揺れがあり、T07 の ROI +15.30% も
seed 由来の偶発で +6pp 程度は乗っている可能性がある。

### 3. 窓 2024〜 + 直近 6mo×2 重みの複合効果

- T01（窓 2024〜 単独）: ROI +8.58% だが broken=2, worst -61.28%（裾リスク大）
- T07（T01 + 直近 6mo×2 倍重み）: ROI +15.30%, broken=0, worst -35.16%（裾リスク抑制）

**窓短縮は ROI を押し上げるが裾リスクを増やす傾向** が T01 で確認され、T07 で直近強調を
追加すると両方改善した（ROI +6.7pp, worst +26.1pp）。seed ガチャを排除できれば、
この複合効果は仮説として有望。

### 4. 破局設定の確認

- T02_window_2025（窓 2025〜 のみ）: 学習データ不足で過学習、ROI -12.71%
- T04_lgbm_regularized（容量絞り）: 識別能力低下、ROI -12.91%, worst -66.05%
- T05_lgbm_conservative_lr（低 lr × 多 boost）: 破局月製造機、broken=3, worst -81.65%

これら 3 本は「本データセットで避けるべき方向」として記録しておく。

### 5. ECE（calibrated）の trial 間差は小さい

全 trial で 0.001〜0.0016 のレンジ。予測信頼性そのものは trial 間で大差なく、
ROI 差は「どこを賭けるか（フィルタ統一）下でモデルが拾う月次レジーム」に集約される。

## 次アクション（タスク 6-9）

T07 を確証するため、以下 3 本を `trials/pending/` に追加して `/model-loop` を再実行する:

| trial_id | 変更点 | 検証目的 |
|---|---|---|
| T10_window_2024_weight_seed1 | T07 と同設定 + `lgb_params.seed=1` | T07 pass が seed 由来か検証 |
| T11_window_2024_weight_seed2 | T07 と同設定 + `lgb_params.seed=2` | 同上、もう 1 本 |
| T12_window_2024_weight_strong | T07 ベースで `recency_months=3, recency_weight=3.0` | 直近強調の感度（さらに攻める方向） |

判定:
- **T10/T11 の 2/2 または 1/2 が verdict=pass** → T07 本採用候補として構造確定、近傍探索継続
- **T10/T11 の 0/2 が pass** → T07 は seed ガチャ確定、構造変更フェーズへ移行
- **T12 が T07 超え** → 直近強調はもう 1 段攻めてよい方向として追加探索

## 成果物

- `trials/results.jsonl` — 10 行（trial ごとに 1 行 append）
- `artifacts/walkforward_T*_summary.json` — 10 ファイル（KPI + monthly_roi）
- `artifacts/walkforward_T*.csv` — 10 ファイル（raw Walk-Forward 出力）
- `artifacts/model_loop_logs/run_*.log` — 実行ログ
- `trials/completed/T00〜T09.yaml` — 使用済み trial 定義

## 参考

- 設計書: [MODEL_LOOP_PLAN.md](MODEL_LOOP_PLAN.md)
- スラッシュコマンド: [.claude/commands/model-loop.md](.claude/commands/model-loop.md)
- 運用基準: [CLAUDE.md](CLAUDE.md)「現行の運用方針（2026-04-24 時点）」
- 背景: [BET_RULE_REVIEW_202509_202512.md](BET_RULE_REVIEW_202509_202512.md) §30-32
