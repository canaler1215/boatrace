# LAMBDARANK_WALKFORWARD_RESULTS — R1 LambdaRank 本体統合 + Walk-Forward 12 ヶ月（タスク 6-10-d Step 4-7）

最終更新: 2026-04-25（Step 7: seed 反復 3 本まで拡張、案 C 完了）
対象: AUTO_LOOP_PLAN フェーズ 6 タスク 6-10-d Step 4-7

## 背景

- フェーズ 6 構造変更ツリー §5 全 4 候補（特徴量拡張 / 目的関数変更 / Purged CV /
  キャリブレーション再設計）が採用 0 件で終了
- 6-10-b で R1 (LambdaRank) のみ単月 val (2025-12) で baseline +0.63pp の保留入り
- 6-10-d Step 1（[LAMBDARANK_SEED_CHECK_RESULTS.md](LAMBDARANK_SEED_CHECK_RESULTS.md)）で
  seed=42/123/7 反復により Δ_obs=+0.609pp、std_pooled=0.241pp、**verdict=go**
  （seed ノイズではない、Walk-Forward 検証に進む価値あり）
- Step 2-3 で trainer.py / predictor.py / engine.py / run_walkforward.py に
  lambdarank モードを統合（multiclass 後方互換、smoke + 91 tests 全 pass）

## 実行条件

| 項目 | 値 |
|---|---|
| trial_id | T13_lambdarank |
| Walk-Forward 期間 | 2025-05 〜 2026-04（12 ヶ月） |
| retrain_interval | 3 ヶ月（学習 4 回） |
| train_start | 2023-01（baseline T00 と同一） |
| sample_weight | null |
| objective | lambdarank |
| label_gain | [0, 1, 3, 7, 15, 31] |
| ndcg_eval_at | [1, 3] |
| seed | 42（4 系統一括固定） |
| 特徴量 | ベースライン 12 次元 |
| strategy | T00 と同一（prob 0.07, EV 2.0, min_odds 100, exclude_stadiums 10 場、bet 100 円）|
| 実オッズ | あり |
| 実行時間 | 444 秒（~7.4 分）※ retrain 4 回のみ、odds は cache hit |

## 採用判定基準（MODEL_LOOP_PLAN §3-5、CLAUDE.md 実運用再開条件と整合）

- pass: 通算 ROI ≥ +10% **かつ** broken_months=0 **かつ** プラス月 ≥ 60% **かつ** bootstrap CI 下限 ≥ 0
- marginal: 通算 ROI ≥ 0 **かつ** broken_months=0
- fail: 上記いずれも未達

## 結果

### 主要 KPI（T13_lambdarank vs 比較対象）

| 指標 | T13_lambdarank | T00_baseline (multiclass) | T07_window_2024_plus_weight (現状唯一の pass) |
|---|---:|---:|---:|
| verdict | **fail** | fail | pass |
| 通算 ROI | **-7.1%** | -6.6% | +15.3% |
| worst_month_roi | **-56.3%** | -43.2% | -35.2% |
| broken_months (< -50%) | **1**（2025-09） | 0 | 0 |
| プラス月比率 | **41.7%**（5/12） | 50.0% | 66.7% |
| bootstrap CI 下限（90%） | **-23.2** | -13.3 | +1.9 |
| 的中率/bet | 0.289% | — | — |
| 的中時平均オッズ | 321x | — | — |
| total_bets | 55,311 | — | — |
| best_month_roi | +93.9%（2025-12） | — | — |
| ECE rank-1 calibrated | 0.00671 | — | — |

### 月次 ROI

| 月 | ROI |
|---|---:|
| 2025-05 | +38.9% |
| 2025-06 | -48.6% |
| 2025-07 | -44.2% |
| 2025-08 | +13.2% |
| 2025-09 | **-56.3%**（broken）|
| 2025-10 | -35.4% |
| 2025-11 | -4.8% |
| 2025-12 | +93.9% |
| 2026-01 | -44.1% |
| 2026-02 | +17.8% |
| 2026-03 | -40.9% |
| 2026-04 | +39.6% |

平均 ROI -7.1%、月次標準偏差 ~50pp（極めて高分散）。

### 採用基準への当てはめ

| 条件 | 閾値 | T13 実績 | 判定 |
|---|---|---:|---|
| 通算 ROI ≥ +10% | ≥ 10% | -7.1% | ❌ |
| broken_months = 0 | 0 | 1 | ❌ |
| プラス月比率 ≥ 60% | ≥ 60% | 41.7% | ❌ |
| bootstrap CI 下限 ≥ 0 | ≥ 0 | -23.2 | ❌ |

→ **verdict = fail（4 条件すべて未達）**

## 主要所見

### 1. 単月 top-1 改善は ROI に転化しなかった

Step 1 で確認した「R1 LambdaRank の +0.609pp top-1 改善（seed ノイズ域外）」は
**Walk-Forward 12 ヶ月の通算 ROI には現れなかった**。

- T13 ROI -7.1% は T00 baseline (-6.6%) と統計的に区別不能（範囲内）
- 月次 best (+93.9%) と worst (-56.3%) の幅が 150pp と巨大、std_pooled で見た
  単月 top-1 改善（0.241pp）は本質的に noise floor 以下に埋没
- ECE は良好（0.0067）で確率質は維持されているが、ROI ロジック（prob 0.07 +
  EV 2.0 + min_odds 100x）の閾値超え/未超えに lambdarank の改善が効いていない

### 2. T07 (現状唯一の pass) との比較

| 観点 | T07 | T13 |
|---|---|---|
| 学習窓 | 2024 開始（短期） | 2023 開始 |
| sample_weight | recency 強重み | なし |
| objective | multiclass | lambdarank |

T07 は **学習窓 + sample_weight** で +15.3% を達成、T13 は **objective だけ変更**して
-7.1%。同じ T00 ベースから出発して **「データの選び方」のほうが「目的関数」より
ROI に効いた**ことを意味する。ただし T07 自身も seed 反復（T10/T11）で
ROI std 17pp が確認されており、seed 1 本での pass は確証としては弱い。

### 3. 重大発見「全ビン均一」は解消していない

CLAUDE.md「1 着識別能力の全ビン均一」問題は、ranking 系 objective でも改善せず。
ndcg@1=0.70 (T13 retrain 1 回目) という比較的高い値が出ているが、これは
「6 艇中で最も 1 着らしい艇を当てる」性能であり、**「特定の予測確率帯で実際勝率が
予測より高い」セグメントの発見**とは別問題。本タスクでは未解決のまま。

### 4. broken_months が出た 2025-09 の特徴

| 月 | ROI | best_iter（直前 retrain） |
|---|---:|---:|
| 2025-09 | -56.3% | 188（2025-04 学習）|

retrain 直後の 2025-08（+13.2%）と比べて 2025-09 だけ局所的に崩壊。
ranking 系の確率分布が IR キャリブレーション後も特定月のオッズ分布と整合しなかった
可能性が高い。multiclass T00 の 2025-09 は -23.5%（崩壊なし）だったため、
**ranking 系のほうが特定月で過大確信に振れる**サインとも読める。

## 結論: フェーズ 6 撤退確定

構造変更ツリー §5 全 4 候補 + 保留候補 R1 LambdaRank すべて採用基準未達。

| タスク | 内容 | 結果 |
|---|---|---|
| 6-1〜6-9 | パラメータ探索（学習窓・sample_weight・LightGBM ハイパラ） | T07 のみ marginal pass、seed 反復で確証不足 |
| 6-10-a | 特徴量拡張 PoC | 採用 0 |
| 6-10-b | 目的関数変更 PoC | R1 のみ +0.63pp 保留、本タスクで解消 |
| 6-10-c PCV | Purged/Embargoed CV PoC | 採用 0、leak フリー判定 |
| 6-10-c CAL | C1 Dirichlet / C2 結合 IR PoC | 採用 0 |
| **6-10-d** | **R1 LambdaRank 本体統合 + Walk-Forward** | **fail（本ドキュメント）** |

CLAUDE.md「実運用再開条件」（通算 ROI ≥ +10% かつ最悪月 > -50%）を、
モデル側の設計改善（特徴量 / 目的関数 / CV / Calibration / Ranking）で
クリアすることはできなかった。

## Step 7: seed 反復 3 本による撤退判定の確証（案 C 実施、2026-04-25）

T13 の verdict=fail は seed=42 1 本のみで、T07/T10/T11 で Walk-Forward seed 反復
ROI std 17pp が確認されているため、撤退判定の確証として補強を実施。
T14 (seed=123) / T15 (seed=7) を追加実行し、3 trial で集計。

### 3 trial 結果（同設定、seed のみ変更）

| trial_id | seed | verdict | ROI | worst_month | プラス月 | broken | CI_low |
|---|---:|---|---:|---:|---:|---:|---:|
| T13_lambdarank | 42 | fail | -7.1% | -56.3% | 41.7% | 1 | -23.2 |
| T14_lambdarank_seed123 | 123 | **fail** | **-16.8%** | **-59.1%** | **25.0%** | **2** | **-26.7** |
| T15_lambdarank_seed7 | 7 | fail | -6.1% | -40.5% | 33.3% | 0 | -20.2 |
| **mean** | — | — | **-10.0%** | **-52.0%** | **33.3%** | **1.0** | **-23.4** |
| **std (ddof=1)** | — | — | **5.9pp** | **10.0pp** | **8.3%** | **1.0** | **3.3** |
| min | — | — | -16.8% | -59.1% | 25.0% | 0 | -26.7 |
| max | — | — | -6.1% | -40.5% | 41.7% | 2 | -20.2 |

### 採用基準（4 条件）への当てはめ

| 条件 | 閾値 | mean | best | 達成数 |
|---|---|---:|---:|---:|
| 通算 ROI ≥ +10% | ≥ +10% | -10.0% | **-6.1%（max）** | **0/3** |
| broken_months = 0 | 0 | 1.0 | 0（T15 のみ） | 1/3 |
| プラス月 ≥ 60% | ≥ 60% | 33.3% | 41.7% | 0/3 |
| bootstrap CI 下限 ≥ 0 | ≥ 0 | -23.4 | -20.2 | 0/3 |

→ **3 trial すべて verdict=fail、最良 seed (T15) でも ROI=-6.1% で +10% 閾値から
   16pp の乖離**。

### 確証の強さ

- **ROI 最良値 -6.13% は、+10% 閾値（pass 必要条件）から 16pp 以上 net 負方向**。
  T07 の seed 反復で観測された ROI std 17pp（T07/T10/T11 = +15.3% / -17.2% / +9.5%）
  と類似の分散（ここでは std 5.9pp、実は T07 比で安定）を考慮しても、
  **lambdarank が真に +10% に到達できる確率は実質ゼロ**
- worst_month は 3 trial すべて -40% 以下、**平均 -52% で broken 域に踏み込み**
- bootstrap CI 下限は 3 trial 全て -20pp 以下、**真の通算 ROI が 0% を上回る
  可能性は統計的に否定**

### 結論: フェーズ 6 撤退の最終確定

3 seed 反復で「lambdarank では実運用再開条件は達成できない」ことを定量的に確証。
**フェーズ 6 完全撤退を確定**。構造変更ツリー §5 全 4 候補 + 保留候補 R1 LambdaRank
の合計 5 系統すべてで採用基準未達となり、モデル側の設計改善で
CLAUDE.md「実運用再開条件」（通算 ROI ≥ +10% / worst > -50%）はクリア不能と確定した。

## 次のアクション（ユーザー判断委譲）

撤退の確証が取れた現状、選択肢は以下の 2 案:

### 案 A: フェーズ 6 完全撤退、運用停止継続

- これ以上モデル側の探索投資は行わない
- 実運用は引き続き停止
- 手動バックテスト・キャリブレーション分析は研究目的で継続可能
- 次に何かを試す動機ができたら新フェーズとして仕切り直す

### 案 B: 全く別のアプローチを新フェーズで開始

候補（いずれもフェーズ 6 の延長ではなく新規企画）:

- **B-1: マーケット観点の改善** — オッズ過小評価（人気馬券バイアス）の活用、
  低確率 × 超高オッズの統計的歪みなど、モデル精度ではなく「市場効率の歪み」狙い
- **B-2: 特徴量の根本見直し** — Kファイル/Bファイル以外のデータソース（SNS、
  ライブオッズ動向、選手コンディション等）導入の費用対効果検討
- **B-3: 戦略フレーム転換** — 3連単固定をやめて 2連複/単勝+EV計算など
  別の馬券種で再出発（CLAUDE.md「3連複検討履歴」と同様の検証）

## 成果物

- `ml/src/model/trainer.py` — lambdarank/rank_xendcg モード追加（race_ids 引数、
  group 構築、ranking 学習、(N,)→race-softmax→(N,6) ブロードキャスト）
- `ml/src/model/predictor.py` — `predict_win_prob(model, X, race_ids=None)` 拡張、
  booster.params.objective 分岐
- `ml/src/backtest/engine.py` — race_ids を predict_win_prob に渡す（multiclass 互換）
- `ml/src/scripts/run_walkforward.py` — ranking objective 時に race_ids を trainer に注入
- `trials/completed/T13_lambdarank.yaml` / `T14_lambdarank_seed123.yaml` / `T15_lambdarank_seed7.yaml`
- `artifacts/walkforward_T13_lambdarank.csv` / `_T14_*.csv` / `_T15_*.csv` + 各 `_summary.json`
- `artifacts/model_loop_T13_lambdarank_*.pkl` × 4 (+ T14/T15 各 4 = 計 12 retrain モデル)
- `trials/results.jsonl`（T13 / T14 / T15 各 1 行追記）
- 既存テスト 91 件すべて pass（multiclass 後方互換確認）

## 参考

- 設計書: [MODEL_LOOP_PLAN.md](MODEL_LOOP_PLAN.md) §3-5
- Step 1: [LAMBDARANK_SEED_CHECK_RESULTS.md](LAMBDARANK_SEED_CHECK_RESULTS.md)
- 6-10-b: [OBJECTIVE_POC_RESULTS.md](OBJECTIVE_POC_RESULTS.md)
- 13 trial 結果: [MODEL_LOOP_RESULTS.md](MODEL_LOOP_RESULTS.md)
- 重大発見: [CLAUDE.md](CLAUDE.md)
- フェーズ 6 計画: [AUTO_LOOP_PLAN.md](AUTO_LOOP_PLAN.md)
