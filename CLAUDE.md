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
    tidal_features.py       潮位特徴量
    stadium_features.py     場特徴量（全24場中3場のみカスタム値）
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
- **3連単確率**: Plackett-Luce近似（1着確率のみから計算）
- **EV計算**: `EV = P_model × odds`（実オッズ or 合成オッズ）
- **購入条件**: 的中確率 ≥ 3% AND EV > 1.2
- **購入金額**: 1点 100円

## 既知の問題（改善タスクに対応中）

→ 詳細は `IMPROVEMENT_PLAN.md` を参照。

## Walk-Forward 実績（2025-10〜12, 実オッズ, 各月再学習）

| 指標 | 値 |
|------|----|
| 期間ROI | **+2,524%** |
| ベット数 | 37,868点 |
| 的中 | 2,344件 |
| 的中率/bet | 6.2%（ランダム比 7.5x） |
| 的中時平均オッズ | 424x（中央値148x） |

> 注: 3ヶ月のみでサンプル期間が短い。キャリブレーション・グリッドサーチCSVは
> GH Actions artifactsから別途DL要。オッズparquetは `data/odds/` への配置が必要。

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

# 次回バックテスト前にオッズParquetをコピー
cp artifacts/odds_2025*.parquet data/odds/
```
