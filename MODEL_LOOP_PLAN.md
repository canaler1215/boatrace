> # 🛑 (P-v) 凍結後の参照記録 (2026-04-28、Q-B 合意)
>
> 本ドキュメントの実行ループ・改善計画はすべて凍結済み。**新規着手は不可**。
> 設計記録 / 仕様参照としてのみ保持。詳細は [CLAUDE.md](CLAUDE.md)「現行の運用方針」冒頭参照。
>
> 手動レース予想は CLAUDE.md「手動レース予想の手順 (P-v 凍結後)」を参照。

---

# モデル構造自律改善ループ 実装計画（アプローチB）

本ドキュメントは**別セッションで実装するための設計書**である。
セッション開始時にこのファイルをまず読み、記載通りに実装を進めること。

最終更新: 2026-04-24
ステータス: **タスク1〜6 完了、案 X（trial 固有モデル永続コピー）実装済み、§7-6 smoke 動作確認合格、本番 10 trial 実行（§7-9、2026-04-24 改訂で 8→10）は実オッズ DL 完了待ち**

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
    "broken_months": 1,
    "cvar20_month_roi": -72.4,
    "roi_ci_low_90": -8.3,
    "roi_ci_high_90": 24.5,
    "avg_hit_odds": 261.0,
    "hit_rate_per_bet": 0.0035,
    "ece_rank1_calibrated": 0.1337
  },
  "monthly_roi": {
    "2025-05": 44.7,
    "2025-06": 104.0,
    ...
  },
  "primary_score": -32.55,
  "verdict": "marginal",
  "notes": "breakdown月が2026-01 で発生、CI 下限が負なので pass 失格"
}
```

### 3-4. primary_score の定義（2026-04-24 改訂）

```python
def primary_score(kpi: dict) -> float:
    """
    CVaR20 ベースの複合スコア（高いほど良い）。

    定義:
        primary_score = roi_total + 0.5 * cvar20 - 10 * broken_months

    ここで:
      cvar20          = 下位 20% 月次 ROI の平均（裾の平均、最低 1 月）
      broken_months   = 月次 ROI < -50% の月数（離散カウント）

    例: roi_total=11.2, cvar20=-79.5, broken=1
        → 11.2 + 0.5*(-79.5) - 10 = -38.55
    """
    roi = kpi["roi_total"]
    cvar20 = kpi.get("cvar20_month_roi", 0.0)
    broken = kpi.get("broken_months", 0)
    return roi + 0.5 * cvar20 - 10.0 * broken
```

**設計意図（2026-04-24 レビュー指摘反映）**:

旧定義 `roi - 2 * max(0, -50 - worst)` には以下の問題があった:

- `worst_month` が単月の偶発的事故に支配され、primary_score も 1 月の当落で大きく振れる
- roi_total にも worst 月の損失は含まれており、penalty と合わせて **二重カウント**
  （例: worst=-80% なら roi_total 側で -80、penalty 側で +60 ×2 = -140 相当のインパクト）
- -50 閾値の直前後で挙動が急変（連続関数だが勾配が急）

新定義は:

- **CVaR20（裾の「平均」）** で単月事故への過度な感度を緩和（2〜3 月分の情報を使う）
- **broken_months（離散カウント）** で -50% 超過を階段状に罰する（1 件 -10、2 件 -20、…）
- 係数 0.5 / 10 は「通算 ROI と同じ桁の単位」で解釈可能

### 3-5. verdict 判定ルール（2026-04-24 改訂）

pass 基準を CLAUDE.md「現行の運用方針」の実運用再開条件
（通算 ROI ≥ +10% かつ最悪月 > -50%）と完全整合させる。

```python
# 閾値（CLAUDE.md 実運用再開条件と一致）
PASS_ROI_MIN = 10.0         # 通算 ROI ≥ +10%
PASS_PLUS_RATIO_MIN = 0.60  # プラス月比率 ≥ 60%
PASS_BROKEN_MAX = 0         # 破局月 0 本（worst > -50% と等価）
PASS_CI_LOW_MIN = 0.0       # block bootstrap CI 下限 ≥ 0

def classify_verdict(kpi: dict) -> str:
    roi = kpi["roi_total"]
    plus_ratio = kpi["plus_month_ratio"]
    broken = kpi.get("broken_months", 0)
    ci_low = kpi.get("roi_ci_low_90")  # 無ければチェックスキップ（互換）

    pass_ok = (
        roi >= PASS_ROI_MIN
        and broken <= PASS_BROKEN_MAX
        and plus_ratio >= PASS_PLUS_RATIO_MIN
        and (ci_low is None or ci_low >= PASS_CI_LOW_MIN)
    )
    if pass_ok:
        return "pass"
    if roi >= 0:
        return "marginal"
    return "fail"
```

**設計意図**:

- 旧基準 `roi ≥ 0` は「通算黒字化」だったが、CLAUDE.md 再開条件は「+10% 以上」。
  verdict pass と実運用再開を同じ閾値に揃え、「pass なのに再開条件未達」の
  運用事故を防ぐ。
- `roi_ci_low_90` を必要条件に追加: ブロック長 3（= retrain 周期）の
  block bootstrap で通算 ROI の 90% 信頼区間を計算し、下限が 0 を下回る
  trial は **偶発的に黒字が出ただけの可能性が高い** として pass から落とす。
  旧 KPI（CI フィールド無し）との互換のため、キー不在時はチェックをスキップ。
- `broken_months` を pass 条件に使うことで、worst 1 点に依存しない離散判定に。

### 3-6. block bootstrap による通算 ROI CI

`build_success_record` で `run_model_loop.block_bootstrap_roi_ci(monthly_rows, ...)` を
呼び、`roi_ci_low_90` / `roi_ci_high_90` を KPI に注入する。

- **ブロック長**: 3（= retrain_interval、月次 ROI の系列相関を緩和）
- **再サンプル回数**: 2000
- **信頼水準**: 90%（片側 5%/95% パーセンタイル）
- **seed**: 0 固定（再現性確保）

月数が短い smoke ランでは block_length を自動縮小（`min(block_length, n_months)`）。

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

> **2026-04-24 改訂**: 相互レビュー指摘を受けて以下を変更。
> - T06 を `early_stop_tight`（T04 と同方向のキャパシティ減）から
>   `feature_subsample`（feature_fraction=0.5 / bagging_fraction=0.6、木間ランダム性↑）に差し替え
> - Nice 1 として T08_baseline_seed1 / T09_baseline_seed2 を追加
>   （T00 と同一設定で `lgb_params.seed` のみ変える trial 内ばらつき測定用）
> - 結果として pending は 10 本（T00〜T09）

`trials/pending/` に以下の YAML を作成:

| trial_id | 変更点 |
|---|---|
| T00_baseline | trainer.py 既定のまま（比較基準） |
| T01_window_2024 | train_start_year=2024 |
| T02_window_2025 | train_start_year=2025 |
| T03_sample_weight_recency | train_start=2023, sample_weight mode=recency, recency_months=12, recency_weight=3.0 |
| T04_lgbm_regularized | num_leaves=31, min_child_samples=200（木の複雑度↓） |
| T05_lgbm_conservative_lr | learning_rate=0.02, num_boost_round=2000 |
| T06_feature_subsample | feature_fraction=0.5, bagging_fraction=0.6（木間ランダム性↑、2026-04-24 差し替え）|
| T07_window_2024_plus_weight | train_start_year=2024 + sample_weight recency_months=6 recency_weight=2.0 |
| T08_baseline_seed1 | T00 と同一 + `lgb_params.seed=1`（2026-04-24 追加）|
| T09_baseline_seed2 | T00 と同一 + `lgb_params.seed=2`（2026-04-24 追加）|

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

1. results.jsonl を読み、primary_score（2026-04-24 改訂定義: CVaR20 + broken_months ベース）でソート
2. 上位 trial のパラメータ近傍を探る（例: T01 が良ければ T01b として train_start_year=2024_06 など）
3. 下位 trial の方向は避ける
4. **5 trial 連続で primary_score が baseline 比 非改善** → 構造変更提案フェーズへ進む検討
5. 合格（verdict=pass）trial が出たら即報告、以降は確証のため近傍を 2〜3 本追加して打ち止め

撤退条件（2026-04-24 改訂）:

単純な「10 trial pass 0 → LambdaRank」は統計的に早すぎる（p=15% 仮定で 10 回全失敗確率 ≒ 20%）
ため、段階化する:

- **10 trial 時点で評価**: pass 事後確率 P(p>10%) を β(1,1) 事前 + 観測で更新し、
  20% 超なら追加 5 trial（合計 15）まで延長。
- **15 trial pass 0** または **5 trial 連続で primary_score が baseline 比 非改善** →
  構造変更提案フェーズへ。
- 構造変更の候補は LambdaRank 単独指名ではなく、以下のツリーから期待値で選ぶ:
  1. 特徴量拡張（最小工数・期待値高い。例: 直前気象差分、場×コース交互作用、ST ばらつき）
  2. 目的関数変更（binary top-1 / pairwise / LambdaRank）
  3. キャリブレーション再設計（per-class IR → 結合 IR / Dirichlet）
  4. Purged/Embargoed time-series CV
- いずれも本格投入前に **単月 val top-1 accuracy の小規模 PoC** で筋を確認する。

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
- 2026-04-24: **タスク 2 完了**（run_walkforward.py の config 対応、sample_weight 生成、単体テスト追加）
- 2026-04-24: **タスク 3 完了**（run_model_loop.py 新規作成、trials/ ディレクトリ構造、単体テスト追加）
- 2026-04-24: **タスク 4 完了**（初期 trial seeds 8 本を配置、YAML 妥当性テスト追加）
- 2026-04-24: **タスク 5 完了**（`.claude/commands/model-loop.md` 新規作成、スラッシュコマンド登録確認）
- 2026-04-24: **タスク 6 完了**（CLAUDE.md に「モデル構造自律改善ループ（/model-loop）」章を追加、AUTO_LOOP_PLAN.md にフェーズ 6 を追記、trials/README.md はタスク 3 作成分のまま据え置き）
- 2026-04-24: **案 X 実装**（trial 固有モデルの永続コピー）。`run_model_loop.py` に `_copy_trial_model` を追加し、retrain 直後に `artifacts/model_loop_<trial_id>_<YYYYMM>.pkl` として `shutil.copy2`。同じ `train_start` を共有する trial 間で共有ファイルが上書きされる問題を回避（設計書 §3-1 準拠）。テスト 6 ケース追加、全 86 件パス。

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

### 2026-04-24 — タスク 2 完了（run_walkforward.py の config 対応）

**変更内容**:

1. [ml/src/features/feature_builder.py](ml/src/features/feature_builder.py) の `build_features_from_history()` を拡張:
   - `return_dates: bool = False` keyword-only 引数を追加
   - `return_dates=True` で `(X, y, race_dates)` を返す。`race_dates` は X と同じインデックス・長さの `pd.Series (datetime64[ns])`
   - 既存呼び出し（9 箇所の `X, y = build_features_from_history(df)`）は後方互換のまま維持
   - sample_weight 生成時の§6-3 落とし穴 3 を解消（`dropna`/`sort_values` 後の行順と一致する race_date を取得可能に）

2. [ml/src/scripts/run_walkforward.py](ml/src/scripts/run_walkforward.py):
   - `build_sample_weight(race_dates, ref_date, config)` 関数を新設:
     - `mode: "recency"` → `ref_date - recency_months` 以降を `recency_weight` 倍、それ以前は 1.0
     - `mode: "exp_decay"` → `exp(-decay_k * age_months)`（age は ref_date 起点、未来は 0 扱い）
     - `config=None` / `{}` / `{"mode": None}` で None 返却
     - 未知 mode は `ValueError`
   - `get_model_for_month()` に keyword-only 引数 `trial_config: dict | None` と `return_metrics: bool = False` を追加:
     - `trial_config["training"]["sample_weight"]` → build_sample_weight で重み配列化
     - `trial_config["training"]["num_boost_round"]` / `["early_stopping_rounds"]` / `trial_config["lgb_params"]` を `train()` に渡す
     - `return_metrics=True` で `(model, metrics_dict)` を返す（trainer.train の dict をそのまま）
     - retrain=False / trial_config=None / sample_weight 未指定 はすべて従来挙動を維持
   - sample_weight 生成時のみ `build_features_from_history(df, return_dates=True)` を呼ぶ（不要時は従来のまま）
   - ref_date は「学習期間末月の末日」（test_month の前月末）

3. CLI 引数は追加していない（トライアル注入は `run_model_loop.py`（タスク 3）経由で想定）

**追加テスト**: [ml/tests/test_walkforward_config.py](ml/tests/test_walkforward_config.py)（11 ケース、ネットワーク・DB 不要）

- `build_sample_weight`:
  1. config=None / mode=None → None
  2. recency 境界（cutoff 前後で 1.0 / N 倍が正しく切り替わる）
  3. recency 既定値（recency_months=12, weight=3.0）
  4. exp_decay 単調非増加、ref_date 同日で約 1.0
  5. 未知 mode → ValueError
- `build_features_from_history`:
  6. 後方互換: 戻り値が `(X, y)` の 2 要素
  7. `return_dates=True` で `(X, y, dates)`、長さ・インデックス・dtype 整合
- `get_model_for_month`（依存関係を monkeypatch でモック）:
  8. trial_config=None → `train()` に既定値が渡る（後方互換）
  9. `lgb_params` / `num_boost_round` / `early_stopping_rounds` が `train()` に伝搬
  10. sample_weight.mode=recency 指定時、`train()` に `np.ndarray` が渡る（最大値=recency_weight, 最小値=1.0）
  11. `return_metrics=True` で `(model, metrics_dict)` が返る

**テスト結果**:
```
py -3.12 -m pytest ml/tests/test_trainer_config.py ml/tests/test_walkforward_config.py -v
=> 18 passed in 5.93s
```

**既存呼び出し側への影響**: なし
- `build_features_from_history` は全 9 箇所とも `X, y = ...` の形で受け取っており、`return_dates` デフォルト False を追加しただけなので非破壊
- `get_model_for_month` は内部関数で外部から呼ばれていない（`run_walkforward.py` の `main()` からのみ）
- `run_walkforward.py --help` で CLI 引数が正常に解釈される（import エラーなし）

**次のアクション**: タスク 3（`run_model_loop.py` の新規作成）
- `trials/pending/*.yaml` を glob して順次実行するランナー
- `run_walkforward.py` の `main()` をライブラリ呼び出しできるようリファクタするか、
  `get_model_for_month` + `run_backtest_batch` を直接組み立てる
- `results.jsonl` へ KPI 追記、trial を `pending/` → `completed/` へ移動
- 設計書 §3.1, §3.3, §3.4, §3.5 に準拠

### 2026-04-24 — タスク 3 完了（run_model_loop.py 新規作成）

**変更内容**:

1. [ml/src/scripts/run_model_loop.py](ml/src/scripts/run_model_loop.py) を新規作成。以下を実装:
   - **YAML スキーマ検証** (`load_trial_yaml` / `validate_trial_schema`)
     - 必須キー: `trial_id`, `walkforward.{start,end}`, `strategy.{prob_threshold,ev_threshold,bet_amount}`
     - 任意キー: `description`, `hypothesis`, `training.*`, `lgb_params`, `walkforward.{retrain_interval,real_odds}`, `strategy.{max_bets,min_odds,exclude_courses,exclude_stadiums,bet_type}`
   - **trial 実行** (`run_trial_walkforward`)
     - `run_walkforward.main()` をコピーせず、ライブラリ関数 `get_model_for_month` + `run_backtest_batch` を直接組み立てる方針を採用（§4 タスク 3 設計方針に準拠）
     - 各月ごとに `retrain_interval` に応じて再学習判定、trial_config（`lgb_params` / `training.sample_weight` / `num_boost_round` / `early_stopping_rounds`）を `get_model_for_month(..., trial_config=..., return_metrics=True)` 経由で `trainer.train` に伝搬
     - 最後の再学習月の metrics dict（`ece_rank1_calibrated` を含む）を保持し KPI に同梱
     - `real_odds=True` のとき bet_type に応じて `load_or_download_month_odds` / `load_or_download_month_trio_odds` を呼び分け
   - **KPI 計算** (`compute_kpi`): 設計書 §3-3 の schema に一致。`roi_total` / `worst_month_roi` / `best_month_roi` / `plus_months` / `plus_month_ratio` / `avg_hit_odds` / `hit_rate_per_bet` を算出。wagered=0 や空 DataFrame でも落ちない。
   - **primary_score / classify_verdict** (§3-4 / §3-5 完全準拠)
     - `primary_score = roi_total - max(0, -50 - worst) * 2`
     - `pass`: roi≥0 かつ worst≥-50 かつ plus_ratio≥0.60、`marginal`: roi≥0 のみ、それ以外 `fail`
   - **ファイル出力**
     - `artifacts/walkforward_<trial_id>.csv` — Walk-Forward の raw 結果
     - `artifacts/walkforward_<trial_id>_summary.json` — KPI + primary_score + verdict + monthly_roi
     - `trials/results.jsonl` — 1 trial 1 行の append-only ログ
     - `artifacts/model_loop_<trial_id>_error.log` — エラー時の traceback
   - **成功時のみ** `trials/pending/<trial_id>.yaml` を `trials/completed/` へ移動（失敗時は pending に残して再実行可能）
   - **CLI**: `--trial <trial_id>` で単発実行、省略時は pending 全実行

2. [trials/](trials/) ディレクトリを新規作成:
   - `trials/pending/` (`.gitkeep`)
   - `trials/completed/` (`.gitkeep`)
   - `trials/README.md` — ディレクトリ運用ガイド

**追加テスト**: [ml/tests/test_model_loop.py](ml/tests/test_model_loop.py)（22 ケース、ネットワーク・DB 不要）

- A. スキーマ検証（5 ケース）: 正常系 / トップレベル必須欠落 / walkforward 必須欠落 / strategy 必須欠落 / mapping 不正
- B. KPI 計算（3 ケース）: 基本ケース（月別 ROI / avg_hit_odds / plus_month_ratio の整合性）/ 空 DataFrame / wagered=0 月
- C. primary_score / classify_verdict（8 ケース）: ペナルティ有無の境界 / verdict 3 分類 + 境界条件
- D. `discover_pending_trials`（3 ケース）: 指定 trial 欠落時の FileNotFoundError / `.yaml` と `.yml` 両対応 / 特定 trial 指定時の厳密マッチ
- E. `execute_trial_file`（3 ケース）:
  - 成功: YAML が pending → completed へ移動、results.jsonl に 1 行、summary.json 作成
  - 失敗（`run_trial_walkforward` が raise）: YAML は pending に残り、status=error、error.log が traceback 付きで生成
  - YAML 不正: 実行前スキーマ検証で失敗、pending に残り status=error、`run_trial_walkforward` は呼ばれない

**テスト結果**:
```
py -3.12 -m pytest ml/tests/test_trainer_config.py ml/tests/test_walkforward_config.py ml/tests/test_model_loop.py -v
=> 40 passed in 5.99s
```

さらに `python ml/src/scripts/run_model_loop.py --help` と空 pending 実行でスモーク確認済み（CLI 引数解釈 OK、pending 空時の早期 return OK）。

**既存呼び出し側への影響**: なし（新規スクリプト／新規ディレクトリのみ）。`run_walkforward.py` / `trainer.py` は本タスクで変更していない（タスク 1・2 で整えた API をそのまま利用）。

**次のアクション**: タスク 4（初期 trial seeds 作成）
- `trials/pending/` に T00_baseline, T01_window_2024, T02_window_2025, T03_sample_weight_recency, T04_lgbm_regularized, T05_lgbm_conservative_lr, T06_early_stop_tight, T07_window_2024_plus_weight を配置
- `strategy` セクションは全 trial 統一（設計書 §4 タスク 4 準拠）
- 実行前に baseline（T00）の Walk-Forward が実際に完走することを確認（設計書 §7-1）
- タスク 5（`/model-loop` スラッシュコマンド）, タスク 6（ドキュメント更新）も後続で対応

### 2026-04-24 — タスク 4 完了（初期 trial seeds 8 本を配置）

**変更内容**:

1. [trials/pending/](trials/pending/) に 8 本の trial YAML を配置（設計書 §4 タスク 4 準拠）:

   | trial_id | 変更点 | 仮説 |
   |---|---|---|
   | T00_baseline | 現行 trainer.py 既定（train_start=2023/1, LGB_PARAMS デフォルト） | 他 trial の比較基準 |
   | T01_window_2024 | train_start_year=2024 | 古いデータが直近の分布シフトを吸収しきれていないか |
   | T02_window_2025 | train_start_year=2025 | さらに超直近のみで過学習リスクを検証 |
   | T03_sample_weight_recency | 窓 2023〜 + recency_months=12, recency_weight=3.0 | 古いデータを捨てず直近を強調する折衷案 |
   | T04_lgbm_regularized | num_leaves=31, min_child_samples=200 | 過学習抑制で汎化性能を回復 |
   | T05_lgbm_conservative_lr | learning_rate=0.02, num_boost_round=2000 | 細かい収束で粗さ/過学習を解消 |
   | T06_early_stop_tight | early_stopping_rounds=30 | 早期停止で汎化に強い iter を採用 |
   | T07_window_2024_plus_weight | window=2024 + recency_months=6, recency_weight=2.0 | T01 × recency の複合効果 |

2. 全 8 本で `strategy` セクションを統一（BET_RULE_REVIEW 案 A ベース、比較可能性を保証）:
   ```yaml
   prob_threshold: 0.07, ev_threshold: 2.0, min_odds: 100.0,
   exclude_courses: [], exclude_stadiums: [2, 3, 4, 9, 11, 14, 16, 17, 21, 23],
   bet_amount: 100, max_bets: 5, bet_type: trifecta
   ```

3. 全 8 本で `walkforward` を `2025-05 〜 2026-04, retrain_interval=3, real_odds=true` に統一（§1-3 合意事項）。

**追加テスト**: [ml/tests/test_trial_seeds.py](ml/tests/test_trial_seeds.py)（40 ケース、全て静的検証・重い学習なし）

- 期待される 8 本が trials/pending/ に揃っていること
- 各 YAML が `load_trial_yaml` を通過、`trial_id` がファイル名と一致すること
- `strategy` セクションが 8 本すべてで統一されていること（比較統一性の回帰検知）
- `walkforward` 期間・retrain_interval・real_odds が統一されていること
- `sample_weight.mode` が `null` / `"recency"` / `"exp_decay"` の妥当値であること
- T00〜T07 それぞれの変更点が仕様通りであること（per-trial 検証）

**テスト結果**:
```
py -3.12 -m pytest ml/tests/test_trial_seeds.py -v
=> 40 passed in 4.38s

py -3.12 -m pytest ml/tests/test_trainer_config.py ml/tests/test_walkforward_config.py \
    ml/tests/test_model_loop.py ml/tests/test_trial_seeds.py -v
=> 80 passed in 5.84s
```

さらに `discover_pending_trials()` スモーク確認で 8 本すべてが列挙・load できることを確認済み。

**既存呼び出し側への影響**: なし（新規 YAML と新規テストのみ）。

**ユーザーのローカル環境で必要な準備（設計書 §2 前提、実行前確認）**:

タスク 5（`/model-loop` スラッシュコマンド）の実装を待たずに、ユーザーが先に baseline（T00）を手動で
走らせる場合の前提条件を以下にまとめる。すべて既存ワークフローの再確認であり、新規要件はない:

1. **Python 3.12 環境**: `py -3.12 --version` で確認。`pip install -r ml/requirements.txt` 済みであること
2. **データキャッシュ**: `data/history/` / `data/program/` / `data/odds/` に 2023-01〜2026-04 の K/B/オッズファイルがあること
   （設計書 §2-1 「本計画書の期間については既にダウンロード済み」の前提）
3. **DB 接続不要**: `run_backtest.py` / `run_walkforward.py` はファイルキャッシュだけで完結するため `BACKTEST_DATABASE_URL` は不要
4. **ディスク容量**: モデル 1 本 ~50MB × 10 trial = 500MB、CSV 数 MB × 10 = 数十 MB（2026-04-24 改訂で 8→10）
5. **実行時間見積もり**: 1 trial あたり 15〜25 分、10 本で 2.5〜4 時間（夜間回し想定）

単発実行例（タスク 5 完了前でも動く）:
```bash
# 全 10 本を連続実行
py -3.12 ml/src/scripts/run_model_loop.py

# T00_baseline のみ先行実行
py -3.12 ml/src/scripts/run_model_loop.py --trial T00_baseline
```

**次のアクション**: タスク 5（`/model-loop` スラッシュコマンド `.claude/commands/model-loop.md` を新規作成）
- argument-hint: `[trial_id | all]`
- pending に YAML があれば `run_model_loop.py` を実行、なければ次 trial 設計フェーズへ
- 連続実行合意のため、途中報告は最小限。全 trial 完了後に results.jsonl を読んでまとめて報告する設計
- タスク 6（CLAUDE.md / AUTO_LOOP_PLAN.md 追記）も後続で対応
- 設計書 §7-6 の動作確認（T00_baseline + T01 の実行）はタスク 5 完了後、ユーザーがローカルで実 Walk-Forward を走らせる段で実施

### 2026-04-24 — タスク 5 完了（/model-loop スラッシュコマンド）

**変更内容**:

[.claude/commands/model-loop.md](.claude/commands/model-loop.md) を新規作成。設計書 §4 タスク 5 準拠。

- `description`: 「モデル構造自律改善ループを実行する（ローカルで学習ハイパラ・学習窓・sample_weight を探索）」
- `argument-hint`: `[trial_id | all]`
- 既存 `/inner-loop`（GitHub Actions 経由、フィルタ探索）との違いを冒頭で明示（変更対象・実行場所・1 trial の時間）
- **前提チェック**: Python 3.12 / 依存パッケージ（lightgbm, yaml, pandas, sklearn）/ データキャッシュ（2023-01〜2026-04）を事前確認するコマンド群を記載。欠落時のユーザー誘導文も明記
- **実行フロー**: Step 1〜7 で構成
  - Step 1: 引数パース（空 / `all` → 全 trial、それ以外 → 単発）
  - Step 2: `trials/pending/*.yaml` 有無を確認。空なら `results.jsonl` を読んで新 trial 設計フェーズへ
  - Step 3: 実行開始通知（対象 trial / 見積もり時間 / 途中報告しない方針）
  - Step 4: `py -3.12 ml/src/scripts/run_model_loop.py [--trial <id>]` を実行。長時間化を前提に `run_in_background: true` + `BashOutput` ポーリング推奨
  - Step 5: `trials/results.jsonl` を pandas で整形
  - Step 6: verdict / primary_score / ROI / worst_month / plus_ratio / ECE(calibrated) のテーブルを添えて報告
  - Step 7: 設計書 §5 の判定ルールで次アクション提案（上位 trial 近傍 / 構造変更 / 撤退）
- **エラーハンドリング**: 1 trial 失敗時も run_model_loop.py が次 trial に進む／pending に残って再実行可能／traceback は `artifacts/model_loop_<trial_id>_error.log` に保存、という仕様を明記
- **絶対にやってはいけないこと**: `strategy_default.yaml` 変更禁止／複数パラメータ同時変更禁止／`strategy` セクションの trial ごとの変更禁止／GitHub Actions 使用禁止／途中キャンセル禁止／`ml/src/collector/` と `ml/src/features/` への変更禁止（§6-4 準拠）
- **撤退条件**: 10 trial 回しても verdict=pass 0 本 / 5 trial 連続で非改善 / 実行時間超過

**テスト結果**:

```
py -3.12 -m pytest ml/tests/test_trainer_config.py ml/tests/test_walkforward_config.py \
    ml/tests/test_model_loop.py ml/tests/test_trial_seeds.py -v
=> 80 passed in 5.60s
```

動作確認:
- `py -3.12 ml/src/scripts/run_model_loop.py --help` が正常に引数解釈される（`--trial` / `--all` を表示）
- Claude Code ハーネスのスキル一覧に `model-loop` が登録されたことを確認（`/model-loop` で発火可能）

**既存呼び出し側への影響**: なし（新規 md ファイルのみ）。

**md 内リンクの妥当性確認**:
- `MODEL_LOOP_PLAN.md` ✓ 存在
- `ml/src/scripts/run_model_loop.py` ✓ 存在
- `ml/src/scripts/run_collect.py` ✓ 存在
- `ml/requirements.txt` ✓ 存在

**次のアクション**: タスク 6（ドキュメント更新）
- `CLAUDE.md` に「モデル構造ループ（/model-loop）」セクション追加（`/inner-loop` との用途分けを明示）
- `AUTO_LOOP_PLAN.md` に「フェーズ 6: モデル構造ループ」を追記
- `trials/README.md` はタスク 3 で既に作成済みなので追加更新は不要の可能性（要確認）
- その後、設計書 §7-6 の動作確認（T00_baseline + T01 を実際に走らせて results.jsonl に 2 行追記されることを確認）→ §7-9 の残 6 trial 連続実行へ進む

### 2026-04-24 — §7-6 動作確認 合格（smoke trial 経路）

**経緯**:

本番 T00_baseline / T01_window_2024 を走らせるには WF 期間 2025-05〜2026-04 の実オッズが必要だが、
`data/odds/` の実測で `odds_202505.partial.parquet` / `odds_202512.partial.parquet` の 2 件のみ
（いずれも未完了キャッシュ）であることが判明。本来の期間全 12 ヶ月に対して **10 ヶ月分の実オッズが未取得**。

本番データ揃え（`download_odds.py` × 10〜12 ヶ月、1 ヶ月 ≈ 90 分、合計 15〜18 時間）を待たずに
パイプラインの動作確認だけ先行するため、以下 2 本の **smoke 用 trial** を一時的に作成して実行:

| trial_id | WF 期間 | real_odds | 学習設定 | 追加検証 |
|---|---|---|---|---|
| T00_smoke | 2025-12（単月） | **false（合成オッズ）** | train_start=2023/1, LGB_PARAMS デフォルト | 基本経路 |
| T01_smoke | 2025-12（単月） | **false（合成オッズ）** | train_start=2024/1, sample_weight.mode=recency(12mo, ×3), lgb_params override | sample_weight 生成 / lgb_params 上書き伝搬 |

**実行結果**（`py -3.12 ml/src/scripts/run_model_loop.py --trial T00_smoke` → `T01_smoke`、所要 10〜15 分）:

| 判定項目 | 期待 | 実測 | 結果 |
|---|---|---|---|
| ① `trials/results.jsonl` に 2 行追記 | 2 | 2 | ✅ |
| ② 各行 status=success、KPI（roi_total / worst_month_roi / ece_rank1_calibrated 等）が数値 | 数値 | T00: roi=119.05, ece=0.001589 / T01: roi=12.22, ece=0.001928 | ✅ |
| ③ YAML が `trials/completed/` へ移動 | 2 ファイル | 2 ファイル | ✅ |
| ④ artifacts（WF CSV + summary.json）生成 | 4 ファイル | 4 ファイル（CSV 350KB 前後） | ✅ |
| ⑤ `artifacts/model_loop_*_error.log` が空 | 空 | 空 | ✅ |

**副次検証**:
- `sample_weight.mode=recency`（T01_smoke）→ `build_sample_weight` が `np.ndarray` を生成し `train()` に渡り完走
- `lgb_params` 上書き（T01_smoke: `learning_rate=0.05, num_leaves=63`）→ `_merge_lgb_params` 経由で LightGBM に反映・完走
- 単月 WF（start=end=2025-12）でも `run_trial_walkforward` 内の月ループが正しく終了
- 合成オッズ経路（`real_odds=false`）でも `run_backtest_batch` が問題なく KPI を算出

**smoke 由来の verdict について（運用メモ）**:

T00_smoke / T01_smoke ともに `verdict=pass` が出たが、これは**単月 WF の構造的副作用**:
- `plus_month_ratio` が 0% or 100% の二択になる
- `worst_month_roi == roi_total` のため `primary_score` ペナルティ 0
- 合成オッズの payout は艇番ベース全国平均で過大気味、ROI も過大推定

したがって**この pass 判定は本番戦略評価の根拠にしない**。本番判定は §7-9 で本番 trial（WF 12 ヶ月・real_odds=true）を回した際の `results.jsonl` に基づく。

**後始末**:

smoke 実行の副産物は本番データと混在させないため以下を削除:
- `trials/results.jsonl`（本番実行時に新規作成される）
- `trials/completed/T00_smoke.yaml`, `T01_smoke.yaml`
- `artifacts/walkforward_T00_smoke.csv|_summary.json`, `T01_smoke.csv|_summary.json`
- `artifacts/model_202511_from202301_wf.pkl`（T00_smoke 副産物、本番時に再作成される）
- `artifacts/model_202511_from202401_wf.pkl`（T01_smoke 副産物、本番時に再作成される）

pending 側の本番 trial 8 本（T00_baseline, T01_window_2024, ...）は一切触っていない。

**次のアクション**:

1. **並行進行中**: `download_odds.py` を 2025-05〜2026-04 の 12 ヶ月で直列実行（ユーザーのローカル、別 PowerShell ウィンドウ）。所要 15〜18 時間
2. A 完了後（翌日以降）: `py -3.12 ml/src/scripts/run_model_loop.py` で本番 8 trial を連続実行 → §7-9
3. 先行可能なら タスク 6（CLAUDE.md / AUTO_LOOP_PLAN.md 追記）を並行で進められる

### 2026-04-24 — タスク 6 完了（ドキュメント更新）

**変更内容**:

1. [CLAUDE.md](CLAUDE.md)
   - 既存「自律改善ループ（内ループ）の運用」章の直後に「モデル構造自律改善ループ（/model-loop）の運用」章を新設
   - `/inner-loop` vs `/model-loop` の用途差を冒頭の比較表で明示（変更対象・実行場所・1 trial の時間・判定基準・背景）
   - 実行方法（`/model-loop [trial_id | all]`）、前提（Python 3.12 / データキャッシュ / DB 不要 / ディスク 400MB）、なぜローカル実行か、代表的な trial YAML 構造、参照先リンクを記載
   - `strategy` セクションは全 trial 統一という比較可能性の原則を明記

2. [AUTO_LOOP_PLAN.md](AUTO_LOOP_PLAN.md)
   - 既存フェーズ 5 の直後に「フェーズ 6: モデル構造ループ（/model-loop、ローカル）」を追加
   - タスク 6-1〜6-9 に分解し、6-1〜6-7 を `[x]` 完了、6-8（本番 8 trial 連続実行、オッズ DL 完了待ち）・6-9（次イテレーション設計）を `[ ]` 未着手として記録
   - 進捗サマリに「6. モデル構造ループ 7 / 9」を追加、合計 21/29
   - 変更履歴に 1 行追記（本タスクの要約）
   - 「最終更新」ヘッダを「フェーズ 6 タスク 1〜7 完了、本番実行待ち」へ更新

3. [trials/README.md](trials/README.md)
   - タスク 3 で作成済み（§3-1 ディレクトリ構造、§3-2 YAML スキーマ、results.jsonl の見方）
   - 設計書側で「追加更新は不要の可能性」と明記されていたため、本タスクでは据え置き

**テスト結果**:

既存テストスイートは回帰なし（本タスクは md ファイルのみの変更のため、コードテストへの影響なし）:

```
py -3.12 -m pytest ml/tests/test_trainer_config.py ml/tests/test_walkforward_config.py \
    ml/tests/test_model_loop.py ml/tests/test_trial_seeds.py -v
=> 80 passed
```

**既存呼び出し側への影響**: なし（md ファイルのみ変更、コードやスキーマは未変更）。

**ユーザーのローカル環境で必要な準備**:

タスク 6 自体で新たに必要になる設定はない。本番 8 trial 実行（§7-9 / 6-8）のための前提は既にタスク 4 完了時に明記済み:

| 項目 | 状態 |
|---|---|
| Python 3.12 + `pip install -r ml/requirements.txt` | 既存（フェーズ 0 SETUP.md） |
| `data/history/`, `data/program/` 2023-01〜2026-04 | 既存キャッシュ済み |
| `data/odds/` 2025-05〜2026-04（12 ヶ月） | **ユーザーが現在ローカルで DL 実行中**（所要 15〜18 時間） |
| DB 接続 | 不要（ファイルキャッシュのみで完結） |
| ディスク空き ≥ 400MB | モデル 8 本分 |
| スラッシュコマンド登録 | 既存（タスク 5 完了、`/model-loop` として発火可能） |

**次のアクション**:

1. **（ユーザー作業）**: `download_odds.py` による 2025-05〜2026-04 実オッズ DL の完走を待つ
   - 進捗確認: `ls data/odds/odds_20{2505,2506,...,2604}.parquet` で 12 ファイル揃えばゴール
   - `.partial.parquet` が残っていれば未完了。再開は `download_odds.py` を同じ引数で再実行
2. DL 完了後、本セッション（または別セッション）で `/model-loop` を実行 → 本番 8 trial 連続実行 → §7-9
   - 所要 2〜3 時間（夜間回し推奨）
   - 途中報告は最小限、全 trial 完了後に `primary_score` 順で報告
3. §7-10 次イテレーション設計（上位 trial 近傍 2〜3 本追加、または構造変更提案）

### 2026-04-24 — スキル化方針の決定（`/trial-design` は本番 8 trial 完了後に設計）

**経緯**:

タスク 6 完了後、これまでの作業でスキル化できる候補を洗い出した。候補と評価:

| 候補 | 評価 |
|---|---|
| `/trial-design`（results.jsonl を読み、primary_score 上位近傍の新 trial YAML を `trials/pending/` に生成） | §7-10 で必ず発生する作業。スキル化でイテレーション速度が上がる |
| `/trial-report`（results.jsonl を primary_score 順で表・MODEL_LOOP_RESULTS.md 自動生成） | §7-9 完了時に必要だが、pandas 数行で書ける軽量処理 |
| `/odds-download-status`、smoke クリーンアップ、バックテストラッパー等 | スキル化のメリットが小さい／既存 CLI で十分 |

**決定（2026-04-24、ユーザー合意）**:

**`/trial-design` は本番 8 trial 完了後に設計する**。

**理由**:
- results.jsonl が 0 行の現状では近傍探索テンプレが設計できない（baseline の ROI すら未確定）
- 上位 trial の傾向（window 系が強いか、lgb_params 系が強いか、sample_weight が効くか）を見ないと
  「近傍探索」の粒度・方向が決まらない
- 先行実装すると実データと合わずに作り直しになるリスク
- §7-9 で実データを見てから設計するのが正しい順序

**進め方**:

1. §7-9（本番 8 trial 連続実行）完了 → `trials/results.jsonl` に 8 行が追記される
2. `primary_score` 順で並べ、上位・下位の傾向を観察
3. その知見をベースに `.claude/commands/trial-design.md` を新規作成
   - 入力: 任意（現 results.jsonl を読んで自動判断）または「T0X 近傍を N 本」のようなヒント
   - 出力: `trials/pending/T0Xb_*.yaml` などの新 trial YAML
   - 探索ルール（MODEL_LOOP_PLAN §5 準拠）: 上位近傍を探る／下位方向は避ける／5 trial 連続非改善で構造変更提案／10 trial で pass 0 なら撤退
4. スキル完成後は `/trial-design` → `/model-loop` のサイクルで §7-10 を回す

**`/trial-report` について**: 現時点では `/model-loop` 末尾の報告処理で十分。独立スキル化は保留。
もし §7-9 実行時に報告テンプレが複雑化するようなら、その段階で切り出しを再検討する。

**スキル化しないと決めたもの**（参考）:
- `/odds-download-status` — `ls data/odds/*.parquet` で足りる
- smoke クリーンアップ系 — 一度きりの処理
- バックテスト／再学習ラッパー — 既存 CLI が十分シンプル
- trial YAML 検証 — `run_model_loop.py` のスキーマ検証で既に担保済み

**次のアクション（更新）**:

1. **（ユーザー作業）**: 実オッズ DL の完走を待つ（本節より上に記載済み）
2. DL 完了後 `/model-loop` で本番 8 trial 連続実行 → §7-9
3. **results.jsonl を読んで `/trial-design` スキルを設計**（本追記で確定した方針）
4. `/trial-design` → `/model-loop` のサイクルで §7-10 を回す

### 2026-04-24 — 案 X 実装（trial 固有モデルの永続コピー）

**背景**:

`run_walkforward.get_model_for_month` が生成するモデルファイルの命名は
`model_<train_end>_from<train_start>_wf.pkl` で、**trial_id / lgb_params / sample_weight を含まない**。
同じ `train_start` を使う trial（T00_baseline / T03_sample_weight_recency / T04_lgbm_regularized /
T05_lgbm_conservative_lr / T06_early_stop_tight の 5 本が `2023/1` 共有、T01 / T07 が `2024/1` 共有）が
同名ファイルを上書きし合う。

- **同一 trial 内**: `cached_model` 変数で持ち回るため結果の正確性には影響なし
- **trial 間**: 次の trial の retrain で上書きされるため、**完了後に trial 個別のモデルを再参照できない**
- §3-1 「`artifacts/model_loop_<trial_id>.pkl` 学習済みモデル」は設計書に明記されていたが未実装だった

**変更内容**:

1. [ml/src/scripts/run_model_loop.py](ml/src/scripts/run_model_loop.py)
   - `_copy_trial_model(train_result, trial_id, test_year, test_month)` 関数を新設
   - `run_trial_walkforward` 内の retrain 直後（`should_retrain` 分岐の末尾）で呼び出し、
     `train_result["model_path"]` を `artifacts/model_loop_<trial_id>_<YYYY><MM>.pkl` として `shutil.copy2`
   - 非 retrain 月（`cached_model` 使用）では呼ばれない
   - 異常系（`train_result` が dict でない / `model_path` キー欠落 / 実ファイル不在）は警告ログのみで
     例外を送出しない（既存のバックテストフローを壊さない）

2. 命名規則: `model_loop_<trial_id>_<test_year><test_month:02>.pkl`
   - `test_year`/`test_month` は「このモデルを適用するテスト月」（学習末尾はその前月末）
   - 1 trial あたり retrain 回数分（本番設定 = 4 回）のコピーが作られる
   - ディスク: 50MB × 4 × 8 trial = 約 **1.6GB 追加**（§6-2 の削除方針でフォロー可能）

3. [ml/tests/test_model_loop.py](ml/tests/test_model_loop.py) にグループ F を追加（6 ケース）:
   - 正常コピー（コピー先ファイル名・中身・元ファイルが残ること）
   - 複数 trial が共有 src を上書きしても各 trial_id 付きコピーが独立に残ること
   - `model_path` が実ファイルでない場合の警告ログ + None 返却
   - `train_result` が dict でない場合の None 返却
   - `model_path` キー欠落時の None 返却
   - 命名規則（2 桁 0 埋め、長い trial_id）

**テスト結果**:

```
py -3.12 -m pytest ml/tests/test_trainer_config.py ml/tests/test_walkforward_config.py \
    ml/tests/test_model_loop.py ml/tests/test_trial_seeds.py -v
=> 86 passed in 5.84s（既存 80 + 新規 6）
```

`py -3.12 ml/src/scripts/run_model_loop.py --help` も正常解釈。

**既存呼び出し側への影響**: なし
- `run_walkforward.get_model_for_month` / `trainer.train` は未変更
- 非 retrain 月は `cached_model` 経由で従来通り
- 案 Y（version 命名に trial_id を含める）を採らなかったので、`run_walkforward.py` の
  `retrain=False` 時の glob フォールバック（`ARTIFACTS_DIR.glob("model_*.pkl")`）も影響なし

**ディスク運用の注意**（設計書 §6-2 準拠）:

本番 8 trial × 4 retrain × 50MB = **約 1.6GB** の追加容量を消費する。
検証完了後、不要な trial の `artifacts/model_loop_*.pkl` は安全に削除可能。
例: `rm artifacts/model_loop_T*_smoke*.pkl`（smoke 由来）、
`rm artifacts/model_loop_T0{4,5,6}_*.pkl`（primary_score 下位 trial）等。

**案 Y を採らなかった理由**（対話ログより）:
- 案 Y（version に trial_id を含める）は 32 中間ファイルが実行中に分散生成され、
  `run_walkforward.py` の `retrain=False` 時の glob フォールバックと衝突するリスクがあった
- 案 X は `run_model_loop.py` 1 ファイルに変更が閉じ、既存機能への影響ゼロ
- ディスク消費量は両案同等

**次のアクション**: 変更なし（本番 8 trial 実行待ち）
