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
- `kpi.plus_month_ratio`: プラス月の比率（0〜1）
- `primary_score`: ROI - `max(0, -50 - worst) * 2`（高いほど良い）
- `verdict`: `pass`（合格）/ `marginal`（ROI≥0 だが月次安定性不足）/ `fail`

詳細は [MODEL_LOOP_PLAN.md](../MODEL_LOOP_PLAN.md) を参照。
