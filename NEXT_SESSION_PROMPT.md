# 次セッション用プロンプト — タスク 6-10-d R1 LambdaRank 本体統合 + Walk-Forward 検証

以下を次セッションの最初のユーザープロンプトとして貼り付けてください。

---

## プロンプト本文

boatrace プロジェクトのタスク 6-10-d として、**6-10-b で保留ゾーン入りした R1 (LambdaRank)
を本体統合し、Walk-Forward 12 ヶ月で検証**してほしい。これは構造変更ツリー §5 全 4 候補
（特徴量拡張 / 目的関数変更 / Purged CV / キャリブレーション再設計）すべて採用 0 となった
あとの **最後の保留ゾーン候補**であり、フェーズ 6 撤退判定の最終ゲートになる。

作業開始前に必ず以下を読むこと:

- `OBJECTIVE_POC_RESULTS.md`（タスク 6-10-b 結果、R1 が +0.63pp 保留ゾーン入り）
- `PURGED_CV_POC_RESULTS.md`（タスク 6-10-c 第 1 候補、leak フリー判定）
- `CALIBRATION_POC_RESULTS.md`（タスク 6-10-c 第 2 候補、確率質改善は限定的）
- `MODEL_LOOP_PLAN.md §3-5`（採用基準、Walk-Forward 評価条件）
- `CLAUDE.md`（実運用再開条件「ROI ≥ +10% / worst > -50%」、重大発見「全ビン均一」）
- `ml/src/model/trainer.py` / `predictor.py` / `engine.py`（統合対象の本体コード）
- `ml/src/scripts/run_objective_poc.py`（R1 を実装した PoC ハーネス、参考）

### これまでの経緯（要約）

| タスク | 内容 | 結果 |
|---|---|---|
| 6-1〜6-9 | パラメータ探索（学習窓・sample_weight・LightGBM ハイパラ） | 13 trial で verdict=pass 再現 0、撤退 |
| 6-10-a | 特徴量拡張 PoC（c/b/a/複合） | 採用 0、撤退 |
| 6-10-b | 目的関数変更 PoC（B1/R1/P1） | R1 のみ +0.63pp で保留、案 Y で一旦撤退 |
| 6-10-c PCV | Purged/Embargoed CV PoC | 採用 0、leak フリー判定 |
| 6-10-c CAL | C1 Dirichlet / C2 結合 IR PoC | 採用 0（trifecta ECE -10.4% は出るが top-1 動かず） |

→ **構造変更ツリー §5 全 4 候補消費完了。R1 LambdaRank が最後の保留ゾーン候補**。

### タスク 6-10-d で行うこと

**R1 (LambdaRank) を trainer.py / predictor.py / engine.py に統合し、Walk-Forward
12 ヶ月で評価する**。

#### Step 1: 単月再現テスト（着手前の sanity check）

`run_objective_poc.py --objective lambdarank` の結果（top1=0.5773 / NDCG@1=0.6969）が
seed 分散 ~0.5pp の中で再現するかを確認する。**LightGBM の seed を固定して 3 回実行**し、
top-1 の標準偏差を測る。標準偏差が ≥ 0.4pp なら **6-10-b の +0.63pp 改善は seed ノイズに
飲まれている可能性が高く、Walk-Forward 検証はスキップしてフェーズ 6 撤退**を提案する。

#### Step 2: trainer.py への LambdaRank モード統合

ユーザーと合意してから着手:
- `trainer.py` に `objective="lambdarank"` モードを追加（既存 multiclass モードと共存、CLI 引数で切替）
- ranking 系では race_id 順ソート + group ベクトル必須（`run_objective_poc.py` の `_sort_for_ranking` / `_build_groups` 移植）
- 出力は (N, 1) スコア → レース内 softmax で 1 着確率 (N, 6) に変換するアダプタを書く
- ECE キャリブレーションは引き続き per-class IR + softmax 再正規化で動かす（Plackett-Luce 互換）

#### Step 3: predictor.py / engine.py 互換調整

- 保存形式は既存と同じ `{"booster": ..., "softmax_calibrators": [...]}` を維持
- `predictor.py` で booster の objective を読み取って multiclass / lambdarank を分岐
- LambdaRank の場合は **booster.predict() が (N, 1) を返す** ので、レース内 softmax 後に
  6 クラス確率にブロードキャストして既存 IR キャリブレーションを通す
- engine.py の API（`get_model_for_month` / `run_backtest_batch`）は触らない

#### Step 4: Walk-Forward 12 ヶ月検証

- `trials/pending/T13_lambdarank.yaml` を作成
- 学習設定: train_start_year=2023, sample_weight=null（baseline 同条件）
- LightGBM: objective=lambdarank, label_gain=[0,1,3,7,15,31], ndcg_eval_at=[1,3]
- walkforward: start=2025-05, end=2026-04, retrain_interval=3, real_odds=true
- strategy: 全 trial 統一（CLAUDE.md 既定値）
- `/model-loop T13_lambdarank` で実行

#### Step 5: 採用判断

MODEL_LOOP_PLAN §3 採用基準:
- **採用**: 通算ROI ≥ +10% **かつ** broken_months=0（worst > -50%）**かつ** プラス月 ≥ 60% **かつ** bootstrap CI 下限 ≥ 0
- **保留**: 通算ROI ≥ 0% かつ broken_months=0
- **却下**: 上記いずれも未達

### 厳守事項

- ❌ Step 1 の sanity check（seed 固定 3 回反復で std 測定）を**スキップしない**
  - 6-10-b の +0.63pp が真の改善か seed ノイズか未確定
  - std ≥ 0.4pp なら Walk-Forward 検証は時間とディスクの無駄
- ❌ trainer.py / predictor.py / engine.py の本体統合は**ユーザー合意を取ってから**着手
  - これまでの 6-10-a/b/c は本体不変方針だった。本タスクは初の本体変更
- ❌ multiclass 既存モードを壊さない（`run_predict.py` / `run_backtest.py` が回帰しないこと）
- ❌ strategy セクションの変更（全 trial 統一）

### Step 1 の具体実装案（着手前合意ポイント）

`run_objective_poc.py` に `--seed` 引数を追加し、LightGBM params に `seed=N`,
`bagging_seed=N`, `feature_fraction_seed=N` を渡せるようにする。または新規ハーネス
`run_lambdarank_seed_check.py` を作る。3 回（seed=42, 123, 7）走らせ、top-1 の
mean / std / min / max を出す。実行時間は ~7 分 × 3 = 21 分の見込み。

**合意したい 1 行**:
> Step 1 は seed 固定 3 回反復で R1 LambdaRank の top-1 std を測る。
> std < 0.3pp なら +0.63pp は真の改善とみなして Step 2〜5 へ進む。
> std ≥ 0.4pp なら Walk-Forward は無駄と判定してフェーズ 6 撤退を提案する。
> 0.3〜0.4pp はグレーゾーンとして判断委譲する。

### 採用判断のサニティチェック

R1 LambdaRank で Walk-Forward 採用基準が出たとしても、CLAUDE.md「重大発見（全ビン均一）」
が解消するレベルではない。あくまで **「ROI ≥ +10% を達成できる戦略」** として最低限の
実用性を確認するだけ。本番運用再開はその後の運用ルール再策定（資金管理、月次モニタリング
基準）が前提となる。

### 終了条件と次手の判断

- **R1 採用基準達成**: `trials/pending/T13_lambdarank.yaml` を `completed/` へ移動。
  運用再開準備フェーズ（資金管理 / 月次モニタリング基準策定）へ移行する提案を出す
- **R1 保留**: bootstrap CI 下限 < 0 などで「ギリ達成、信頼度低」の場合、
  追加 seed で 2〜3 trial 反復するか、フェーズ 6 撤退かを判断委譲
- **R1 却下**: フェーズ 6 撤退確定。CLAUDE.md「実運用再開条件」を別アプローチで
  攻めるか、運用停止継続をユーザーに判断委譲する
- **Step 1 で std ≥ 0.4pp**: 即フェーズ 6 撤退提案（Walk-Forward に進まない）

### 成果物

1. `run_lambdarank_seed_check.py`（または `run_objective_poc.py` に `--seed` 追加）
2. `LAMBDARANK_SEED_CHECK_RESULTS.md`（Step 1 結果）
3. **以下は Step 1 通過時のみ作成**:
   - trainer.py / predictor.py に LambdaRank モード追加（PR 分割推奨）
   - `trials/pending/T13_lambdarank.yaml`
   - `LAMBDARANK_WALKFORWARD_RESULTS.md`
   - artifacts/walkforward_T13_lambdarank.csv / _summary.json
4. AUTO_LOOP_PLAN.md フェーズ 6 タスク 6-10-d 進捗更新

### 実行環境

- Python 3.12（`py -3.12`）
- ローカル（Windows）、DB 接続不要
- データキャッシュ: `data/history/`, `data/program/` に 2023-01〜2026-04 揃い
- 実オッズキャッシュ: `data/odds/2025-05〜2026-04` 揃い（Walk-Forward 用）
- Step 1: 約 21 分（7 分 × 3 seed）
- Step 4: 約 3〜4 時間（Walk-Forward 12 ヶ月、3 ヶ月毎再学習）

### 参照すべきドキュメント

- [OBJECTIVE_POC_RESULTS.md](OBJECTIVE_POC_RESULTS.md) — タスク 6-10-b 結果、R1 +0.63pp 保留
- [PURGED_CV_POC_RESULTS.md](PURGED_CV_POC_RESULTS.md) — leak フリー判定
- [CALIBRATION_POC_RESULTS.md](CALIBRATION_POC_RESULTS.md) — C1/C2 撤退、確率質改善は限定的
- [MODEL_LOOP_RESULTS.md](MODEL_LOOP_RESULTS.md) — 13 trial 結果、seed 分散
- [MODEL_LOOP_PLAN.md](MODEL_LOOP_PLAN.md) §3-5 — 採用基準、構造変更ツリー
- [CLAUDE.md](CLAUDE.md) — 「重大発見」（1 着識別能力の全ビン均一）、実運用再開条件
- [AUTO_LOOP_PLAN.md](AUTO_LOOP_PLAN.md) フェーズ 6 タスク 6-10
- [ml/src/scripts/run_objective_poc.py](ml/src/scripts/run_objective_poc.py) — R1 実装の参考
- [ml/src/scripts/run_calibration_poc.py](ml/src/scripts/run_calibration_poc.py) — cal split 設計の参考
- [ml/src/model/trainer.py](ml/src/model/trainer.py) — 統合対象（multiclass 現行）
- [ml/src/model/predictor.py](ml/src/model/predictor.py) — 統合対象
- [ml/src/backtest/engine.py](ml/src/backtest/engine.py) — API は不変だが互換性確認

以上。**Step 1（seed 固定 3 回 std 測定）の合意を取ってから着手してほしい**。
