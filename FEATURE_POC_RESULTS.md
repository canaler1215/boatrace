# FEATURE_POC_RESULTS — 特徴量拡張 PoC 結果（タスク 6-10）

最終更新: 2026-04-25
対象: AUTO_LOOP_PLAN フェーズ 6 タスク 6-10「構造変更フェーズ：特徴量拡張」

## 背景

- フェーズ 6 のパラメータ探索は通算 13 trial で verdict=pass 再現 0 本、撤退判定済み（PR #9 / PR #10、`MODEL_LOOP_RESULTS.md`）
- ROI の seed 分散が std 17pp、worst 平均 -47% で構造を問わず大きく、パラメータ枠では CLAUDE.md 実運用再開条件（ROI ≥ +10% かつ worst > -50%）の再現可能達成は困難
- ECE（calibrated）が全 13 trial で 0.001〜0.0016 に飽和、**入力情報追加** による識別能力改善が最有望と判断
- `MODEL_LOOP_PLAN.md §5` 構造変更ツリーから第 1 候補「特徴量拡張」を選択
- `ml/src/features/` の変更禁止指定をユーザーに合意のうえ解除して着手（2026-04-25）

## 実行条件（共通）

| 項目 | 値 |
|---|---|
| train 期間 | 2023-01 〜 2025-11 |
| val 期間 | 2025-12（単月、~28k サンプル） |
| LGB params | trainer.py の LGB_PARAMS（既定） |
| num_boost_round | 1000（早期停止 50） |
| キャリブレーション | softmax 正規化 + per-class IsotonicRegression（trainer.py と同一） |
| ハーネス | `ml/src/scripts/run_feature_poc.py` |
| 結果保存 | `artifacts/feature_poc_results.jsonl`（1 行/run） |

採用判断基準（プロトコル）:

- **採用**: top-1 accuracy +0.5pp 以上 かつ multi-logloss 非悪化
- **保留**: top-1 accuracy ±0.2pp 以内（単独不採用、複合版で再評価）
- **却下**: top-1 accuracy 低下 or multi-logloss 悪化

## 結果テーブル

| tag | n_features | best_iter | top1_acc (raw) | top1_acc (cal) | ECE_rank1 (cal) | mlogloss (cal) |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 12 | 212 | 0.5753 | 0.5748 | 0.00217 | 1.5981 |
| c_st_dispersion | 14 | 261 | 0.5721 | 0.5726 | 0.00140 | 1.5966 |
| b_course_win_rate | 13 | 156 | 0.5735 | 0.5733 | 0.00170 | 1.5985 |
| a_wind_diff | 13 | 208 | 0.5765 | 0.5763 | 0.00217 | 1.5981 |
| **combined_abc** | 16 | 248 | 0.5726 | 0.5719 | 0.00130 | 1.5965 |

baseline 比の差（pp / 絶対値）:

| tag | Δtop1 (raw) | Δtop1 (cal) | ΔECE (cal) | Δmlogloss (cal) | 判定 |
|---|---:|---:|---:|---:|---|
| c_st_dispersion | **-0.32pp** | -0.22pp | -0.00077 (改善) | -0.0015 (改善) | **却下**（top1 低下） |
| b_course_win_rate | **-0.18pp** | -0.15pp | -0.00047 (改善) | +0.0004 (微悪化) | **保留**（境界） |
| a_wind_diff | **+0.13pp** | +0.15pp | ±0.00000 | ≒0 | **保留**（境界、唯一の正方向） |
| combined_abc | **-0.27pp** | -0.29pp | -0.00087 (改善) | -0.0016 (改善) | **却下**（top1 低下） |

## 主要所見

### 1. どの特徴量も採用基準（+0.5pp）を満たさない

4 通り（単独 3 + 複合 1）試したが、top-1 accuracy は ±0.3pp の範囲で揺れただけ。
PoC プロトコル §3 採用判断基準の **採用** は 0 件、**保留** は 2 件（a/b）、**却下** は 2 件（c/combined）。

### 2. mlogloss / ECE は持続的に微改善する

特に複合版は ECE_cal を 0.00217 → 0.00130（**-40%**）、mlogloss_cal を 1.5981 → 1.5965（-0.001）と
全指標で最良。確率分布の質（calibration / log-likelihood）は改善方向にある。

ただし CLAUDE.md の「重大発見」=「1 着識別能力が全予測ビンで均一」を解消するには
**ranking 性能の改善（top-1 accuracy）が必要**であり、この改善は得られなかった。

### 3. PoC c（ST ばらつき）が単独では悪化方向

仮説: 「直近 ST の分散・遅刻率は 1 着識別の核心要素」だったが、`racer_avg_st`（既存 12 次元）と
強く相関し、追加情報が小さく、過学習方向に作用した可能性。best_iteration が 261 と他より長い
（早期停止が効きにくい）のも兆候。

### 4. PoC a（風速差分）が唯一プラスだが微小

stadium 過去平均風速との差分は + 0.13pp と最良だが基準未達。
風向との交互作用（追風 vs 向風 × インコース）等、扱える情報は多いが
本 PoC の単純差分では引き出せていない。

### 5. PoC d は仕様上実装不可能

K ファイル / B ファイルにはモーター ID / ボート ID 列が無く、特定モーターの直近成績は
計算不可能。B ファイルの `motor_win_rate` は当該開催時点の集計値（既に直近寄り）であり、
「期間平均より直近重視」を追加実装する余地がほぼない。

代替案として「racer の指数減衰勝率」も検討したが、既存の `_add_rolling_racer_win_rate`
（直近 3 ヶ月加重平均）との差が小さく、別仮説の試行価値は低いと判断して **PoC d は実装スキップ**。

## 結論

特徴量拡張 PoC（c → b → a → combined）は **採用基準達成 0 件** で終了。
構造変更ツリーの「1. 特徴量拡張」は本データセット・本モデルでは
**識別性能（top-1 accuracy）の改善には寄与しない** ことを確認。

確率質（mlogloss / ECE）は微改善するため、Walk-Forward での ROI 改善余地はゼロではないが、
- 採用基準ゼロ達成
- ECE は元々 0.00217 と十分小さい（trainer.py のキャリブレーションが効いている）
- 13 trial の seed 分散が ROI std 17pp あるため、ECE の 40% 改善が ROI に転写される
  保証は薄い

を踏まえ、**Walk-Forward 検証は実施せず、構造変更ツリーの次候補へ移行** する判断を提案する。

## 次候補（MODEL_LOOP_PLAN §5）

1. ✅ ~~特徴量拡張~~ — 本 PoC で採用 0、撤退
2. **目的関数変更**（binary top-1 / pairwise / LambdaRank）— 1 着識別に的を絞る
3. キャリブレーション再設計（per-class IR → 結合 IR / Dirichlet）
4. Purged/Embargoed time-series CV

「1 着識別能力がランダムに近い」核心問題に対して、特徴量側ではなく **学習目的を 1 着 vs その他の
binary classification や、3 連単直接最適化（LambdaRank）に切り替える** のが
最も筋の良い次手と考えられる。

## 成果物

- `ml/src/features/feature_builder.py` — `extra_features` 引数追加、`EXTRA_FEATURE_REGISTRY` 導入
  - `_add_racer_st_dispersion()` — `racer_st_std` / `racer_late_rate`（PoC c）
  - `_add_wind_speed_diff()` — `wind_speed_diff`（PoC a）
- `ml/src/features/stadium_features.py` — 24×6 場×コース勝率テーブル定数追加
  - `STADIUM_COURSE_WIN_RATE` / `DEFAULT_COURSE_WIN_RATE`
  - `add_stadium_course_features()`（PoC b）
- `ml/src/scripts/run_feature_poc.py` — 単月 val ハーネス（新規）
- `ml/src/scripts/compute_stadium_course_table.py` — 24×6 集計スクリプト（新規）
- `ml/tests/test_feature_st_dispersion.py` — PoC c ユニットテスト 7 件
- `ml/tests/test_feature_stadium_course.py` — PoC b ユニットテスト 5 件
- `ml/tests/test_feature_wind_diff.py` — PoC a ユニットテスト 5 件
- `artifacts/feature_poc_results.jsonl` — 5 行（baseline + 単独 3 + 複合 1）
- `artifacts/feature_poc_logs/*.log` — 各 run のフルログ
- `artifacts/stadium_course_win_rate.json` — 24×6 集計の中間データ

ユニットテスト合計 17 件、全 pass（`py -3.12 -m pytest ml/tests/test_feature_*.py`）。

## 参考

- 設計書: [MODEL_LOOP_PLAN.md](MODEL_LOOP_PLAN.md) §5（探索戦略）§6-4（変更禁止パス、本 PoC で解除合意）
- 直前結果: [MODEL_LOOP_RESULTS.md](MODEL_LOOP_RESULTS.md)（13 trial で pass 再現 0、撤退判定）
- 運用基準: [CLAUDE.md](CLAUDE.md)「重大発見」（1 着識別能力の全ビン均一）
