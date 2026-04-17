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
- **モデル保存形式** (Session 6〜): `{"booster": lgb.Booster, "softmax_calibrators": list[IsotonicRegression]}` ※旧形式(temperature/calibrators/Booster直接)も後方互換
- **キャリブレーション** (Session 6〜): `trainer.py` で raw probs → softmax正規化 → per-class Isotonic Regression → 再正規化
  - Session 5（廃止）: Temperature Scaling（T≈1.0 でスケーリング無効、trifecta ECE 4.6x 悪化と確定）
  - Session 6 狙い: ビン別構造バイアスを per-bin IR で直接補正、sum-to-1 維持で trifecta ECE も改善
- **学習データ分割** (Session 3〜): 時系列 split（最後の 10% を val、random split 廃止）
- **3連単確率**: Plackett-Luce近似（1着確率のみから計算）。`predict_win_prob` が sum-to-1 を保証するため過大推定を抑制
- **EV計算**: `EV = P_model × odds`（実オッズ or 合成オッズ）
- **購入条件** (Session 5〜): prob ≥ 7%, EV ≥ 2.0, コース2/4/5除外, オッズ<100x除外, びわこ(ID=11)除外
- **購入金額**: 1点 100円（`--kelly-fraction 0.25` による 1/4 Kelly 基準も選択可能）

## 既知の問題（改善タスクに対応中）

→ 詳細は `IMPROVEMENT_PLAN.md` を参照。

## Walk-Forward 実績（2025-10〜12, 実オッズ, 各月再学習）

### Session 5 モデル（Temperature Scaling + 強化購入ルール — **現行モデル**）

| 指標 | 値 | Session 3 比 |
|------|----|------------|
| 期間ROI | **+1,044%** | **+2x改善** |
| ベット数 | 6,967点 | -81.7%（絞り込み） |
| 的中 | 130件 | -76% |
| 的中率/bet | 1.87% | +32%改善 |
| 的中時平均オッズ | 613x | +42%改善 |
| avg top_prob | 0.0830 | +18.6%↑ |
| 1着 ECE（raw） | 0.13720 | ほぼ同等（-3%改善） |
| trifecta ECE | 0.001123 | ▼ **4.6x悪化** |
| Temperature T | 0.988≈1.0 | — |

| 月 | ベット | 投資額 | 払戻額 | 的中 | ROI |
|----|-------|--------|--------|-----|-----|
| 2025-10 | 2,245 | 224,500円 | 2,622,980円 | 39件 | +1,068% |
| 2025-11 | 2,064 | 206,400円 | 3,456,580円 | 55件 | +1,575% |
| 2025-12 | 2,658 | 265,800円 | 1,890,310円 | 36件 | +611% |
| **計** | **6,967** | **696,700円** | **7,969,870円** | **130件** | **+1,044%** |

> **評価**: 購入ルール強化（コース/オッズ/場フィルタ, prob≥7%, EV≥2.0）によりROIは倍増。
> 一方、Temperature Scaling は T≈1.0 で実質無効。trifecta ECE が悪化（Plackett-Luce との相互作用）。
> 月次ROIの分散が大きく（611%〜1,575%）、3ヶ月では統計的信頼性が限定的。
> **→ Session 6 でレース内ソフトマックス正規化 + 長期Walk-Forwardで根本課題に対処**

### Session 3 モデル（キャリブレーション補正 + 時系列split）

| 指標 | 値 | Session 2 比 |
|------|----|------------|
| 期間ROI | **+515.6%** | +38pp改善 |
| ベット数 | 38,057点 | -6.7% |
| 的中 | 541件 | -5.7% |
| 的中率/bet | 1.42% | ≒同等 |
| 的中率/race | 5.51% | — |
| 的中時平均オッズ | 433x（中央値164x） | ほぼ同等 |
| avg top_prob | 0.0700 | +7.7%↑ (悪化) |
| 1着 ECE（raw） | 0.14178 | ほぼ同等 |

> **注意**: Session 3 でキャリブレーション補正（Isotonic Regression）と時系列 split を実装したが、
> 的中率/bet は 1.41% → 1.42% とほぼ変化なし。avg top_prob も増加（悪化）。
> 原因: trifecta 確率が予測 10-20% 帯で実際勝率の 7.6x、20-30% 帯で 31x の過大推定。
> Plackett-Luce 近似 + 各クラス独立キャリブレーション（sum-to-1 未担保）が根本課題。
> **→ Session 4 (購入戦略改善) で閾値最適化・Kelly 基準を導入して対処**

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

# キャリブレーション分析（Session 4〜: calibrated ECE も出力）
python ml/src/scripts/run_calibration.py --year 2025 --month 12

# Walk-Forward（複数月）
python ml/src/scripts/run_walkforward.py --start 2025-10 --end 2025-12 --retrain --real-odds

# グリッドサーチ（過大推定フィルタあり/なし比較、既存 combo CSV 再利用）
python ml/src/scripts/run_grid_search.py --combos-csv artifacts/combos_202512.csv

# セグメント分析（場・コース・オッズ帯・確率帯別 ROI）
python ml/src/scripts/run_segment_analysis.py --combos-csv artifacts/combos_202512.csv

# 1/4 Kelly バックテスト
python ml/src/scripts/run_backtest.py --year 2025 --month 12 --real-odds \
  --kelly-fraction 0.25 --kelly-bankroll 100000

# ── Session 5 現行ルール（デフォルト）────────────────────────────────────

# 新ルールでバックテスト
python ml/src/scripts/run_backtest.py --year 2025 --month 12 --real-odds \
  --prob-threshold 0.07 --ev-threshold 2.0 \
  --exclude-courses 2 4 5 --min-odds 100 --exclude-stadiums 11

# 新ルール Walk-Forward
python ml/src/scripts/run_walkforward.py \
  --start 2025-10 --end 2025-12 --retrain --real-odds \
  --prob-threshold 0.07 --ev-threshold 2.0 \
  --exclude-courses 2 4 5 --min-odds 100 --exclude-stadiums 11
```
