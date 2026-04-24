# モデル構造自律改善ループ 実装計画（アプローチB）

本ドキュメントは**別セッションで実装するための設計書**である。
セッション開始時にこのファイルをまず読み、記載通りに実装を進めること。

最終更新: 2026-04-24
ステータス: **タスク1完了、タスク2以降 未着手**

---

## 1. 背景と目的

### 1-1. なぜこのループを作るのか

[BET_RULE_REVIEW_202509_202512.md](BET_RULE_REVIEW_202509_202512.md) §30-32 の結論:

- フィルタ探索（prob下限/上限、オッズ上限、コース除外、場除外）は **out-of-sample で黒字化できない**
- 12 ヶ月通算 ROI -13.4%、2026-01 (-79.5%) / 2026-04 (-65.4%) の破局月が発生
- 根本原因は**モデルの1着識別能力が全ビンでランダムに近い**（CLAUDE.md「重大発見」）
- よって**モデル再学習・再設計を優先**する必要がある

### 1-2. 既存 `/inner-loop` との違い

| 観点 | `/inner-loop`（既存） | `/model-loop`（本書） |
|---|---|---|
| 変更対象 | `ml/configs/strategy_default.yaml`（フィルタ 1 パラメータ） | 学習ハイパラ・学習窓・sample_weight |
| 実行場所 | GitHub Actions 強制 | ローカル |
| 1 trial の粒度 | フィルタ値のみ | モデル全体を再学習 |
| 1 trial の時間 | 数分〜数十分（GA） | 20〜40分（ローカル、3ヶ月再学習間隔） |
| 判定基準 | ROI 500% 基準（崩壊済み） | 通算ROI ≥ 0% + 最悪月 ≥ -50% + プラス月 ≥ 60% |

`/inner-loop` は**残して共存させる**。本ループは別系統として `/model-loop` を新設する。

### 1-3. ユーザーとの合意事項（2026-04-24）

- **実行場所**: ローカル（Windows / Python 3.12）
- **Walk-Forward 対象期間**: 2025-05〜2026-04（12 ヶ月）
- **再学習間隔**: 3 ヶ月ごと（初期値）
- **報告タイミング**: 全 trial 連続実行後にまとめて報告

---

## 2. 実行環境の前提

### 2-1. 使えるキャッシュ

実装時に以下が揃っていることを確認すること。揃っていなければダウンロードから始める必要があるが、
本計画書の期間（2025-05〜2026-04）については **既にダウンロード済み** である。

```
data/history/         K ファイル（競走成績）
data/program/         B ファイル（出走表）
data/odds/            実オッズ
ml/artifacts/backtest_01/  2025-05〜2026-03 の backtest CSV（参考、前回条件のもの）
ml/artifacts/backtest_02/  2026-04 の backtest CSV（参考）
```

### 2-2. Python 環境

- Python **3.12 必須**（pandas 2.2.3 のホイール都合、`SETUP.md` 参照）
- `pip install -r ml/requirements.txt` が済んでいること

### 2-3. DB 接続は不要

`run_backtest.py` / `run_walkforward.py` はファイルキャッシュだけで完結する。
`register_model_version` を通る `run_retrain.py` 経路は**使わない**（DB非依存）。

---

## 3. ループアーキテクチャ

### 3-1. ディレクトリ構成（新規作成）

```
trials/
  pending/        これから実行する trial の YAML（Claude がここに置く）
    T01_window_2024.yaml
    T02_window_2025.yaml
    ...
  completed/      実行済み trial（実行スクリプトが pending から移動する）
  results.jsonl   1 trial 1 行の実行結果（append-only）
  README.md       ディレクトリ構成の説明

ml/src/scripts/
  run_model_loop.py   ← 新規作成。trials/pending/ から 1 本取って実行するループ本体

artifacts/
  model_loop_<trial_id>.pkl          学習済みモデル
  walkforward_<trial_id>.csv         Walk-forward 結果 CSV
  walkforward_<trial_id>_summary.json   Summary（KPI + primary_score）

.claude/commands/
  model-loop.md   ← 新規作成。スラッシュコマンド手順書
```

### 3-2. 1 trial の YAML スキーマ

```yaml
# trials/pending/T01_window_2024.yaml
trial_id: T01_window_2024
description: "学習窓を 2024-01〜 に短縮（直近データ重視仮説の検証）"
hypothesis: |
  BET_RULE_REVIEW §32 候補 1。2023 年からの古いデータが直近の分布シフトを
  吸収しきれていない可能性があるため、2024-01〜 に短縮して検証する。

# ── 学習設定 ────────────────────────────────────
training:
  train_start_year: 2024
  train_start_month: 1
  # sample_weight 調整（省略時は均等）
  sample_weight:
    mode: null            # null / "recency" / "exp_decay"
    # recency の場合のパラメータ例:
    # recency_months: 12  直近12ヶ月を重み付け
    # recency_weight: 3.0 直近の重みを 3 倍

# ── LightGBM ハイパラ（省略時は trainer.py の LGB_PARAMS を使用）──
lgb_params:
  learning_rate: 0.05
  num_leaves: 63
  min_child_samples: 50
  feature_fraction: 0.8
  bagging_fraction: 0.8
  bagging_freq: 5
  num_boost_round: 1000
  early_stopping_rounds: 50

# ── Walk-Forward 設定 ──────────────────────────
walkforward:
  start: "2025-05"
  end: "2026-04"
  retrain_interval: 3     # 3 ヶ月ごとに再学習
  real_odds: true

# ── バックテスト時のフィルタ（比較統一のため固定推奨）─
# BET_RULE_REVIEW の案 A をベースに統一
strategy:
  prob_threshold: 0.07
  ev_threshold: 2.0
  min_odds: 100.0
  exclude_courses: []
  exclude_stadiums: [2, 3, 4, 9, 11, 14, 16, 17, 21, 23]
  bet_amount: 100
  max_bets: 5
  bet_type: trifecta
```

**重要**: `strategy` セクションは全 trial で**統一**すること。モデル側の変化による ROI 差を見たいので、
フィルタを trial ごとに変えると比較不能になる。

### 3-3. results.jsonl の行スキーマ

```json
{
  "trial_id": "T01_window_2024",
  "started_at": "2026-04-24T14:30:00+09:00",
  "finished_at": "2026-04-24T15:05:00+09:00",
  "duration_sec": 2100,
  "status": "success",
  "kpi": {
    "total_bets": 17600,
    "total_wagered": 1760000,
    "total_payout": 1957220,
    "wins": 62,
    "roi_total": 11.2,
    "worst_month_roi": -79.5,
    "best_month_roi": 104.0,
    "plus_months": 7,
    "total_months": 11,
    "plus_month_ratio": 0.636,
    "avg_hit_odds": 261.0,
    "hit_rate_per_bet": 0.0035,
    "ece_rank1_calibrated": 0.1337
  },
  "monthly_roi": {
    "2025-05": 44.7,
    "2025-06": 104.0,
    ...
  },
  "primary_score": -48.3,
  "verdict": "fail",
  "notes": "breakdown月が2026-01, 2026-04 で発生、改善なし"
}
```

### 3-4. primary_score の定義

```python
def primary_score(kpi: dict) -> float:
    """
    合計 ROI から、最悪月のペナルティを差し引いた複合スコア。
    高いほど良い。正で合格圏、負は不合格。

    worst_month_roi が -50% を下回るごとに、超過分の 2 倍をペナルティ。
    例: worst_month_roi = -79.5% → penalty = 2.0 * (79.5 - 50) = 59.0
    """
    roi = kpi["roi_total"]
    worst = kpi["worst_month_roi"]
    penalty = 2.0 * max(0.0, -50.0 - worst)   # worst < -50 のときだけ発動
    return roi - penalty
```

### 3-5. verdict 判定ルール

```python
def classify_verdict(kpi: dict) -> str:
    roi = kpi["roi_total"]
    worst = kpi["worst_month_roi"]
    plus_ratio = kpi["plus_month_ratio"]

    # 合格: 3 基準すべて満たす
    if roi >= 0 and worst >= -50 and plus_ratio >= 0.60:
        return "pass"
    # 準合格: ROI >= 0 だが月次安定性が不足
    if roi >= 0:
        return "marginal"
    return "fail"
```

---

## 4. 実装タスク

以下の順で実装すること。各タスクの完了定義を明記する。

### タスク 1: 学習側の config 対応（trainer.py の拡張）

**ファイル**: `ml/src/model/trainer.py`

現状の `train(X, y, version)` を拡張し、以下の新シグネチャに:

```python
def train(
    X: pd.DataFrame,
    y: pd.Series,
    version: str,
    *,
    lgb_params: dict | None = None,        # None なら LGB_PARAMS を使う
    num_boost_round: int = 1000,
    early_stopping_rounds: int = 50,
    sample_weight: np.ndarray | None = None,   # 学習サンプル重み
) -> Path:
```

- `lgb_params` は既存 `LGB_PARAMS` をベースに dict update でマージ
- `sample_weight` は `lgb.Dataset(..., weight=sample_weight)` に渡す
- 既存呼び出し（`run_retrain.py`, `run_walkforward.py` の既存 `train(X, y, version)`）は**壊さない**こと
  （引数を全部 keyword-only にすれば後方互換を保てる）

### タスク 2: Walk-Forward 側の config 対応

**ファイル**: `ml/src/scripts/run_walkforward.py`

`get_model_for_month` に trial config を渡せるよう拡張するか、別関数 `get_model_for_month_with_config` を新設。

- 学習窓 (`train_start_year`, `train_start_month`) は既に CLI 引数で対応済み、trial config から注入すればよい
- `sample_weight` の生成ロジックを追加:
  - `mode: "recency"` → 直近 N ヶ月の weight を R 倍（race_date ベース）
  - `mode: "exp_decay"` → `weight = exp(-k * (ref_date - race_date_months))`（必要なら追加）
- `lgb_params` / `num_boost_round` / `early_stopping_rounds` を `train()` に渡す

### タスク 3: ループランナー `run_model_loop.py`

**ファイル**: `ml/src/scripts/run_model_loop.py`（新規）

コマンド例:
```bash
# pending にあるすべての trial を順次実行
python ml/src/scripts/run_model_loop.py

# 特定の trial だけ実行
python ml/src/scripts/run_model_loop.py --trial T01_window_2024

# 並列は不要、1本ずつ直列で
```

処理フロー:

1. `trials/pending/*.yaml` を glob、ソートして順に取る
2. 各 trial について:
   - YAML 読み込み、スキーマ検証
   - `run_walkforward.py` のロジックをライブラリ呼び出し
     （`run_walkforward.py` の `main()` を関数化するか、内部関数を直接呼び出す）
   - 学習時のパラメータは trial config から注入
   - バックテスト時のフィルタは `strategy` セクションを使用
   - 終了後、CSV から KPI を算出
   - 1 着 ECE（calibrated）は val データでの学習時ログから拾う
     （trainer.py に ECE を返すフックを追加するか、学習中の print から parse する。
     実装難易度を下げるなら `train()` の戻り値を dict 化して ECE を含める）
3. results.jsonl に 1 行追記
4. trial YAML を `trials/pending/` → `trials/completed/` に移動
5. モデル `artifacts/model_loop_<trial_id>.pkl` と Walk-Forward CSV を保存

エラー処理:
- 1 trial が失敗しても、次の trial に進む（status="error" で記録）
- traceback は `artifacts/model_loop_<trial_id>_error.log` に保存

### タスク 4: 初期 trial seeds を作成

`trials/pending/` に以下 7 本の YAML を作成:

| trial_id | 変更点 |
|---|---|
| T01_window_2024 | train_start_year=2024 |
| T02_window_2025 | train_start_year=2025 |
| T03_sample_weight_recency | train_start=2023, sample_weight mode=recency, recency_months=12, recency_weight=3.0 |
| T04_lgbm_regularized | num_leaves=31, min_child_samples=200 |
| T05_lgbm_conservative_lr | learning_rate=0.02, num_boost_round=2000 |
| T06_early_stop_tight | early_stopping_rounds=30 |
| T07_window_2024_plus_weight | train_start_year=2024 + sample_weight recency_months=6 recency_weight=2.0 |

`strategy` セクションは全 trial で統一（案 A ベース、下記）:

```yaml
strategy:
  prob_threshold: 0.07
  ev_threshold: 2.0
  min_odds: 100.0
  exclude_courses: []
  exclude_stadiums: [2, 3, 4, 9, 11, 14, 16, 17, 21, 23]
  bet_amount: 100
  max_bets: 5
  bet_type: trifecta
```

**baseline trial（T00）**: 現行 trainer.py のまま（train_start=2023, LGB_PARAMS デフォルト）で
Walk-Forward を 1 本実行し、results.jsonl の先頭行にする。他 trial の比較基準。

### タスク 5: スラッシュコマンド `/model-loop`

**ファイル**: `.claude/commands/model-loop.md`（新規）

argument-hint: `[trial_id | all]`

処理:
1. `trials/pending/` に YAML があるか確認
2. なければ「次の trial 候補を設計する」フェーズへ（Claude が results.jsonl を分析 → 新 YAML 作成）
3. あれば `python ml/src/scripts/run_model_loop.py` を実行
4. 完了後、results.jsonl の最新行をテーブル形式でユーザーに報告
5. **連続実行が合意事項**なので、途中報告は最小限。全 trial 完了後にまとめて報告する

### タスク 6: ドキュメント更新

- `CLAUDE.md` に「モデル構造ループ（/model-loop）」セクションを追加
  - `/inner-loop` はフィルタ調整、`/model-loop` は学習側、と用途を明示
- `AUTO_LOOP_PLAN.md` に「フェーズ 6: モデル構造ループ」を追記（進捗管理用）
- `trials/README.md` を作成（ディレクトリの使い方）

---

## 5. 探索戦略（Claude の判断ルール）

初期 7 trial 完了後、Claude は以下のルールで次の trial を設計:

1. results.jsonl を読み、primary_score でソート
2. 上位 trial のパラメータ近傍を探る（例: T01 が良ければ T01b として train_start_year=2024_06 など）
3. 下位 trial の方向は避ける
4. **5 trial 連続で primary_score が baseline 比 非改善** → 構造変更（LambdaRank 等）を提案して停止
5. 合格（verdict=pass）trial が出たら即報告、以降は確証のため近傍を 2〜3 本追加して打ち止め

撤退条件:
- 10 trial 回しても verdict=pass が 0 本 → モデル構造変更フェーズに進む提案をユーザーに出す

---

## 6. 留意事項

### 6-1. 実行時間の見積もり

- 1 trial: 学習 (3 回 × 〜3 分) + Walk-Forward (12 ヶ月 × 〜1 分) = **15〜25 分**
- 7 trial: **2〜3 時間**
- 連続実行なので夜間回しが現実的

### 6-2. ディスク容量

- モデル 1 本 ~50MB × 7 trial = 350MB
- CSV は数 MB
- 古い trial の `.pkl` は定期的に削除してよい（`artifacts/model_loop_*.pkl`）

### 6-3. 既知の落とし穴

1. **ECE 取得**: `trainer.py` の `print()` 文を parse するのではなく、`train()` の戻り値を dict 化して metrics を返す設計にすること
2. **モデル保存形式**: `{"booster": ..., "softmax_calibrators": [...]}` を維持（推論側の後方互換）
3. **sample_weight の生成**: `df_train` の `race_date` 列から計算すること。`feature_builder.py` の返り値（X, y）には日付が落ちている可能性があるので、
   `build_features_from_history` の呼び出し前後で日付配列を保持するよう工夫が必要。
4. **trainer.py の既存呼び出し互換**: `run_retrain.py` / 既存 `run_walkforward.py` は壊さない
5. **trials/ ディレクトリは `.gitignore` しない**: PR で履歴を残す運用

### 6-4. 変更禁止パス

以下は本ループの範囲外。触らないこと:

- `ml/src/collector/` — データ取得
- `ml/src/features/` — 特徴量（別タスク）
- `ml/migrations/`, `apps/` — DB スキーマ
- `.github/workflows/` — CI/CD

---

## 7. 実装順序のチェックリスト

別セッションで実装を進める際のチェックリスト:

- [ ] **7-1. baseline 実行可能性の確認**
  - `python ml/src/scripts/run_walkforward.py --start 2025-05 --end 2026-04 --retrain --retrain-interval 3 --real-odds --prob-threshold 0.07 --ev-threshold 2.0 --min-odds 100 --exclude-stadiums 2 3 4 9 11 14 16 17 21 23 --output artifacts/walkforward_baseline.csv`
  - エラーなく完走すること
  - 実行時間・ピークメモリを計測

- [ ] **7-2. trainer.py 拡張**（タスク 1）
  - 既存呼び出しを壊さないこと（`grep -rn "from model.trainer import train"` で確認）
  - 戻り値を `dict` 化して metrics（ECE 等）を返せるようにする

- [ ] **7-3. run_walkforward.py 拡張**（タスク 2）
  - trial config を受け取る API を追加
  - sample_weight 生成ロジックを実装

- [ ] **7-4. run_model_loop.py 作成**（タスク 3）
  - スキーマ検証、trial 実行、results.jsonl 追記、ファイル移動

- [ ] **7-5. 初期 7 trial seeds 作成**（タスク 4）
  - T00_baseline（現行）
  - T01〜T07

- [ ] **7-6. 動作確認: T00_baseline + T01 を実行**
  - results.jsonl に 2 行追記されること
  - primary_score 等が正しく計算されていること

- [ ] **7-7. スラッシュコマンド `/model-loop`**（タスク 5）
  - `.claude/commands/model-loop.md` を作成

- [ ] **7-8. ドキュメント更新**（タスク 6）
  - CLAUDE.md, AUTO_LOOP_PLAN.md, trials/README.md

- [ ] **7-9. 残 6 trial を連続実行**
  - `python ml/src/scripts/run_model_loop.py`（ALL モード）
  - 結果を `MODEL_LOOP_RESULTS.md`（新規）にまとめる

- [ ] **7-10. 次イテレーションの設計**
  - primary_score 上位 trial の近傍を 2〜3 本追加
  - 合格 trial が出るまで or 10 trial 到達まで継続

---

## 8. 参考資料

- **根拠ドキュメント**:
  - [BET_RULE_REVIEW_202509_202512.md](BET_RULE_REVIEW_202509_202512.md) — §30-32 でモデル側の課題を明記
  - [CLAUDE.md](CLAUDE.md) — 現行仕様、既知課題
  - [AUTO_LOOP_PLAN.md](AUTO_LOOP_PLAN.md) — 既存ループ（フェーズ 0〜3）の実装計画

- **既存コード（読み込み推奨）**:
  - [ml/src/model/trainer.py](ml/src/model/trainer.py) — 学習ロジック（LGB_PARAMS、ソフトマックス正規化+IR）
  - [ml/src/scripts/run_walkforward.py](ml/src/scripts/run_walkforward.py) — Walk-Forward 実装（`retrain_interval` 対応済み）
  - [ml/src/scripts/run_backtest.py](ml/src/scripts/run_backtest.py) — バックテスト本体（`--strategy-config` 対応済み）
  - [ml/src/scripts/run_gate_check.py](ml/src/scripts/run_gate_check.py) — KPI 計算の参考（ゾーン判定は本ループでは使わない）

- **関連ファイル**:
  - [ml/configs/strategy_default.yaml](ml/configs/strategy_default.yaml) — フィルタ側の config（本ループでは触らない）
  - [.claude/commands/inner-loop.md](.claude/commands/inner-loop.md) — 既存のフィルタ探索ループ

---

## 9. 変更履歴

- 2026-04-24: 初版作成（設計確定、実装未着手）
- 2026-04-24: **タスク 1 完了**（trainer.py 拡張、単体テスト追加）

---

## 10. 実装進捗ログ

### 2026-04-24 — タスク 1 完了（trainer.py の config 対応）

**変更内容**:
- [ml/src/model/trainer.py](ml/src/model/trainer.py) の `train()` を以下の keyword-only 引数で拡張:
  - `lgb_params: dict | None` — LGB_PARAMS にマージする上書き（`_merge_lgb_params` で副作用なくマージ）
  - `num_boost_round: int = 1000`
  - `early_stopping_rounds: int = 50`
  - `sample_weight: np.ndarray | None` — `lgb.Dataset(..., weight=...)` に渡す。train split 側のみ切り出し。
  - `return_metrics: bool = False` — True で dict `{model_path, metrics, best_iteration, params}` を返す
- 既存呼び出し（`train(X, y, version)`）は Path を返す動作のまま維持（後方互換）
- `metrics` 内容: `ece_rank1_raw`, `ece_rank1_calibrated`, `n_train`, `n_val`

**既存呼び出し側への影響**: なし
- 確認済み: `run_retrain.py` / `run_walkforward.py` / `run_backtest.py` / `run_grid_search.py` / `run_calibration.py` の 5 箇所すべて `train(X, y, version)` 形式で `Path` を受け取るのみ。keyword-only 追加 + デフォルト挙動維持で非破壊。

**追加テスト**: [ml/tests/test_trainer_config.py](ml/tests/test_trainer_config.py)（合成データ、7 ケース、10 秒前後で完走）
1. 後方互換: `train(X, y, version)` が `Path` を返す
2. `return_metrics=True` で dict を返し、必要キーが揃う
3. `lgb_params` で `num_leaves` / `learning_rate` / `min_child_samples` が上書きされ、`LGB_PARAMS` 本体は不変
4. `num_boost_round=10` 指定で `best_iteration ≤ 10`
5. `sample_weight` を渡しても完走・保存
6. `sample_weight` 長さ不一致で `ValueError`
7. 保存形式 `{"booster": ..., "softmax_calibrators": [...]}`（長さ 6）維持

**テスト結果**:
```
py -3.12 -m pytest ml/tests/test_trainer_config.py -v
=> 7 passed in 10.67s
```

既存テストの `test_no_regression.py` は KPI 履歴（2025-12/2026-03）に基づく回帰検知で失敗しているが、
これは本変更以前からの既存状態であり、trainer.py 変更とは無関係（既存 KPI データを参照するだけのテスト）。

**次のアクション**: タスク 2（`run_walkforward.py` の config 対応）。
- `get_model_for_month` に trial config を注入
- `sample_weight` 生成ロジック（`mode: "recency"` / `"exp_decay"`）
- `lgb_params` / `num_boost_round` / `early_stopping_rounds` を `train()` に渡す
- 注意: `feature_builder.py` の返り値に `race_date` が残っていない可能性があり、sample_weight 生成用に日付配列を別ルートで保持する必要がある（§6-3 落とし穴 3）
