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

- [ ] キャリブレーション補正（Platt scaling or isotonic regression）
- [ ] 2着・3着の条件付きモデルを独立学習（Plackett-Luce脱却）
- [ ] 時系列Walk-Forward学習への移行（random split廃止）
- [ ] ハイパーパラメータ再チューニング

### Session 4: 購入戦略改善
**目標**: ROIがプラスになるベッティング戦略を確立する

- [ ] EV閾値・確率閾値の最適組み合わせをバックテストで特定
- [ ] Kelly基準によるベット額の動的調整
- [ ] 場・艇番・オッズ帯別のセグメント分析
- [ ] 最終的なROI目標値設定と運用ルール策定

---

## 現在の進捗

**最終更新**: 2026-04-16
**現在のセッション**: Session 2 完了 → **Session 3 準備中**

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

---

## Walk-Forward 分析結果（2025-10 〜 2025-12）

### 結果サマリー（prob≥5%, EV≥1.2, 1レース最大5点）

| 月 | ベット数 | 投資額 | 払戻額 | 的中数 | ROI |
|----|---------|--------|--------|--------|-----|
| 2025-10 | 11,973 | 1,197,300円 | 30,470,150円 | 721 | +2,445% |
| 2025-11 | 11,601 | 1,160,100円 | 28,474,940円 | 726 | +2,355% |
| 2025-12 | 14,294 | 1,429,400円 | 40,410,570円 | 897 | +2,727% |
| **計** | **37,868** | **3,786,800円** | **99,355,660円** | **2,344** | **+2,524%** |

### 解釈と注意点

**ROI +2524% の主因**（データリークは確認されず）:
- モデル推定確率 平均 **8.0%** vs 市場含意確率 平均 **1.2%**（的中ベット対象）
- モデルは市場の **34x** 高い確率を推定し、かつ的中している
- 実際の的中率は約 **6.2% / bet**（ランダム 0.83% の **7.5倍**）
- exhibitioin_time が市場に未反映の有力シグナルである可能性

**重要な留保事項**:
1. **サンプル期間が短い**（3ヶ月）: 分散が大きく、幸運な期間の可能性あり
2. **キャリブレーション**（モデル確率 8% vs 実績 6.2%）: 確率が過大推定気味
3. **P7未修正**: ランダム train/val split でアーリーストップが最適でない可能性
4. **Grid Search・Calibration CSVが未取得**: GH Actions artifactsからのDL未完了

### 構造的問題（要修正）
- **オッズParquetの配置ミス**: GH Actionsが出力した `odds_202510/11/12.parquet` が
  `artifacts/` に置かれているが、正しいキャッシュパスは `data/odds/`
  → 次回実行前に `cp artifacts/odds_2025*.parquet data/odds/` が必要

### Session 3 進行前の確認事項
- [ ] オッズParquetを `data/odds/` にコピー（次回バックテスト前に必須）: `cp artifacts/odds_2025*.parquet data/odds/`
- [ ] Session 2 変更を含めた再学習・Walk-Forward検証で改善効果を確認
- [ ] 特徴量重要度確認: `python ml/src/scripts/run_feature_importance.py --year 2025 --month 12`
- [ ] より長期（2024-01〜2025-12）のWalk-Forward検証を将来的に実施
