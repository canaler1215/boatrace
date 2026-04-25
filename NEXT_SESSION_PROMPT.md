# 次セッション用プロンプト — タスク 6-10-c キャリブレーション再設計 / Purged CV

以下を次セッションの最初のユーザープロンプトとして貼り付けてください。

---

## プロンプト本文

boatrace プロジェクトのタスク 6-10-c「構造変更フェーズ」第三着手として、構造変更ツリー §5 の
**残り候補（キャリブレーション再設計 / Purged CV）** を進めてほしい。
背景と進め方は以下のとおり。作業開始前に必ず以下のファイルを読むこと:

- `OBJECTIVE_POC_RESULTS.md`（タスク 6-10-b 結果と案 Y 撤退判定）
- `FEATURE_POC_RESULTS.md`（タスク 6-10-a 結果）
- `MODEL_LOOP_PLAN.md §5`（構造変更ツリー）
- `CLAUDE.md`（「重大発見」=「1 着識別能力が全予測ビンで均一」）

### これまでの経緯（要約）

| タスク | 内容 | 結果 |
|---|---|---|
| 6-1〜6-9 | パラメータ探索（学習窓・sample_weight・LightGBM ハイパラ） | 13 trial で verdict=pass 再現 0、撤退 |
| 6-10-a | 特徴量拡張 PoC（c/b/a/複合）| 採用 0、撤退（top-1 ±0.3pp） |
| 6-10-b | 目的関数変更 PoC（B1/R1/P1）| 採用 0、撤退（R1 のみ +0.63pp で保留ゾーン入りだったが案 Y で撤退確定） |

すべて **CLAUDE.md「重大発見」=「全予測ビンで 1 着率均一」** に対して
入力情報増（特徴量）でも学習目的変更（objective）でも改善幅が seed 分散に飲まれる規模。

### タスク 6-10-c で試す候補

MODEL_LOOP_PLAN §5 の残り 2 候補:

| code | 概要 | 期待効果 |
|---|---|---|
| **C1** | per-class IsotonicRegression → **Dirichlet calibration**（多クラス結合 IR）| sum-to-1 制約と多クラス結合補正で trifecta 確率の質を改善 |
| **C2** | per-class IR → **結合 IR**（多変量 IR / matrix-IR）| C1 の中間案、Dirichlet ほど強くないが実装軽い |
| **PCV** | **Purged / Embargoed time-series CV**（leak 排除）| train/val 境界の情報リーク（同一開催の前後日）を排除し、汎化性能の真値推定 |

### 着手順序の推奨

1. **PCV から始めるべき理由**: 6-10-a/b の baseline 自体が leak 含み（同一場・隣接日の特徴量が
   train→val でリーク）の可能性。leak 排除後の baseline で 6-10-a/b を再評価すると改善が
   見えるかもしれない。**leak 排除は他のすべての PoC のベースとなる**。
2. **C1/C2 はその後**: PCV 適用後の clean baseline に対してキャリブレーション再設計を試す。

ただしユーザーと**順序の合意を 1 行で取ってから着手**すること。「PCV 先か、C1/C2 先か」。

### 最初に合意が必要なこと

トリッキーなのは PCV の影響範囲:

- PCV を入れるとデータ split ロジック（trainer.py / 6-10-a/b ハーネス）に手を入れる必要
- 同じく Walk-Forward (`run_walkforward.py`) も影響を受ける可能性
- ただし trainer.py 本体は変更せず、**PoC 専用ハーネスに閉じ込める**方針（6-10-b と同じ）

**合意したい 1 行**:
> タスク 6-10-c でも `ml/src/model/trainer.py` / `predictor.py` / `engine.py` は変更せず、
> PoC は新規スクリプト（例: `run_calibration_poc.py` / `run_purged_cv_poc.py`）に閉じ込める。
> 採用された手法のみ、別タスクで本体統合を検討する。

### PoC プロトコル（共通）

1. **特徴量はベースライン 12 次元のまま固定**（6-10-a/b の知見）
2. val=2025-12 単月で評価:
   - top-1 accuracy
   - NDCG@1 / NDCG@3
   - 1 着 ECE（C1/C2 では特に重要、PCV では参考値）
   - **trifecta ECE**（CLAUDE.md「全ビン均一」の改善有無を直接見る）
3. 結果は `artifacts/{tag}_poc_results.jsonl` に append、ログは `artifacts/{tag}_poc_logs/` に保存

### 採用判断基準

タスク 6-10-b と同じく厳しめ設定:

- **採用**: top-1 accuracy +1.0pp 以上
- **保留**: top-1 accuracy +0.5〜+1.0pp（複合検証や Walk-Forward に進む価値あり）
- **却下**: top-1 accuracy +0.5pp 未満

PCV のみ別評価軸あり:
- **PCV の効果検証**: 同条件で leak あり/なし baseline を比較し、val ROI 差が +5pp 以上なら採用

### 成果物

1. `ml/src/scripts/run_calibration_poc.py` および/または `run_purged_cv_poc.py`（新規）
2. `CALIBRATION_POC_RESULTS.md` および/または `PURGED_CV_POC_RESULTS.md`（新規）
3. `artifacts/calibration_poc_results.jsonl` / `artifacts/purged_cv_poc_results.jsonl`
4. 採用された手法のみ Walk-Forward で最終検証
5. `AUTO_LOOP_PLAN.md` フェーズ 6 タスク 6-10-c 進捗更新

### 絶対にやってはいけないこと

- ❌ `ml/src/model/trainer.py` / `predictor.py` / `engine.py` の本体変更
- ❌ `strategy` セクションの変更（全 trial 統一）
- ❌ 6-10-b の R1 (LambdaRank) を Walk-Forward に進める（案 Y で撤退確定済み）
- ❌ 単月 val 効果測定をスキップして Walk-Forward に直行する
- ❌ ベースライン特徴量を変える（PoC c/b/a の知見と混ざる）

### 実行環境

- Python 3.12（`py -3.12`）
- ローカル（Windows）、DB 接続不要
- データキャッシュ: `data/history/`, `data/program/` に 2023-01〜2026-04 揃い
- 1 PoC は約 7〜10 分（タスク 6-10-a/b と同等）

### 終了条件と次手の判断

- **3 候補（C1/C2/PCV）すべて採用基準未達**: 構造変更ツリー §5 のすべての候補を
  消費したことになる。フェーズ 6 全体の撤退を検討し、CLAUDE.md「実運用再開条件
  （ROI ≥ +10% / worst > -50%）」を別アプローチで攻めるか、運用停止を継続するかを
  ユーザーに判断委譲する
- **どれか 1 つ採用**: Walk-Forward 検証フェーズへ進み、`trials/pending/TXX_*.yaml` を作成
- **保留 (+0.5〜+1.0pp) 1 つ以上**: 複合検証（PCV + C1 など）を 1 ラウンド試す

### 参照すべきドキュメント

- [OBJECTIVE_POC_RESULTS.md](OBJECTIVE_POC_RESULTS.md) — タスク 6-10-b 結果と案 Y 撤退理由
- [FEATURE_POC_RESULTS.md](FEATURE_POC_RESULTS.md) — タスク 6-10-a 結果
- [MODEL_LOOP_RESULTS.md](MODEL_LOOP_RESULTS.md) — 13 trial 結果、seed 分散
- [MODEL_LOOP_PLAN.md](MODEL_LOOP_PLAN.md) §5 — 構造変更ツリー
- [CLAUDE.md](CLAUDE.md) — 「重大発見」（1 着識別能力の全ビン均一）
- [AUTO_LOOP_PLAN.md](AUTO_LOOP_PLAN.md) フェーズ 6 タスク 6-10
- [ml/src/scripts/run_objective_poc.py](ml/src/scripts/run_objective_poc.py) — 6-10-b ハーネス（参考）
- [ml/src/scripts/run_feature_poc.py](ml/src/scripts/run_feature_poc.py) — 6-10-a ハーネス（参考）
- [ml/src/model/trainer.py](ml/src/model/trainer.py) — 現行 multiclass + per-class IR

以上。trainer.py 等不変方針の合意と、PCV/C1/C2 の着手順序合意を確認してから着手してほしい。
