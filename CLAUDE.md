# boatrace — Claude Code ガイド

## プロジェクト概要

競艇（ボートレース）の3連単予想システム。
LightGBM で各艇の着順確率を推定し、期待値（EV）を計算して購入判断を行う。

## ディレクトリ構成

```
ml/src/
  collector/          データ取得
    history_downloader.py   K/Kファイル（競走成績）ダウンロード
    program_downloader.py   Bファイル（出走表）ダウンロード
    odds_downloader.py      実オッズ取得（boatrace.jp）
    openapi_client.py       OpenAPI クライアント
    db_writer.py            DB書き込み
  features/           特徴量生成
    feature_builder.py      メイン特徴量ビルダー（12次元）
    tidal_features.py       潮位特徴量（月齢推定）
    stadium_features.py     場特徴量（全24場1コース勝率）
  model/              モデル
    trainer.py              LightGBM 学習（multiclass 6クラス）
    predictor.py            推論・EV計算（Plackett-Luce近似）
    evaluator.py            評価（RPS, top1_accuracy）
  backtest/           バックテスト
    engine.py               バックテストエンジン（run_race / run_backtest_batch）
    odds_simulator.py       合成オッズ（艇番ベース全国平均）
  scripts/            実行スクリプト
    run_backtest.py         バックテスト実行
    run_predict.py          本番予測
    run_retrain.py          再学習
    run_collect.py          データ収集
artifacts/            学習済みモデル（model_*.pkl）
data/                 ダウンロードキャッシュ
```

## 現在の仕様

- **モデル**: LightGBM multiclass (num_class=6, 着順1〜6を予測)
- **特徴量** (12次元): `exhibition_time`, `motor_win_rate`, `boat_win_rate`, `boat_no`, `racer_win_rate`, `racer_grade_encoded`, `racer_avg_st`, `tidal_level`, `tidal_type_encoded`, `in_win_rate`, `wind_direction_encoded`, `wind_speed`
- **モデル保存形式** (Session 3〜): `{"booster": lgb.Booster, "calibrators": list[IsotonicRegression]}` ※旧形式(lgb.Booster直接)も後方互換
- **キャリブレーション** (Session 3〜): `trainer.py` で val データに Isotonic Regression を fitting、推論時に `predict_win_prob()` が自動適用
- **学習データ分割** (Session 3〜): 時系列 split（最後の 10% を val、random split 廃止）
- **3連単確率**: Plackett-Luce近似（1着確率のみから計算）
- **EV計算**: `EV = P_model × odds`（実オッズ or 合成オッズ）
- **購入条件**: 的中確率 ≥ 3% AND EV > 1.2
- **購入金額**: 1点 100円

## 既知の問題（改善タスクに対応中）

→ 詳細は `IMPROVEMENT_PLAN.md` を参照。

## Walk-Forward 実績（2025-10〜12, 実オッズ, 各月再学習）

### Session 1 モデル（特徴量改善前）

| 指標 | 値 |
|------|----|
| 期間ROI | **+2,524%** |
| ベット数 | 37,868点 |
| 的中 | 2,344件 |
| 的中率/bet | 6.2%（ランダム比 7.5x） |
| 的中時平均オッズ | 424x（中央値148x） |

### Session 2 モデル（特徴量改善後 — **ECEキャリブレーション大幅悪化**）

| 指標 | 値 | 変化 |
|------|----|------|
| 期間ROI | **+477%** | ▼ 大幅低下 |
| ベット数 | 40,787点 | +8% |
| 的中 | 574件 | ▼ -75% |
| 的中率/bet | 1.4% | ▼ -4.4x |
| 的中時平均オッズ | 410x（中央値165x） | ほぼ同等 |
| 1着 ECE（キャリブレーション） | 0.1396 | ▼ **7.6x悪化** |
| top1_accuracy | 31.2% | ランダム比 1.9x |

> **注意**: Session 2 の特徴量改善（潮位推定・直近勝率・全24場勝率）によりキャリブレーション
> が 7.6x 悪化。確率推定が過大評価になり、的中率が 6.2%→1.4% に低下。
> Session 3 のキャリブレーション補正が最優先課題。

### モデル品質（Session 2）
- top1_accuracy: 31.2%（ランダム 16.7% の 1.9x）
- RPS: 0.1567
- 訓練データ: 2022-01-01〜2026-04-16（1,403,845サンプル）
- 1着 ECE: 0.1396（旧 0.018 → **7.6x悪化**）

## よく使うコマンド

```bash
# バックテスト（実オッズ使用）
python ml/src/scripts/run_backtest.py --year 2025 --month 12 --real-odds --retrain

# バックテスト（合成オッズ、高速）
python ml/src/scripts/run_backtest.py --year 2025 --month 12

# 再学習のみ
python ml/src/scripts/run_retrain.py

# 本番予測
python ml/src/scripts/run_predict.py

# 特徴量重要度・SHAP値の可視化
python ml/src/scripts/run_feature_importance.py --year 2025 --month 12
python ml/src/scripts/run_feature_importance.py --year 2025 --month 12 --no-shap  # SHAP省略

# キャリブレーション分析
python ml/src/scripts/run_calibration.py --year 2025 --month 12

# Walk-Forward（複数月）
python ml/src/scripts/run_walkforward.py --start 2025-10 --end 2025-12 --retrain --real-odds

# 次回バックテスト前にオッズParquetをコピー
cp artifacts/odds_2025*.parquet data/odds/
```
