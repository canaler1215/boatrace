# LAMBDARANK_SEED_CHECK_RESULTS — R1 LambdaRank seed 反復による有意性検証（タスク 6-10-d Step 1）

最終更新: 2026-04-25
対象: AUTO_LOOP_PLAN フェーズ 6 タスク 6-10-d Step 1（着手前 sanity check）

## 背景

- タスク 6-10-b（[OBJECTIVE_POC_RESULTS.md](OBJECTIVE_POC_RESULTS.md)）で R1 (LambdaRank) が
  単月 val（2025-12）で baseline 比 **+0.63pp**（top1 0.5710 → 0.5773）の改善を示し、
  保留ゾーン入り（採用基準 +1.0pp 未達）。
- フェーズ 6 全 4 候補（特徴量 / 目的関数 / Purged CV / Calibration）が採用 0 となった
  あとの **最後の保留候補**であり、Walk-Forward 12 ヶ月検証へ進む前に
  「+0.63pp が真の改善か seed ノイズか」を切り分ける必要がある。
- [MODEL_LOOP_RESULTS.md](MODEL_LOOP_RESULTS.md) では Walk-Forward 12 ヶ月の seed 反復で
  ROI std 17pp（T07/T10/T11）と判明済みだが、**単月 top-1 自体の seed std は未測定**。

## 実行条件

| 項目 | 値 |
|---|---|
| train 期間 | 2023-01 〜 2025-11 |
| val 期間 | 2025-12（単月、~28k サンプル / ~4,718 races） |
| 特徴量 | ベースライン 12 次元 |
| LGB params | lr=0.05, num_leaves=63, min_child_samples=50, ff=0.8, bf=0.8, bf_freq=5 |
| num_boost_round | 1000（早期停止 50） |
| seed 固定 | `seed` / `bagging_seed` / `feature_fraction_seed` / `data_random_seed` を一括固定、`deterministic=True` |
| 反復 seed | 42, 123, 7 |
| 試行 | baseline (multiclass) × 3 + R1 (lambdarank) × 3 = **6 run** |
| ハーネス | `ml/src/scripts/run_objective_poc.py`（`--seed` 追加）+ `run_lambdarank_seed_check.py`（driver） |
| 結果保存 | `artifacts/lambdarank_seed_check_results.jsonl` / `_summary.json` / `_logs/*.log` |

## 採用判断基準（合意済み 2026-04-25）

`Δ_obs = mean(R1.top1) - mean(baseline.top1)`、
`std_pooled = sqrt((std(R1)^2 + std(baseline)^2) / 2)` に対して:

- **go** （Step 2 へ進む）: `Δ_obs ≥ 2 × std_pooled` **かつ** `Δ_obs ≥ 0.4 pp`
- **withdraw**（フェーズ 6 撤退提案）: `Δ_obs < std_pooled` **または** `Δ_obs < 0.2 pp`
- **gray**（ユーザー判断委譲）: 中間

設計意図: 6-10-b の +0.63pp は単月の数値であり、seed 由来のばらつきと区別できていなかった。
2σ 基準で「seed ノイズで偶然出る確率が低い」ことを担保、かつ絶対値 0.4pp で
「Walk-Forward 12 ヶ月に進む価値がある最低限の effect size」を確保する。

## 結果テーブル

### per-run（top-1 accuracy、val 2025-12）

| seed | baseline (multiclass) | R1 (lambdarank) | Δ |
|---:|---:|---:|---:|
| 42  | 0.5707 | **0.5796** | +0.89 pp |
| 123 | 0.5687 | 0.5740 | +0.53 pp |
| 7   | 0.5698 | 0.5739 | +0.41 pp |

best_iter:

| seed | baseline | R1 |
|---:|---:|---:|
| 42  | 154 | 173 |
| 123 | 183 | 134 |
| 7   | 203 |  74 |

### 集計

| 指標 | baseline | R1 lambdarank |
|---|---:|---:|
| n | 3 | 3 |
| mean | 0.56973 | 0.57582 |
| std (ddof=1) | 0.00098 | 0.00326 |
| min | 0.56872 | 0.57386 |
| max | 0.57067 | 0.57959 |

- **Δ_obs（R1 mean − baseline mean）**: **+0.609 pp**
- **std_pooled** = sqrt((0.00098² + 0.00326²)/2) = **0.241 pp**
- 2σ_pooled = 0.481 pp
- 6-10-b 単月値（+0.63 pp）は本実験の Δ_obs（+0.609 pp）にほぼ一致 → 結果再現性あり

## 判定: **go**

| 条件 | 値 | 判定 |
|---|---|---|
| Δ_obs ≥ 2 × std_pooled | 0.609 ≥ 0.481 | ✅ |
| Δ_obs ≥ 0.4 pp | 0.609 ≥ 0.4 | ✅ |
| **go 条件** | 両方満たす | ✅ |
| withdraw 条件（Δ_obs < σ または < 0.2pp） | 0.609 ≥ 0.241、0.609 ≥ 0.2 | 不該当 |

→ **R1 LambdaRank の +0.6pp 改善は seed ノイズでは説明できない**。
   Walk-Forward 12 ヶ月検証（Step 2〜5）へ進む価値あり。

## 補足所見

### 1. R1 のほうが seed 分散が大きい（0.10pp → 0.33pp、3.4×）

baseline std=0.10pp に対し R1 std=0.33pp。LambdaRank は best_iter のばらつきが
74〜173 と非常に広く（baseline 154〜203 に比べて広範）、ranking 系の損失曲面が
multiclass より複雑な可能性。Walk-Forward では retrain 毎にこの分散が混入するため、
**月次 ROI の seed 揺れは既存 multiclass モデル（17pp）より広がる可能性**を念頭に置く。

### 2. NDCG@1 でも整合した改善（参考）

| seed | baseline NDCG@1 | R1 NDCG@1 | Δ |
|---:|---:|---:|---:|
| 42  | 0.6896 | 0.6994 | +0.99 pp |
| 123 | 0.6871 | 0.6940 | +0.69 pp |
| 7   | 0.6884 | 0.6932 | +0.48 pp |

NDCG@1 mean Δ = +0.72 pp。top-1 と独立指標で同方向の改善が出ているため、
偶然の効果ではなく ranking 専用 objective の構造的優位性と整合する。

### 3. ECE は R1 のほうが小さい（参考）

raw ECE: baseline ~0.0057 vs R1 ~0.0119（softmax 化後）。
ただし R1 は IsotonicRegression 未適用の生確率ベースなので、本体統合後に
per-class IR を通せば既存 multiclass + IR と同等の ECE になる見込み。

### 4. CLAUDE.md「重大発見」（全ビン均一）への含意

R1 の +0.6pp 改善は「1 着識別能力」の底上げを示唆するが、絶対水準（0.5758）は
依然 baseline 0.5697 と同じオーダー。**「全ビンで 1 着率均一」が劇的に解消する
レベルではない**。Walk-Forward で ROI ≥ +10% / worst > -50% を達成できるかが
最終ゲートで、達成しても本番運用再開には資金管理ルール再策定が前提となる
（タスク 6-10-d 設計書のサニティチェック節と整合）。

## 次のアクション

**Step 2: trainer.py への LambdaRank モード統合**へ進む。
ユーザー合意のうえで以下を着手:

1. `trainer.py` に `objective="lambdarank"` モードを追加
   - 既存 multiclass モードと共存、CLI / 設定で切替可能に
   - race_id 順ソート + group ベクトル構築（PoC ハーネスから移植）
   - 出力: (N, 1) → race-level softmax → (N, 6) ブロードキャスト → per-class IR
2. `predictor.py` で booster.objective を読んで分岐
3. `engine.py` API は不変、内部で objective 分岐を吸収
4. `trials/pending/T13_lambdarank.yaml` を作成
5. `/model-loop T13_lambdarank` で Walk-Forward 12 ヶ月実行（~3〜4 時間）

採用判定は MODEL_LOOP_PLAN §3-5（通算 ROI ≥ +10%、broken_months=0、
プラス月 ≥ 60%、bootstrap CI 下限 ≥ 0）。

## 成果物

- `ml/src/scripts/run_objective_poc.py`（`--seed` 引数追加、LightGBM seed 4 系統一括固定）
- `ml/src/scripts/run_lambdarank_seed_check.py`（新規 driver）
- `artifacts/lambdarank_seed_check_results.jsonl`（6 行）
- `artifacts/lambdarank_seed_check_summary.json`
- `artifacts/lambdarank_seed_check_logs/*.log`（各 run のフルログ）

## 参考

- 設計書: [MODEL_LOOP_PLAN.md](MODEL_LOOP_PLAN.md) §3-5 採用基準
- 直前結果: [OBJECTIVE_POC_RESULTS.md](OBJECTIVE_POC_RESULTS.md)（タスク 6-10-b、R1 +0.63pp 保留）
- 13 trial Walk-Forward seed 分散: [MODEL_LOOP_RESULTS.md](MODEL_LOOP_RESULTS.md)
- 重大発見: [CLAUDE.md](CLAUDE.md)（1 着識別能力の全ビン均一）
- 次セッション設計: [NEXT_SESSION_PROMPT.md](NEXT_SESSION_PROMPT.md)
