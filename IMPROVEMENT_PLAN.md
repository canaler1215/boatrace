# ROI改善計画

## 背景

- 購入条件: 的中確率 ≥ 3% AND EV > 1.2、1点100円
- 4/15実績: 150件購入、6件的中（的中率4%）、ROI = -52%（払戻率48%）
- 目標: ROIをプラスに転換する

## 診断された問題点

| # | 問題 | 影響度 | 対象ファイル |
|---|------|--------|-------------|
| P1 | バックテストのEVフィルタが未実装（prob_thresholdのみ） | 高 | engine.py:244 |
| P2 | 合成オッズが粗すぎてEVが過大評価される | 高 | odds_simulator.py |
| P3 | Plackett-Luce近似による3連単確率の誤差 | 高 | predictor.py:23-44 |
| P4 | 学習時にtidal_level=0固定（推論時と乖離） | 中 | feature_builder.py:87-91 |
| P5 | スタジアム特徴量が3場のみ（残り21場はデフォルト値） | 中 | stadium_features.py |
| P6 | モデルのキャリブレーション未確認 | 中 | evaluator.py |
| P7 | train_test_split が random（時系列リーク） | 低 | trainer.py:44 |

---

## セッション別改善タスク

### Session 1: 実態把握（バックテスト基盤整備）
**目標**: 現状のROIを正確に計測できる環境を作る

- [x] BT-1a: バックテストにEV閾値フィルタを追加（P1の修正）
  - `engine.py`: `run_race` / `run_backtest_batch` に `ev_threshold` パラメータ追加
  - `run_backtest.py`: `--ev-threshold`（デフォルト 1.2）引数追加
- [x] BT-1b: 実オッズ × 複数月 Walk-Forward検証スクリプト作成
  - `scripts/run_walkforward.py` 新規作成
  - `--start YYYY-MM --end YYYY-MM --retrain --real-odds` 形式で複数月連続バックテスト
- [x] BT-2: prob_threshold × EV_threshold グリッドサーチ実装
  - `scripts/run_grid_search.py` 新規作成
  - `engine.py` に `collect_combos` モード追加（全120通りの予測データを収集）
  - prob: 0.01〜0.20 × EV: 0.0〜2.0 の56通りを高速スキャン
  - `artifacts/combos_YYYYMM.csv` → `artifacts/grid_search_YYYYMM.csv`
- [x] BT-3: キャリブレーション分析スクリプト作成
  - `scripts/run_calibration.py` 新規作成
  - クラス別 ECE（Expected Calibration Error）計算
  - 3連単確率のキャリブレーション分析
  - `artifacts/calibration_YYYYMM_{class,trifecta,summary}.csv`

**成果物**: `artifacts/calibration_*.csv`, `artifacts/grid_search_*.csv`, `artifacts/walkforward_*.csv`

**次のステップ（Session 1 実行手順）**:
```bash
# 1. Walk-Forward で実績 ROI を正確計測（推奨: --real-odds）
python ml/src/scripts/run_walkforward.py --start 2025-10 --end 2025-12 --retrain --real-odds

# 2. グリッドサーチで最適閾値を探索
python ml/src/scripts/run_grid_search.py --year 2025 --month 12 --real-odds

# 3. キャリブレーション分析（combos CSV が生成されていれば再利用可能）
python ml/src/scripts/run_calibration.py --year 2025 --month 12
```

### Session 2: 特徴量改善
**目標**: 学習データの質を上げてモデル精度を向上させる

- [x] 全24場の1コース勝率を追加（stadium_features.py 拡充）
  - 旧コードのJCDコード誤記バグ修正（4→13=尼崎, 22→24=大村）
  - 全24場の実績値を追加
- [x] tidal_level を学習データに組み込む（月齢×半日周潮モデルによる推定）
  - `tidal_features.py`: `estimate_tidal_level` + `add_tidal_features_estimated` を追加
  - `feature_builder.py`: 歴史データに tidal_level / tidal_type_encoded を推定値で設定（P4修正）
- [x] racer_win_rate の直近3ヶ月加重平均化
  - `feature_builder.py`: `_add_rolling_racer_win_rate` を追加
  - 重み: 1ヶ月前×3, 2ヶ月前×2, 3ヶ月前×1 / 加重レース数≥3で有効
  - 履歴不足の場合はBファイル勝率にフォールバック
- [x] 特徴量重要度・SHAP値の可視化
  - `scripts/run_feature_importance.py` 新規作成
  - LightGBM gain/split importance を CSV + PNG に保存
  - SHAP beeswarm + bar plot を PNG に保存（shap ライブラリ要）

### Session 3: モデル改善
**目標**: 確率推定の精度を上げ、キャリブレーションを適正化する

#### 優先順位（Session 2 分析結果に基づく）

| 優先度 | タスク | 根拠 |
|--------|--------|------|
| 🔴 最優先 | Platt scaling / isotonic regression によるキャリブレーション補正 | 1착 ECE が 0.018→0.140 に 7.6x 悪化。確率過大推定が的中率 6.2%→1.4% 低下の主因 |
| 🟠 高 | 時系列 Walk-Forward 学習への移行（random split 廃止） | random split がキャリブレーション悪化に寄与している可能性 |
| 🟡 中 | 2着・3着の条件付きモデルを独立学習（Plackett-Luce脱却） | キャリブレーション補正後に効果測定 |
| 🟡 中 | ハイパーパラメータ再チューニング | キャリブレーション後に実施 |

- [x] 🔴 キャリブレーション補正（Isotonic Regression）
  - `trainer.py`: val データで各クラス独立に `IsotonicRegression` を学習
  - 保存形式を `{"booster": lgb.Booster, "calibrators": list[IsotonicRegression]}` に変更
  - `predictor.py`: `predict_win_prob` でキャリブレーション補正を自動適用
  - `engine.py`: `model.predict()` → `predict_win_prob()` に切り替え
  - 後方互換性: 旧形式（lgb.Booster 直接）も自動判別・動作
  - 目標: 次回再学習後に 1着 ECE を 0.02 以下に戻す
- [x] 🟠 時系列Walk-Forward学習への移行（random split廃止）
  - `trainer.py`: `train_test_split` を時系列順（最後の 10% を val）に変更
  - `run_retrain.py` / `run_backtest.py`: val split も時系列順に統一
  - P7 の根本修正
- [ ] 🟡 2着・3着の条件付きモデルを独立学習（Plackett-Luce脱却）
- [ ] 🟡 ハイパーパラメータ再チューニング

### Session 4: 購入戦略改善
**目標**: ROIがプラスになるベッティング戦略を確立する

- [x] EV閾値・確率閾値の最適組み合わせをバックテストで特定
  - `run_grid_search.py` に `--filter-overestimation` オプション追加（win_prob<10%のみ対象）
  - フィルタあり/なしの比較を自動出力
- [x] Kelly基準によるベット額の動的調整
  - `engine.py`: `calc_kelly_bet()` 関数追加、`run_race` / `run_backtest_batch` に `kelly_fraction` / `kelly_bankroll` パラメータ追加
  - `run_backtest.py`: `--kelly-fraction`（0.0=固定, 0.25=1/4Kelly推奨）/ `--kelly-bankroll` 引数追加
- [x] 場・艇番・オッズ帯別のセグメント分析
  - `scripts/run_segment_analysis.py` 新規作成
  - 分析軸: 場別・コース別（1着艇番）・オッズ帯別・確率帯別
  - 出力: `artifacts/segment_{stadium,course,odds,prob}_{YYYYMM}.csv`
- [x] calibrated ECE 計測を追加（補正前後のECE比較）
  - `run_calibration.py`: calibrators がある場合に calibrated ECE も計算して比較表示
  - Summary CSV に `ece_calibrated` 列を追加
- [ ] 最終的なROI目標値設定と運用ルール策定  → Session 5 の S5-4 に移動

### Session 5: 購入ルール強化 + キャリブレーション再設計
**目標**: Session 4 分析結果を実装し、ROI を実運用可能レベルに引き上げる

#### Session 4 GH Actions 分析結果まとめ（Session 5 の根拠）

| 発見 | 根拠データ | 対処方針 |
|------|-----------|---------|
| コース2・4・5 が低ROI | コース2: 611%, 4: 468%, 5: 385%（コース1: 2,585%） | 除外フィルタ追加 |
| びわこ が極端低ROI | 607%（全24場中断トツ最下位、次点1,341%） | 場除外フィルタ |
| オッズ~100x が低ROI | ROI 158%（競艇公式75%払戻に近い水準） | オッズ下限フィルタ |
| prob≥7%, EV≥2.0 が最高ROI | 2,369%（現行 prob=3%, EV=1.2: 2,231%） | デフォルト閾値変更 |
| Isotonic Regression が逆効果 | 5/6クラスで ECE 悪化（補正前後でほぼ変化なし） | 温度スケーリングへ変更 |
| EV 閾値が prob 低時に無効 | max_bets=5 × EV 降順ソートで常に上位5件が EV≥2.0 | prob≥7% 設定で解消 |
| 1着確率の構造的歪み | 0-10%ビン: 過小推定(5%→実16%)、30%+ビン: 過大推定3x | Temperature Scaling で修正 |

#### タスク

- [x] S5-1: 購入ルール強化（コース/オッズ/場フィルタ）— **2026-04-16 実装完了**
  - `engine.py`: `run_race` / `run_backtest_batch` に `exclude_courses`, `min_odds`, `exclude_stadiums` パラメータ追加
  - `run_backtest.py`: `--exclude-courses 2 4 5`, `--min-odds 100`, `--exclude-stadiums 11` 引数追加
  - `run_walkforward.py`: 同引数追加
  - `run_grid_search.py`: `apply_thresholds()` / `run_grid_search()` に同フィルタを追加
- [x] S5-2: 温度スケーリングによるキャリブレーション再設計 — **2026-04-16 実装完了**
  - `trainer.py`: IsotonicRegression を廃止 → Temperature Scaling（scipy.optimize で NLL 最小化）
    - `booster.predict(raw_score=True)` でロジットを取得し、温度 T でスケール
    - val データで負対数尤度最小化（bounds=(0.1, 10.0)）により最適 T を探索
  - `predictor.py`: `predict_win_prob` で temperature 優先処理（calibrators は legacy 対応のみ）
  - 保存形式: `{"booster": lgb.Booster, "temperature": float}` に変更（旧形式後方互換維持）
- [ ] S5-3: Walk-Forward 再検証（新ルール + 新キャリブレーション）
  - 再学習（Temperature Scaling）+ 新ルール（コース/オッズ/場フィルタ、prob≥7%, ev≥2.0）で 2025-10〜12 Walk-Forward
  - Session 3 との ROI 比較
  ```bash
  python ml/src/scripts/run_walkforward.py \
    --start 2025-10 --end 2025-12 --retrain --real-odds \
    --prob-threshold 0.07 --ev-threshold 2.0 \
    --exclude-courses 2 4 5 --min-odds 100 --exclude-stadiums 11
  ```
- [ ] S5-4: 最終 ROI 目標値と運用ルールの策定
  - Walk-Forward 結果を踏まえた実運用判断基準の文書化

**Session 5 実行コマンド（実装後）**:
```bash
# 既存 combos CSV で新フィルタ効果を先行検証
python ml/src/scripts/run_grid_search.py \
  --combos-csv artifacts/Session4/combos_202512.csv \
  --exclude-courses 2 4 5 --min-odds 100 --exclude-stadiums 11

# Walk-Forward（新ルール）
python ml/src/scripts/run_walkforward.py \
  --start 2025-10 --end 2025-12 --retrain --real-odds \
  --prob-threshold 0.07 --ev-threshold 2.0 \
  --exclude-courses 2 4 5 --min-odds 100 --exclude-stadiums 11

# 温度スケーリング後のキャリブレーション確認
python ml/src/scripts/run_calibration.py --year 2025 --month 12
```

---

## 現在の進捗

**最終更新**: 2026-04-16
**現在のセッション**: **Session 5 進行中（S5-1/S5-2 実装完了 → S5-3 Walk-Forward 再検証待ち）**

### Session 1 成果物
| ファイル | 内容 |
|---------|------|
| `ml/src/backtest/engine.py` | EV閾値フィルタ追加、combo収集モード追加 |
| `ml/src/scripts/run_backtest.py` | --ev-threshold 引数追加 |
| `ml/src/scripts/run_walkforward.py` | 新規作成：複数月Walk-Forward検証 |
| `ml/src/scripts/run_grid_search.py` | 新規作成：閾値グリッドサーチ |
| `ml/src/scripts/run_calibration.py` | 新規作成：キャリブレーション分析 |

### Session 2 成果物
| ファイル | 内容 |
|---------|------|
| `ml/src/features/stadium_features.py` | 全24場1コース勝率追加・JCDコードバグ修正 |
| `ml/src/features/tidal_features.py` | 月齢推定関数 `estimate_tidal_level` + `add_tidal_features_estimated` 追加 |
| `ml/src/features/feature_builder.py` | P4修正（潮位推定）+ 直近3ヶ月加重平均勝率（`_add_rolling_racer_win_rate`）追加 |
| `ml/src/scripts/run_feature_importance.py` | 新規作成：特徴量重要度・SHAP値可視化 |

### Session 5 成果物（2026-04-16 実装）
| ファイル | 変更内容 |
|---------|------|
| `ml/src/model/trainer.py` | IsotonicRegression廃止 → Temperature Scaling（scipy NLL最小化、`raw_score=True`でロジット取得）保存形式 `{"booster": ..., "temperature": float}` |
| `ml/src/model/predictor.py` | `predict_win_prob`: temperature優先 → calibrators(legacy) → raw の優先順位で適用 |
| `ml/src/backtest/engine.py` | `run_race`/`run_backtest_batch`: `exclude_courses`/`min_odds`/`exclude_stadiums` パラメータ追加 |
| `ml/src/scripts/run_backtest.py` | `--exclude-courses`/`--min-odds`/`--exclude-stadiums` 引数追加 |
| `ml/src/scripts/run_walkforward.py` | 同引数追加 |
| `ml/src/scripts/run_grid_search.py` | `apply_thresholds`/`run_grid_search` に同フィルタ追加 |

### Session 4 成果物（2026-04-16 実装）
| ファイル | 変更内容 |
|---------|------|
| `ml/src/scripts/run_calibration.py` | calibrated ECE 計測追加（補正前後のECE比較・`ece_calibrated`列出力） |
| `ml/src/scripts/run_grid_search.py` | `--filter-overestimation`オプション追加（win_prob<10%フィルタ）、フィルタあり/なし比較出力 |
| `ml/src/backtest/engine.py` | `calc_kelly_bet()`関数追加、`run_race`/`run_backtest_batch`にKellyパラメータ追加 |
| `ml/src/scripts/run_backtest.py` | `--kelly-fraction`/`--kelly-bankroll`引数追加 |
| `ml/src/scripts/run_segment_analysis.py` | 新規作成：場・コース・オッズ帯・確率帯別セグメント分析 |

**Session 4 実行コマンド**:
```bash
# calibrated ECE 分析（補正前後のECE比較）
python ml/src/scripts/run_calibration.py --year 2025 --month 12

# グリッドサーチ（過大推定フィルタあり/なし比較）
python ml/src/scripts/run_grid_search.py --combos-csv artifacts/combos_202512.csv

# セグメント分析（場・コース・オッズ帯・確率帯）
python ml/src/scripts/run_segment_analysis.py --combos-csv artifacts/combos_202512.csv

# 1/4 Kelly バックテスト
python ml/src/scripts/run_backtest.py --year 2025 --month 12 --real-odds \
  --kelly-fraction 0.25 --kelly-bankroll 100000
```

---

## Session 4 → Session 5 移行分析（2026-04-16）

### GH Actions 実行結果（Session 4 検証パイプライン: Grid Search + Segment Analysis + Calibration Analysis）

| ファイル | 内容 |
|---------|------|
| `artifacts/Session4/calibration_202512_summary.csv` | RAW ECE: 1着=0.13288, Calibrated ECE: 0.13343（**補正後が悪化**） |
| `artifacts/Session4/grid_search_202512.csv` | フィルタなしグリッドサーチ（prob×8 × ev×7 = 56通り） |
| `artifacts/Session4/grid_search_202512_filtered.csv` | 過大推定フィルタあり（win_prob<10%限定） |
| `artifacts/Session4/segment_{stadium,course,odds,prob}_202512.csv` | セグメント別 ROI 分析 |
| `artifacts/Session4/combos_202512.csv` | 全コンボデータ（525,840件、再利用可能） |

### キャリブレーション分析結果

| クラス | RAW ECE | Calibrated ECE | 評価 |
|--------|---------|----------------|------|
| 1着 | 0.13288 | 0.13343 | **悪化** |
| 2着 | 0.05260 | 0.05529 | **悪化** |
| 3着 | 0.03558 | 0.04002 | **悪化** |
| 4着 | 0.03244 | 0.03122 | 微改善 |
| 5着 | 0.05489 | 0.05582 | **悪化** |
| 6着 | 0.08920 | 0.09509 | **悪化** |

**根本原因**: 各クラス独立の Isotonic Regression は sum-to-1 制約を破壊するため、Plackett-Luce 計算に悪影響。→ Session 5 で Temperature Scaling（全クラス一括）に変更。

1着 ECE ビン別詳細（RAW）:

| ビン | 予測確率 | 実際的中率 | 乖離 |
|------|---------|----------|------|
| 0-10% | 5.0% | 16.3% | **過小推定 3.3x** |
| 10-20% | 13.7% | 16.8% | ほぼ適正 |
| 30-40% | 34.5% | 15.9% | **過大推定 2.2x** |
| 60-70% | 65.2% | 19.9% | **過大推定 3.3x** |

### グリッドサーチ結果（ベスト組み合わせ）

| prob | EV | ベット数 | ROI | 的中率 | 備考 |
|------|----|---------|-----|-------|------|
| 0.01 | 0.0 | 21,910 | 2,877% | 2.60% | EV 閾値が無効（max_bets=5で解消） |
| **0.07** | **2.0** | **4,791** | **2,369%** | 6.03% | **推奨（ROI/ベット数バランス）** |
| 0.10 | 2.0 | 1,294 | 2,354% | 7.50% | ベット数少なすぎ |
| 0.03 | 1.2 | 21,359 | 2,231% | 3.82% | 現行設定 |

### セグメント分析結果

**コース別 ROI（除外候補）**:

| コース | ROI | 的中数 | 判定 |
|-------|-----|-------|------|
| 1 | 2,585% | 666 | 維持 |
| 3 | 2,683% | 69 | 維持 |
| 2 | **611%** | 63 | **除外候補** |
| 4 | **468%** | 11 | **除外候補** |
| 5 | **385%** | 3 | **除外候補** |

**オッズ帯別 ROI**:

| オッズ帯 | ROI | 判定 |
|---------|-----|------|
| ~100x | **158%** | **除外候補** |
| 100-300x | 603% | 維持 |
| 300-1000x | 1,754% | 維持 |
| 1000x+ | 8,864% | 積極維持 |

**場別 ROI（下位）**:

| 場 | ROI | 判定 |
|----|-----|------|
| びわこ (ID=11) | **607%** | **除外候補（唯一の突出した低ROI）** |
| 平和島 (ID=4) | 1,341% | 要観察 |

### Session 5 移行の判断

**→ Session 5 (購入ルール強化) を優先する**。理由:

1. **即時効果が期待できる**: コース/オッズ/場フィルタは既存 combos CSV で先行検証可能
2. **キャリブレーションが根本課題**: Temperature Scaling により ECE 改善 + Plackett-Luce 精度向上が期待できる
3. **combos CSV 再利用可能**: 再バックテスト不要で新フィルタ効果を素早く計測できる

---

### Session 3 成果物（2026-04-16 実装）
| ファイル | 変更内容 |
|---------|------|
| `ml/src/model/trainer.py` | ①random split→時系列split(P7修正) ②IsotonicRegression calibrator学習・dict形式保存 |
| `ml/src/model/predictor.py` | `load_model`: dict/Booster 両形式対応。`predict_win_prob`: calibrator 自動適用 |
| `ml/src/backtest/engine.py` | `model.predict()` → `predict_win_prob()` に切り替え（全バックテストに calibration が反映） |
| `ml/src/scripts/run_retrain.py` | val split を時系列順に統一、dict形式のbooster抽出に対応 |
| `ml/src/scripts/run_backtest.py` | val split を時系列順に統一、dict形式のbooster抽出に対応 |
| `ml/src/scripts/run_calibration.py` | dict形式から booster を取り出して raw probs を分析するよう修正 |
| `ml/src/scripts/run_feature_importance.py` | `_load_model`: dict形式から booster を取り出すよう修正 |

---

## Session 3 → Session 4 移行分析（2026-04-16）

### GH Actions 実行結果（Session 3 検証パイプライン: 再学習→キャリブレーション→Walk-Forward）

| ファイル | 内容 |
|---------|------|
| `artifacts/Session3/model_metrics.txt` | version=202604, rps=0.1565, top1_accuracy=31.45%, samples=1,403,845 |
| `artifacts/Session3/calibration_202512_summary.csv` | RAW ECE: 1着=0.14178（Session 2と同等） |
| `artifacts/Session3/walkforward_202510-202512.csv` | Session 3 Walk-Forward 結果（実オッズ） |

### Walk-Forward 全セッション比較

| 指標 | Session 1 | Session 2 | Session 3 | S2→S3変化 |
|------|-----------|-----------|-----------|-----------|
| ベット数 | 37,868 | 40,787 | 38,057 | -6.7% |
| 投資額 | 3,786,800円 | 4,078,700円 | 3,805,700円 | -6.7% |
| 払戻額 | 99,355,660円 | 23,550,890円 | 23,428,190円 | -0.5% |
| 的中数 | 2,344 | 574 | 541 | -5.7% |
| 的中率/bet | **6.19%** | 1.41% | 1.42% | ≒同等 |
| ROI | **+2,524%** | +477% | +515.6% | +38pp改善 |
| avg top_prob | 0.048 | 0.065 | 0.0700 | +7.7%↑ (悪化) |
| avg matched_odds | 424x | 410x | 433x | ほぼ同等 |
| 1着 ECE (raw) | 0.018 | 0.1396 | 0.1418 | ほぼ同等 |

### Session 3 重大発見

**キャリブレーション補正の効果が限定的** — 以下の問題を確認:

1. **的中率/bet が変化なし** (1.41% → 1.42%): Isotonic Regression を適用したはずが、的中率は改善していない
2. **avg top_prob が増加** (0.065 → 0.070): キャリブレーション後は確率が下がるはずが、逆に増加 → calibrated ECE は未計測のため効果不明
3. **trifecta ECE が深刻** (Session 3 raw):

| 予測確率ビン | サンプル数 | 予測確率 | 実際勝率 | 乖離倍率 |
|------------|---------|--------|--------|---------|
| 0-10% | 548,342 | 0.76% | 0.83% | **良好** |
| 10-20% | 3,031 | 12.8% | 1.68% | **7.6x 過大推定** |
| 20-30% | 137 | 22.9% | 0.73% | **31x 過大推定** |

### 根本原因

**Plackett-Luce近似が高確率域で 7〜31倍の過大推定を生む** → EV = P_model × odds が実態より大幅に過大評価される。

- EV フィルタ (EV > 1.2) を通過した combos の実際勝率は 1.4%
- 1着 ECE の Isotonic Regression は「各クラス独立キャリブレーション」のため、レース内確率の sum-to-1 制約が壊れ Plackett-Luce 計算に悪影響している可能性あり

### Session 4 移行の判断

**→ Session 4 (購入戦略改善) を優先する**。理由:

| 理由 | 詳細 |
|------|------|
| Session 3 主要タスク完了 | キャリブレーション + 時系列 split は実装済み |
| 残 Session 3 タスクの前提条件未整備 | 2착・3착独立モデルはキャリブレーション正常動作が前提。ROI改善効果が現状では計測困難 |
| Session 4 インフラ整備済み | grid_search.py・collect_combos モードが既に実装済み。即実行可能 |
| 閾値最適化で trifecta 過大推定に対処可能 | prob_threshold / EV_threshold を上げれば高確率帯の選択を回避できる |
| Kelly criterion が自然なリスク制御になる | 確率過大推定への対策として bet size を縮小する効果 |

**Session 3 残タスクの扱い**:
- 🟡 2着・3着独立モデル → Session 4 グリッドサーチの結果次第でSession 5 以降に
- 🟡 ハイパーパラメータ再チューニング → Session 4 後に実施

**Session 4 で最初に確認すべきこと**:
1. `run_calibration.py` に calibrated ECE 計測を追加（補正後確率の ECE を計算）
2. グリッドサーチで prob_threshold を高め（≥5%, ≥7%）に設定した場合の ROI 確認
3. trifecta 過大推定ビン（10-20%）に入る combos を除外した場合の ROI 確認

---

## Session 2 → Session 3 移行分析（2026-04-16）

### GH Actions 実行結果（Session 2 特徴量改善後）

| ファイル | 内容 |
|---------|------|
| `artifacts/model_metrics.txt` | version=202604, rps=0.1567, top1_accuracy=31.16%, samples=1,403,845 |
| `artifacts/shap_importance_202512.csv` | boat_no が SHAP 0.716 でダントツ1位 |
| `artifacts/walkforward_202510-202512.csv` | 新 Walk-Forward 結果 |
| `artifacts/calibration_202512_summary.csv` | 新 ECE: 1착=0.1396 |
| `artifacts/calibration_202512_summary_old.csv` | 旧 ECE: 1착=0.018（比較用） |

### 重大発見: キャリブレーションの大幅悪化

| クラス | 旧 ECE | 新 ECE | 悪化倍率 |
|--------|--------|--------|---------|
| 1着 | 0.0185 | 0.1396 | **7.6x** |
| 2着 | 0.0088 | 0.0573 | 6.5x |
| 3着 | 0.0082 | 0.0364 | 4.4x |
| 4着 | 0.0069 | 0.0367 | 5.3x |
| 5着 | 0.0069 | 0.0579 | 8.4x |
| 6着 | 0.0177 | 0.0850 | 4.8x |
| trifecta | 0.000242 | 0.000242 | 変化なし（※） |

※ trifecta ECE は低確率ビン（0-0.1）が 99%以上を占めるため表面上は良好。実際は相対的に誤差あり。

### Walk-Forward 比較: 旧モデル vs 新モデル

| 指標 | Session 1 モデル（旧） | Session 2 モデル（新） | 変化 |
|------|---------------------|---------------------|------|
| ベット数 | 37,868 | 40,787 | +8% |
| 的中数 | 2,344 | 574 | **-75%** |
| 的中率/bet | 6.19% | 1.41% | **-4.4x** |
| ROI | +2,524% | +477% | ▼ 大幅低下 |
| avg top_prob | 0.048 | 0.065 | +35%（確率過大推定） |
| avg top_EV | 72 | 119 | +65% |

### 問題の根本原因

**Session 2 特徴量改善が ECE を 7.6x 悪化させた**。具体的には:

1. **確率過大推定**: 新モデルは各レースの最高確率を 0.048 → 0.065（+35%）に推定
2. **EV 過大評価**: EV = P_model × odds なので EV も 65% 増加
3. **しきい値通過増加**: EV>1.2 を満たすコンボが増え、的中率が下がった
4. **容疑**: 潮位推定値（tidal_level）の学習データへの組み込み（P4修正）または直近勝率ロールアップが確率の歪みを引き起こした可能性

### SHAP 特徴量重要度（新モデル、2025-12）

| 特徴量 | SHAP値 | 備考 |
|--------|--------|------|
| boat_no | 0.716 | 圧倒的1位（ポジションバイアス強い） |
| racer_win_rate | 0.268 | |
| racer_grade_encoded | 0.251 | |
| racer_avg_st | 0.196 | |
| exhibition_time | 0.103 | 有効なシグナル |
| in_win_rate | 0.060 | |
| motor_win_rate | 0.048 | |
| wind_speed | 0.041 | |
| tidal_level | 0.032 | **P4修正の効果は小** |
| boat_win_rate | 0.031 | |
| wind_direction_encoded | 0.007 | |
| tidal_type_encoded | 0.002 | ほぼ無効 |

### Session 3 進行の判断

**Session 3 を即座に開始する**。理由:
- ROI は +477% と依然プラス（破綻ではない）
- ECE 悪化の直接的な修正は Session 3 のキャリブレーション補正タスク
- 時系列 split への移行も ECE 悪化への対処として有効
- 旧モデル（ECE 0.018）でもキャリブレーション補正は有益

---

## Walk-Forward 分析結果（2025-10 〜 2025-12）

### Session 1 モデル（prob≥3%, EV≥1.2, 実オッズ）

| 月 | ベット数 | 投資額 | 払戻額 | 的中数 | ROI |
|----|---------|--------|--------|--------|-----|
| 2025-10 | 11,973 | 1,197,300円 | 30,470,150円 | 721 | +2,445% |
| 2025-11 | 11,601 | 1,160,100円 | 28,474,940円 | 726 | +2,355% |
| 2025-12 | 14,294 | 1,429,400円 | 40,410,570円 | 897 | +2,727% |
| **計** | **37,868** | **3,786,800円** | **99,355,660円** | **2,344** | **+2,524%** |

**1착 ECE**: 0.018（良好）｜**的中率/bet**: 6.2%

### Session 2 モデル（prob≥3%, EV≥1.2, 実オッズ）

| 月 | ベット数 | 投資額 | 払戻額 | 的中数 | ROI |
|----|---------|--------|--------|--------|-----|
| 2025-10 | 12,685 | 1,268,500円 | 5,364,650円 | 137 | +322.9% |
| 2025-11 | 12,657 | 1,265,700円 | 9,126,210円 | 201 | +621.0% |
| 2025-12 | 15,445 | 1,544,500円 | 9,060,030円 | 236 | +486.6% |
| **計** | **40,787** | **4,078,700円** | **23,550,890円** | **574** | **+477%** |

**1착 ECE**: 0.1396（**7.6x 悪化**）｜**的中率/bet**: 1.4%

### 解釈と注意点

**ECE 悪化の主因（Session 2 特徴量改善の副作用）**:
- 確率過大推定: avg top_prob 0.048 → 0.065（+35%）
- EV 過大評価: avg top_EV 72 → 119（+65%）
- 的中率低下: 6.19% → 1.41%（-4.4x）
- `tidal_level` 推定値（P4修正）または直近勝率ロールアップが歪みを引き起こした可能性

**ROI は依然プラスだが、確率推定の信頼性が低下している**:
1. **サンプル期間が短い**（3ヶ月）: 分散が大きい
2. **ECE 7.6x 悪化**: Session 3 のキャリブレーション補正が急務
3. **P7未修正**: random train/val split は引き続き問題
4. **boat_no SHAP 支配**: モデルがポジションバイアスに依存しすぎている可能性

### Session 3 進行前の確認事項
- [x] ~~Session 2 変更を含めた再学習・Walk-Forward検証~~ → 完了（ROI 477%、ECE 7.6x悪化を確認）
- [x] ~~特徴量重要度確認~~ → 完了（boat_no が SHAP 0.716 でダントツ1位）
- [x] ~~Calibration Analysis~~ → 完了（1착 ECE: 0.018 → 0.140 を確認）
- [ ] オッズParquetを `data/odds/` にコピー（次回バックテスト前に必須）: `cp artifacts/odds_2025*.parquet data/odds/`
- [ ] より長期（2024-01〜2025-12）のWalk-Forward検証を将来的に実施
