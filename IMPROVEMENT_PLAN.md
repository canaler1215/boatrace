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

- [ ] EV閾値・確率閾値の最適組み合わせをバックテストで特定
- [ ] Kelly基準によるベット額の動的調整
- [ ] 場・艇番・オッズ帯別のセグメント分析
- [ ] 最終的なROI目標値設定と運用ルール策定

---

## 現在の進捗

**最終更新**: 2026-04-16
**現在のセッション**: **Session 3 コード実装完了 → 次回再学習で ECE 改善を検証**

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

**次のステップ**: GitHub Actions の retrain.yml を実行 → 再学習後に `run_calibration.py --year 2025 --month 12` で ECE 改善を確認

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
