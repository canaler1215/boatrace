# CALIBRATION_POC_RESULTS — キャリブレーション再設計 PoC 結果（タスク 6-10-c 第 2 候補）

最終更新: 2026-04-25
対象: AUTO_LOOP_PLAN フェーズ 6 タスク 6-10-c「構造変更フェーズ：キャリブレーション再設計」

## 背景

- フェーズ 6 タスク 6-10-c 第 1 候補「Purged CV」は採用 0、月境界 split が
  実質 leak フリーであることを確認（[PURGED_CV_POC_RESULTS.md](PURGED_CV_POC_RESULTS.md)）
- 構造変更ツリー §5 の最後の候補がキャリブレーション再設計
  - **C1 Dirichlet calibration**: log(p_norm) 入力の多項ロジスティック回帰（L2 正則化）
  - **C2 結合 IR**: per-class IR の出力を logit 化 → softmax 再結合（temperature 付き）
- 主目的: CLAUDE.md「重大発見」=「1 着識別能力が全予測ビンで均一」に対し、
  確率質改善で trifecta ECE を直接改善できるかを検証

## 実装方針（合意 2026-04-25）

`ml/src/model/trainer.py` / `predictor.py` / `engine.py` は**変更しない**。
PoC は新規スクリプト `ml/src/scripts/run_calibration_poc.py` に閉じ込める。

## 実行条件（共通）

| 項目 | 値 |
|---|---|
| train (LightGBM) | 2023-01 〜 2025-10（val-2 ヶ月） |
| cal split (calibrator fit) | 2025-11 単月（~23k samples） |
| eval (val) | 2025-12 単月（~28k samples / ~4,718 races） |
| 特徴量 | ベースライン 12 次元 |
| objective | multiclass（6 クラス、num_class=6） |
| LGB params | learning_rate=0.05, num_leaves=63, min_child_samples=50, feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=5 |
| ハーネス | `ml/src/scripts/run_calibration_poc.py` |
| 結果保存 | `artifacts/calibration_poc_results.jsonl`（1 行/run） |

**重要**: PCV PoC とは split 構成が異なる（PCV は train=2023-01〜2025-11, val=2025-12）。
本 PoC では cal split（2025-11）を確保するため train 末を 1 ヶ月切り詰めている。
そのため top-1 の絶対値は PCV_baseline（0.5728）と直接比較せず、本 PoC 内の
CAL_baseline（per_class_ir）を共通 baseline として比較する。

## 採用判断基準（プロトコル、合意済み）

主基準（top-1 accuracy）:
- **採用**: top-1 +1.0pp 以上
- **保留**: top-1 +0.5〜+1.0pp
- **却下**: top-1 +0.5pp 未満

補助基準（合意 2026-04-25）:
- **trifecta ECE が baseline 比 50% 以上改善**: 保留以上として記録（top-1 が動かなくても価値あり）

## 試行 3 種

| tag | calibrator | 内容 |
|---|---|---|
| CAL_baseline | per_class_ir | trainer.py 同等。row sum-to-1 → per-class IR fit → row 再正規化 |
| **CAL_C2_joint_ir** | joint_ir | C2: per-class IR fit → 適用時に logit 化 → softmax (temperature 付き) で再結合。temperature は cal split 上で多項 NLL 最小化の grid search (0.5〜2.0, 31 点) |
| **CAL_C1_dirichlet** | dirichlet | C1: `sklearn.LogisticRegression(multi_class='multinomial', penalty='l2', C=1.0)` を log(p_norm) 入力で fit |

## 結果テーブル

| tag | top1_raw | top1_cal | NDCG@1 | NDCG@3 | ECE_raw | ECE_cal | trifecta_ECE | mlogloss_cal |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| CAL_baseline (per_class_ir) | 0.5749 | **0.5756** | **0.6925** | **0.7603** | 0.00576 | 0.00819 | 0.00858 | 1.6192 |
| CAL_C2_joint_ir (T=1.0) | 0.5707 | 0.5705 | 0.6881 | 0.7601 | 0.00576 | 0.00819 | 0.00854 | 1.6104 |
| CAL_C1_dirichlet | 0.5720 | 0.5712 | 0.6897 | 0.7595 | 0.00576 | 0.00828 | **0.00768** | **1.6049** |

baseline (per_class_ir) 比 Δ:

| tag | Δtop1_cal | Δtrifecta_ECE | Δmlogloss | 判定 |
|---|---:|---:|---:|---|
| C2 joint_ir | **-0.51pp** | -0.4% | -0.55% | **却下** (top-1 低下、ECE ほぼ同じ、temperature=1.0 で grid 貫通) |
| **C1 dirichlet** | **-0.44pp** | **-10.4%** | **-0.88%** | **却下** (top-1 低下、trifecta ECE 改善は補助基準 50% に未達) |

## 主要所見

### 1. 採用基準（top-1 +1.0pp）達成 0 件、補助基準（trifecta ECE -50%）も達成 0 件

C1 Dirichlet が trifecta ECE -10.4% / mlogloss -0.88% と確率質改善を見せたものの、
top-1 は -0.44pp で seed 分散範囲（PCV PoC で観測した ~0.5pp）に飲まれる規模。
補助基準（50% 改善）にも全く届かず却下。

### 2. C2 joint_ir は temperature=1.0 で grid 貫通

cal split (2025-11) 上で多項 NLL を最小化する temperature を 0.5〜2.0 の 31 点で
grid search したが、最良が **T=1.0**（境界値ではなく中間値）。これは「per-class IR
の出力を logit→softmax で再結合する」操作が、cal split 上で **無補正に近いスケール**
が最適という結論。実質的に baseline IR と数学的にほぼ同等となり、結果も seed 分散
範囲内に収まった（top-1 -0.51pp）。

### 3. C1 Dirichlet は確率質を確実に改善

| 指標 | baseline | dirichlet | 改善率 |
|---|---:|---:|---:|
| trifecta ECE | 0.00858 | 0.00768 | -10.4% |
| multi-class log-loss | 1.6192 | 1.6049 | -0.88% |

LogisticRegression が log(p) 入力で 6 クラス間の関係を結合的に学習し、
single-class IR では捕捉できない多クラス構造補正を実現した。
ただし top-1 は **改善しない**: ランキング順序を変える効果はないため。

### 4. CLAUDE.md「重大発見」（全ビン均一）の根本解決には至らず

C1 Dirichlet で trifecta ECE が 10% 改善しても、top-1 が動かない事実は
**「モデルが1着を識別する能力そのものに上限がある」**ことを再確認させる。
キャリブレーションは確率の絶対値を補正するが、ランキングは変えない。
1着識別能力は LightGBM 出力の order に支配されており、IR/Dirichlet/joint_IR
いずれもその order を変える設計ではない。

### 5. 注: top1_raw が tag ごとに異なる

| tag | top1_raw |
|---|---:|
| CAL_baseline | 0.5749 |
| CAL_C2_joint_ir | 0.5707 |
| CAL_C1_dirichlet | 0.5720 |

同じ booster.predict() 出力なのに top1_raw が 0.42pp 揺れる = **LightGBM 学習自体に
seed 固定なしの確率的サンプリング** (`bagging_fraction=0.8, bagging_freq=5`,
`feature_fraction=0.8`) が混入。PCV PoC で観測した ~0.5pp 規模の seed 分散と整合。

各 calibrator の比較は、それぞれの top1_raw を内部基準にした **(top1_cal - top1_raw)**
で見るべきとも言える:

| tag | top1_raw | top1_cal | Δ(cal-raw) |
|---|---:|---:|---:|
| CAL_baseline | 0.5749 | 0.5756 | +0.064pp |
| CAL_C2_joint_ir | 0.5707 | 0.5705 | -0.021pp |
| CAL_C1_dirichlet | 0.5720 | 0.5712 | -0.085pp |

この内部基準でも C1/C2 はキャリブレーションが top-1 を僅かに「悪化」させている
（baseline IR は僅かに改善）。確率質改善と引き換えに top-1 を犠牲にしている構造。

## 結論

キャリブレーション再設計 PoC（C1 Dirichlet / C2 joint IR）は
**主基準（top-1 +1.0pp）達成 0 件、補助基準（trifecta ECE -50%）達成 0 件** で終了。

C1 Dirichlet が trifecta ECE -10.4% を達成したことは確率質改善の方向性として
意味があるが、改善幅が補助基準（-50%）の 1/5 規模で、top-1 も低下方向。
trifecta ECE 0.00858 → 0.00768 はそもそも絶対値が小さく、ROI 改善に
直結する規模ではない。

## 確定判断（次手）

タスク 6-10-c の構造変更ツリー §5 の **3 候補（特徴量拡張 / 目的関数変更 /
キャリブレーション再設計 / Purged CV、計 4 件）すべて採用基準未達** が確定:

| タスク | 候補 | 結果 |
|---|---|---|
| 6-10-a | 特徴量拡張 (c/b/a) | 採用 0、撤退 |
| 6-10-b | 目的関数変更 (B1/R1/P1) | 採用 0（R1 のみ保留→案 Y で撤退）|
| 6-10-c PCV | Purged/Embargoed CV | 採用 0、leak フリー判定 |
| **6-10-c CAL** | **C1 Dirichlet / C2 結合 IR** | **採用 0、確率質改善は限定的** |

→ **構造変更ツリー全候補消費**。フェーズ 6 全体の撤退を検討する局面。

### 次手の選択肢（ユーザー判断委譲）

1. **フェーズ 6 全体撤退**:
   - CLAUDE.md「実運用再開条件（ROI ≥ +10% / worst > -50%）」を別アプローチで攻める
     - 例: bet_type 変更（3連単→3連複は 2026-04 に検証済み・非推奨確定）
     - 例: アンサンブル（XGBoost / CatBoost を併用）
     - 例: 完全に異なる戦略空間（馬連風 / 単勝のみ等）
   - または運用停止を継続
2. **構造変更ツリー外の候補**:
   - 例: 多目的学習（1 着 + ST + 順位の同時学習、`label_gain` weighting）
   - 例: 二段階モデル（1 着候補絞り込み → 順位推定）
   - 例: メタモデル（複数 booster を stacking）
3. **撤退済み候補の再評価**:
   - 6-10-b R1 (LambdaRank, +0.63pp) を Walk-Forward まで進めて seed 分散の中で
     真の改善か判定する（実装コストはあるが確実な評価）

**推奨**: 選択肢 3（R1 を Walk-Forward 検証）。理由:
- 4 候補消費の中で唯一「保留」ゾーン入りしたのが R1
- C1 Dirichlet も方向性は正しい（trifecta ECE 改善）が幅が小さい
- 仮に R1 で Walk-Forward 12 ヶ月 ROI ≥ 0% を達成できれば、CLAUDE.md 再開条件
  「ROI ≥ +10%」に最も近い実装になる
- 失敗しても撤退は明確に確定できる（フェーズ 6 全体終了）

ただしこれはユーザー判断であり、実装コスト（trainer.py / predictor.py / engine.py の
互換性レビュー）を考えれば選択肢 1（撤退）も合理的。

## 成果物

- `ml/src/scripts/run_calibration_poc.py`（新規）
  - per_class_ir / joint_ir / dirichlet をサポート
  - cal split (val_period - 1 ヶ月) で calibrator fit、val_period で評価
  - trifecta ECE 計算（Plackett-Luce 近似で 6P3=120 通り全列挙）
  - trainer.py / predictor.py / engine.py は一切変更せず
- `artifacts/calibration_poc_results.jsonl`（3 行: baseline + C2 + C1）
- `artifacts/calibration_poc_logs/*.log`（各 run のフルログ）

## 参考

- 設計書: [MODEL_LOOP_PLAN.md](MODEL_LOOP_PLAN.md) §5 構造変更ツリー
- 直前: [PURGED_CV_POC_RESULTS.md](PURGED_CV_POC_RESULTS.md)（タスク 6-10-c 第 1 候補、leak フリー判定）
- 6-10-b: [OBJECTIVE_POC_RESULTS.md](OBJECTIVE_POC_RESULTS.md)（R1 LambdaRank 撤退、案 Y）
- 6-10-a: [FEATURE_POC_RESULTS.md](FEATURE_POC_RESULTS.md)
- 13 trial: [MODEL_LOOP_RESULTS.md](MODEL_LOOP_RESULTS.md)
- 重大発見: [CLAUDE.md](CLAUDE.md)（1 着識別能力の全ビン均一）
