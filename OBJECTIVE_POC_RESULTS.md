# OBJECTIVE_POC_RESULTS — 目的関数変更 PoC 結果（タスク 6-10-b）

最終更新: 2026-04-25
対象: AUTO_LOOP_PLAN フェーズ 6 タスク 6-10-b「構造変更フェーズ：目的関数変更」

## 背景

- フェーズ 6 のパラメータ探索は通算 13 trial で verdict=pass 再現 0 本、撤退判定済み
- タスク 6-10-a 特徴量拡張 PoC は採用 0 件で撤退（[FEATURE_POC_RESULTS.md](FEATURE_POC_RESULTS.md)）
  - top-1 accuracy ±0.3pp の範囲で揺れただけ
  - mlogloss / ECE は微改善するが、CLAUDE.md「重大発見」=「1 着識別能力が全予測ビンで均一」は特徴量で解けないことを確認
- 残る構造変更ツリー（MODEL_LOOP_PLAN §5）: **目的関数変更** → キャリブレーション再設計 → Purged CV
- 目的関数変更が次の本命: 1 着識別に学習目的を絞り込む方向

## 実装方針（合意事項 2026-04-25）

`ml/src/model/trainer.py` / `predictor.py` / `engine.py` は**変更しない**。
PoC は新規スクリプト `ml/src/scripts/run_objective_poc.py` に閉じ込める。
改善が見えた目的関数のみ、別タスクで trainer.py 統合を検討する。

## 実行条件（共通）

| 項目 | 値 |
|---|---|
| train 期間 | 2023-01 〜 2025-11 |
| val 期間 | 2025-12（単月、~28k サンプル / ~4,718 races） |
| 特徴量 | ベースライン 12 次元（タスク 6-10-a の知見：追加特徴量で top-1 改善せず） |
| LGB params | learning_rate=0.05, num_leaves=63, min_child_samples=50, feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=5 |
| num_boost_round | 1000（早期停止 50） |
| ハーネス | `ml/src/scripts/run_objective_poc.py` |
| 結果保存 | `artifacts/objective_poc_results.jsonl`（1 行/run） |

## 採用判断基準（プロトコル）

タスク 6-10-a より厳しめに設定（目的関数変更は実装コスト大）:

- **採用**: top-1 accuracy +1.0pp 以上
- **保留**: top-1 accuracy +0.5〜+1.0pp（複合検証や Walk-Forward に進む価値あり）
- **却下**: top-1 accuracy +0.5pp 未満

## 試行 4 種

| code | objective | 概要 |
|---|---|---|
| baseline | `multiclass` (num_class=6) | trainer.py と同一の学習。本ハーネスでは IsotonicRegression キャリブレーション無し（apples-to-apples 比較のため） |
| **B1** | `binary` | 各艇を独立に「1 着 か / そうでないか」の二値分類。予測 prob をレース内で sum-to-1 正規化 |
| **R1** | `lambdarank` | `group=race`、relevance = `5 - finish_position`（1 着=5, 6 着=0）。`label_gain=[0,1,3,7,15,31]` |
| **P1** | `rank_xendcg` | LambdaRank の比較対照（pairwise xendcg） |

ranking 系（R1/P1）は `_sort_for_ranking` で race_id 順にデータを並べ替えてから group ベクトルを構築。

## 結果テーブル

| tag | top-1 acc | NDCG@1 | NDCG@3 | ECE_rank1 (raw) | best_iter |
|---|---:|---:|---:|---:|---:|
| baseline_multiclass | **0.5710** | **0.6910** | **0.7608** | 0.00670 | 212 |
| B1_binary | 0.5698 | 0.6894 | 0.7590 | 0.00520 | 188 |
| **R1_lambdarank** | **0.5773** | **0.6969** | **0.7645** | 0.01261 | 103 |
| P1_rank_xendcg | 0.5749 | 0.6936 | 0.7622 | 0.07735 | 68 |

baseline 比の差:

| tag | Δtop-1 | ΔNDCG@1 | ΔNDCG@3 | 判定 |
|---|---:|---:|---:|---|
| B1_binary | **-0.13pp** | -0.16pp | -0.18pp | **却下**（top-1 低下） |
| **R1_lambdarank** | **+0.63pp** | **+0.59pp** | **+0.37pp** | **保留**（+0.5〜+1.0pp 帯、唯一の改善） |
| P1_rank_xendcg | **+0.39pp** | +0.27pp | +0.14pp | **却下**（+0.5pp 未満） |

## 主要所見

### 1. 採用基準（+1.0pp）達成は 0 件

タスク 6-10-a と同じく **+1.0pp 改善は得られなかった**。
ただし R1 (LambdaRank) は **+0.63pp で唯一の保留ゾーン入り**。

### 2. R1 (LambdaRank) が単月 val では最良

- top-1: 0.5773（baseline +0.63pp、B1 +0.75pp、P1 +0.24pp）
- NDCG@1: 0.6969（baseline +0.59pp）
- NDCG@3: 0.7645（baseline +0.37pp）

「1 着 vs 2-6 着」だけでなく「1〜3 着の順位識別」も改善方向。
学習が早期収束（best_iter=103、baseline 212 の半分以下）しており、
ranking 専用 objective が 1 着識別タスクと相性が良い兆候。

### 3. B1 (binary) は失敗

二値分類化で 1 着情報を直接最適化したが top-1 -0.13pp と微低下。
原因仮説: 各艇独立の binary 学習はレース内競合（1 レースで 1 着は 1 艇）を
モデル化しないため、softmax 正規化後の確率分布がノイジーになる可能性。

### 4. P1 (rank_xendcg) は中間

R1 と同じ ranking 系だが top-1 +0.39pp に留まる。
LambdaRank の方が NDCG 直接最適化として強いことが確認できた。
ECE が 0.077 と非常に大きいのは pairwise の score が確率と解釈できず、
softmax 正規化による確率化と実頻度の乖離が大きいため。

### 5. ECE は全 PoC で baseline より悪化

binary は 0.005（生確率は良好）だが、レース内正規化後は 0.019。
ranking 系は 0.013〜0.077。
これらは確率モデルでないので確率質改善は期待できない。
**運用には trainer.py の per-class IsotonicRegression と組み合わせる前提**。

## 結論

目的関数変更 PoC（B1 / R1 / P1）は **採用基準（+1.0pp）達成 0 件** で終了。

ただし **R1 (LambdaRank) は保留ゾーン入り** で、特徴量拡張 PoC（最大 +0.13pp）と
比べると明確に大きい改善幅（+0.63pp）。次手として 2 案ある:

### 案 X: R1 を Walk-Forward 検証へ進める

- 単月 val の +0.63pp が複数月で再現するかを確認
- 12 ヶ月通算 ROI ≥ +10% / worst > -50% / プラス月 ≥ 60% を満たすかを評価
- trainer.py に LambdaRank モードを追加（既存 multiclass モードと共存、`objective` 引数で切替）
- predictor.py / engine.py 互換のため、ranking score → race-level softmax → IsotonicRegression を新規実装

### 案 Y: 構造変更ツリーの次候補へ進む（撤退）

- +0.63pp は「保留」ゾーンであり、Walk-Forward の seed 分散（std 17pp）に
  容易に飲み込まれる規模
- LambdaRank 統合の実装コスト（predictor.py / IR 互換）が大きく、
  ROI 改善保証なしの投資は割に合わない
- MODEL_LOOP_PLAN §5 の次候補「キャリブレーション再設計（per-class IR → 結合 IR / Dirichlet）」
  または「Purged/Embargoed time-series CV」へ進む

**推奨**: 案 Y（撤退）。理由:

1. +0.63pp は単月の seed 分散の範囲内（タスク 6-10-a baseline と本ハーネス baseline で
   top-1 が 0.5748→0.5710 と既に -0.38pp ばらついている：IR キャリブレーションの有無差）
2. R1 の改善幅が「seed ノイズ」か「真の構造改善」か単月では区別不能
3. 仮に Walk-Forward で +0.5pp 程度残っても、CLAUDE.md 重大発見「全ビンで 1 着率均一」が
   解消するレベルではない
4. trainer.py / predictor.py / engine.py 統合の実装コストが大きい（最低 1 セッション、互換性レビュー必須）

## 確定判断（2026-04-25）

**案 Y で確定**（ユーザー承認済み）。次セッションでタスク 6-10-c に着手する:

- 構造変更ツリー §5 の次候補「キャリブレーション再設計（per-class IR → 結合 IR / Dirichlet）」
  または「Purged/Embargoed time-series CV」
- 6-10-b の R1 (LambdaRank) は本セッションでは **Walk-Forward に進めない**
- 将来「キャリブレーション再設計 / Purged CV でも採用基準未達」となった場合に、
  R1 を再評価する選択肢として残す（OBJECTIVE_POC_RESULTS.md の数値と
  `artifacts/objective_poc_results.jsonl` を保持）
- 次セッション用プロンプト: [NEXT_SESSION_PROMPT.md](NEXT_SESSION_PROMPT.md)（タスク 6-10-c）

## 成果物

- `ml/src/scripts/run_objective_poc.py`（新規）
  - multiclass / binary / lambdarank / rank_xendcg をサポート
  - race_id 連続塊化（`_sort_for_ranking`）、NDCG@k 評価（小レース対応）
  - trainer.py / predictor.py / engine.py は一切変更せず
- `artifacts/objective_poc_results.jsonl`（4 行: baseline + B1 + R1 + P1）
- `artifacts/objective_poc_logs/*.log`（各 run のフルログ）

## 参考

- 設計書: [MODEL_LOOP_PLAN.md](MODEL_LOOP_PLAN.md) §5 構造変更ツリー
- 直前結果: [FEATURE_POC_RESULTS.md](FEATURE_POC_RESULTS.md)（タスク 6-10-a 撤退判定）
- 13 trial 結果: [MODEL_LOOP_RESULTS.md](MODEL_LOOP_RESULTS.md)（パラメータ探索撤退判定）
- 重大発見: [CLAUDE.md](CLAUDE.md)（1 着識別能力の全ビン均一）
