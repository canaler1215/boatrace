# trials/ — モデル構造自律改善ループの trial 置き場

MODEL_LOOP_PLAN.md §3-1 に従ったディレクトリ。

## 構成

```
trials/
  pending/       これから実行する trial YAML を置く
  completed/     run_model_loop.py が成功後に自動で移動
  results.jsonl  1 trial 1 行の実行結果（append-only）
  README.md      本ファイル
```

## 使い方

1. `pending/` に trial YAML（例: `T01_window_2024.yaml`）を置く
2. `python ml/src/scripts/run_model_loop.py` を実行
3. 成功した trial は `completed/` へ自動移動、`results.jsonl` に 1 行追記される
4. 失敗した trial は `pending/` に残り、`artifacts/model_loop_<trial_id>_error.log` にトレースが保存される

特定 trial のみ実行する場合:

```bash
python ml/src/scripts/run_model_loop.py --trial T01_window_2024
```

## YAML スキーマ

必須キー（MODEL_LOOP_PLAN.md §3-2 準拠）:

- `trial_id` (str)
- `walkforward.start`, `walkforward.end` (str, "YYYY-MM")
- `strategy.prob_threshold`, `strategy.ev_threshold`, `strategy.bet_amount`

任意キー（省略時は既定値）:

- `description`, `hypothesis`
- `training.train_start_year` / `train_start_month`（既定: 2023/1）
- `training.sample_weight` `{mode: "recency"|"exp_decay", ...}`
- `training.num_boost_round`, `training.early_stopping_rounds`
- `lgb_params` (dict) — `LGB_PARAMS` にマージされる
- `walkforward.retrain_interval` (int, 既定: 1)
- `walkforward.real_odds` (bool, 既定: true)
- `strategy.max_bets`, `min_odds`, `exclude_courses`, `exclude_stadiums`, `bet_type`

## 生成される artifacts

1 trial の実行で以下が `artifacts/` に保存される:

- `walkforward_<trial_id>.csv` — Walk-Forward の raw 結果
- `walkforward_<trial_id>_summary.json` — KPI + primary_score + verdict + monthly_roi
- `model_loop_<trial_id>_<YYYYMM>.pkl` — retrain したモデルの trial 固有コピー
  （本番設定では 1 trial あたり 4 ファイル、8 trial で約 1.6GB）
- `model_loop_<trial_id>_error.log` — エラー時の traceback（成功時は作られない）

### trial 固有モデルの用途

共有ファイル `model_<train_end>_from<train_start>_wf.pkl` は同じ `train_start` を使う
別 trial の retrain で上書きされるため、trial 完了後は最後に実行した trial の内容に
なってしまう。`model_loop_<trial_id>_<YYYYMM>.pkl` は上書きされない永続コピー。

`/trial-design` 等で過去 trial のモデルを再参照したい場合はこちらを使う。
検証完了後は不要な trial のファイルを削除して良い（例: `rm artifacts/model_loop_T04_*.pkl`）。

## results.jsonl の見方

- `status`: "success" | "error"
- `kpi.roi_total`: 期間通算 ROI(%)
- `kpi.worst_month_roi`: 最悪月 ROI(%)
- `kpi.broken_months`: 月次 ROI < -50% の月数（2026-04-24 追加）
- `kpi.cvar20_month_roi`: 下位 20% 月次 ROI 平均（2026-04-24 追加）
- `kpi.roi_ci_low_90` / `roi_ci_high_90`: 通算 ROI の block bootstrap 90% CI（2026-04-24 追加）
- `kpi.plus_month_ratio`: プラス月の比率（0〜1）
- `primary_score`: `roi_total + 0.5 * cvar20 - 10 * broken_months`（2026-04-24 改訂、高いほど良い）
- `verdict`: `pass`（合格）/ `marginal`（ROI≥0 だが pass 条件未達）/ `fail`
  - pass 条件: `roi≥+10% AND broken_months==0 AND plus_ratio≥0.60 AND roi_ci_low_90≥0`

詳細は [MODEL_LOOP_PLAN.md](../MODEL_LOOP_PLAN.md) §3-4 / §3-5 を参照。

## 現在の pending trials（2026-04-24 改訂）

| trial_id | 変更軸 |
|---|---|
| T00_baseline | trainer 既定（比較基準） |
| T01_window_2024 | train_start_year=2024 |
| T02_window_2025 | train_start_year=2025 |
| T03_sample_weight_recency | recency 12ヶ月 × 3.0 |
| T04_lgbm_regularized | num_leaves=31 / min_child_samples=200（木の複雑度↓）|
| T05_lgbm_conservative_lr | lr=0.02 / num_boost_round=2000 |
| T06_feature_subsample | feature_fraction=0.5 / bagging_fraction=0.6（木間ランダム性↑、2026-04-24 差し替え）|
| T07_window_2024_plus_weight | T01 + recency 6ヶ月 × 2.0 |
| T08_baseline_seed1 | T00 と同一 + `lgb_params.seed=1`（trial 内ばらつき測定、Nice 1）|
| T09_baseline_seed2 | T00 と同一 + `lgb_params.seed=2`（同上）|

**差し替え履歴**:
- 旧 T06_early_stop_tight（`early_stopping_rounds=30`）は T04 と同方向のキャパシティ減で
  独立軸として弱いとの相互レビュー指摘（2026-04-24）を受けて T06_feature_subsample に差し替え。
