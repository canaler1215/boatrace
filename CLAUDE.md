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
  ※ バグ修正後の実オッズ検証でコース4/5除外は逆効果と判明。条件見直し中（`BET_RULE_REVIEW_202509_202512.md` 参照）
- **購入金額**: 1点 100円（`--kelly-fraction 0.25` による 1/4 Kelly 基準も選択可能）

## 既知の問題（改善タスクに対応中）

→ 詳細は `IMPROVEMENT_PLAN.md` を参照。

## Walk-Forward 実績（実オッズ）

> 🛑 **⚠️ 警告: 以下の数値はすべて無効です（2026-04-24 確定）**
>
> Session 1〜6 / S6-3 / S6-4 の ROI 実績値（+794.9%、+1,312%、+2,524% 等）は、
> **オッズパース処理のバグ**により水増しされた**幻影**であり、修正後の実オッズでは
> 以下の通り大幅に乖離します:
>
> - 2025-09〜12（4 ヶ月）: **ROI -21.0%**
> - 2025-05〜2026-04（12 ヶ月、案 A = 10 場除外適用）: **ROI -13.4%**
> - 破局月: 2025-10 (-72.4%) / 2026-01 (-79.5%) / 2026-04 (-65.4%)
>
> **参照禁止**: 以下の数値・運用ルール・季節性・月次停止基準等を根拠にした判断は
> すべて誤った前提に基づきます。レビュー・PR・新規実装の根拠に引用しないでください。
>
> **現在の状況**:
> - フェーズ3 内ループは凍結中（PR #3 でレビュー結果反映済み）
> - フェーズ6 `/model-loop` でモデル側（学習窓・sample_weight・LightGBM ハイパラ）を
>   再設計中。本番 10 trial 連続実行は `data/odds/2025-05〜2026-04` の DL 完了待ち
>   （2026-04-24 改訂: 旧 T06 を feature_subsample に差し替え、T08/T09 seed 反復を追加）
> - 実運用再開条件: 通算 ROI ≥ +10% かつ最悪月 > -50% を満たすこと
>
> 詳細: [BET_RULE_REVIEW_202509_202512.md](BET_RULE_REVIEW_202509_202512.md) §28-32
>
> 以下の旧実績テーブルは、バグ修正前の試行の履歴として残していますが、
> 現在の意思決定には使わないでください。折りたたまれているのは意図的です。

<details>
<summary>🗂 旧実績テーブル（幻影。参照禁止 / Session 1〜6、S6-3 短期比較含む）— クリックで展開</summary>

> ⚠️ ここから下のテーブル・評価コメントは**すべてバグ修正前の幻影**です。
> 個別の数値（avg_odds=708x 等）も実態を反映していません。
> 現行の参照すべき実績は [BET_RULE_REVIEW_202509_202512.md](BET_RULE_REVIEW_202509_202512.md) のみです。

### Session 6 モデル（Softmax正規化 + Isotonic Regression — **現行モデル、S6-3長期検証完了**）

#### S6-3: 長期 Walk-Forward（2024-01〜2025-12、24ヶ月）

| 指標 | 値 |
|------|----|
| 期間ROI | **+794.9%** |
| ベット数 | 62,693点 |
| 投資額 | 6,269,300円 |
| 払戻額 | 56,101,620円 |
| 的中数 | 958件 |
| 平均的中率/bet | 1.53% |
| 的中時平均オッズ | 586x（中央値317x） |
| avg top_prob | 0.0854 |
| **ROI<0%の月** | **0/24（全月プラス）** |

| 年 | ベット | 投資額 | 払戻額 | 的中 | ROI |
|----|-------|--------|--------|-----|-----|
| 2024 | 30,104 | 3,010,400円 | 24,817,210円 | 444 | +724.4% |
| 2025 | 32,589 | 3,258,900円 | 31,284,410円 | 514 | +860.0% |
| **計** | **62,693** | **6,269,300円** | **56,101,620円** | **958** | **+794.9%** |

月次ROI統計: 平均796.5%、中央値795.6%、標準偏差220.4%、最低+297.9%（2024-06）、最高+1,430.3%（2025-12）

季節性: 3月（平均465%）・6月（578%）が低め、7〜9月（900%前後）・12月（1,106%）が高め

> **評価（S6-3）**: **全24ヶ月でROIプラス**（偶然では説明できない統計的信頼性）。
> 短期S6（+1,312%）より低い+794.9%は長期分散の平準化で想定内。
> ROIの源泉は依然として高オッズ×絞り込みの宝くじ構造（avg 586x × 的中率1.53%）。
> 1着識別能力の問題（全ビン~17%）は未解決だが、戦略として機能することが統計的に確認された。

#### 短期比較（2025-10〜12、S5 比較用）

| 指標 | 値 | Session 5 比 |
|------|----|------------|
| 期間ROI | **+1,312%** | **+268pp改善** |
| ベット数 | 7,023点 | ≒ 同等 |
| 的中 | 140件 | +7.7% |
| 的中率/bet | 1.99% | +6.4%改善 |
| 的中時平均オッズ | 708x | +15%改善 |
| avg top_prob | 0.0848 | +2.2% |
| 1着 ECE（raw） | 0.13561 | 微改善（-1.2%） |
| 1着 ECE（calibrated） | 0.13371 | IR有効（-2.5%） |
| trifecta ECE | 0.001327 | ▼ **+18%悪化** |

| 月 | ベット | 投資額 | 払戻額 | 的中 | ROI |
|----|-------|--------|--------|-----|-----|
| 2025-10 | 2,090 | 209,000円 | 3,312,520円 | 47件 | +1,485% |
| 2025-11 | 2,201 | 220,100円 | 3,167,150円 | 47件 | +1,339% |
| 2025-12 | 2,732 | 273,200円 | 3,435,190円 | 46件 | +1,157% |
| **計** | **7,023** | **702,300円** | **9,914,860円** | **140件** | **+1,312%** |

> **評価**: ROI +268pp改善、月次ROI幅が 964pp → 328pp に大幅安定化。的中率・avg odds も改善。
> ただし trifecta ECE は悪化（+18%）。Softmax正規化でも Plackett-Luce 精度改善には至らず。
> **重大発見**: 1着の実際的中率が全予測ビンで均一に ~16〜17%（ランダムに近い）。
> モデルが「誰が1着か」をほとんど識別できていない可能性が高い。ROIプラスは高オッズ×低ベットの宝くじ構造に依存。
> **→ S6-3（長期 Walk-Forward 2024-01〜2025-12）完了: 全24ヶ月プラス、統計的信頼性確認済み**

### Session 5 モデル（Temperature Scaling + 強化購入ルール）

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
> **→ Session 6（Softmax正規化 + Isotonic Regression）で ROI +1,312%・月次安定化を達成。S6-3 長期検証（24ヶ月・全月プラス）完了。**

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

</details>

<details>
<summary>🗂 旧運用ルール S6-4（幻影。参照禁止）— クリックで展開</summary>

> 🛑 **本セクション全体が無効です（2026-04-24）**
>
> 以下のゾーン基準（ROI 500%）、月次停止条件、季節性調整、資金管理はすべて
> 幻影 ROI +794.9% を前提としたものです。修正後の実態（12 ヶ月通算 -13.4%）で
> これらを適用すると危険です。**本番運用には絶対に使用しないでください。**
>
> 現行の実運用再開条件: 通算 ROI ≥ +10% かつ最悪月 > -50% を満たすこと
> （BET_RULE_REVIEW_202509_202512.md §30-32）

## 運用ルール（S6-4、2026-04-18 策定）

S6-3 長期 Walk-Forward（24ヶ月全月プラス、ROI +794.9%）に基づく実運用判断基準。

### 月次モニタリング基準

| ゾーン | ROI基準 | 24ヶ月実績 | アクション |
|--------|---------|-----------|---------|
| 正常域 | ≥ 500% | 22/24ヶ月（92%） | 継続 |
| 注意域 | 300%〜499% | 1/24ヶ月（4%） | 要観察 |
| 警戒域 | 0%〜299% | 0/24ヶ月（史上最低+297.9%に隣接） | **一時停止** → 再学習 + 分析 |
| 危険域 | < 0% | 0/24ヶ月（未発生） | **即時停止** → 総点検 |

### 停止条件
- ROI < 0%: 即時停止 → `run_calibration.py` + `run_segment_analysis.py` で原因分析
- ROI < 300% が2ヶ月連続: 一時停止 → `run_retrain.py` 再学習
- ROI < 500% が3ヶ月連続: グリッドサーチで閾値再最適化

### 季節性調整（S6-3 実績ベース）

| 月 | 実績平均ROI | 推奨ベット額 |
|----|-----------|------------|
| 3月 | 465%（最低） | **70円/点**（-30%） |
| 6月 | 578% | **80円/点**（-20%） |
| 7〜9月、12月 | 900〜1,106% | 100円/点（標準） |
| 他月 | ~800% | 100円/点（標準） |

### 資金管理
- 推奨初期資本: ≥ 200,000円
- 月次投資目安: ~260,000円（月平均2,600件 × 100円）
- 歴史的最悪月: +297.9%（0/24ヶ月でマイナスなし）

### 定期オペレーション手順
- **日次**: `run_predict.py`（当日レースの購入候補抽出）
- **月初**: `run_retrain.py`（モデル再学習）
- **月次**: `run_backtest.py` でROI確認
- **四半期**: `run_calibration.py`（キャリブレーション確認）
- **半期**: `run_walkforward.py`（直近6ヶ月 Walk-Forward 再検証）

→ 詳細は `IMPROVEMENT_PLAN.md` の「Session 6 S6-4 運用ルール」セクションを参照。

</details>

## 現行の運用方針（2026-04-26 時点）

- **実運用（自動購入）は停止中**。再開条件は `BET_RULE_REVIEW_202509_202512.md §30-32`
  の通り「通算 ROI ≥ +10% かつ最悪月 > -50%」を満たすこと
- **フェーズ 3 `/inner-loop`（フィルタ探索）は凍結中**（PR #3、out-of-sample 黒字化不能と判定済み）
- **フェーズ 6 `/model-loop`（モデル構造ループ）は完全撤退確定**（2026-04-25/26）
  - 構造変更ツリー §5 全 4 候補（特徴量拡張 / 目的関数変更 / Purged CV / Calibration 再設計）
    + 保留候補 R1 LambdaRank の 5 系統すべてで採用基準未達
  - lambdarank seed 反復 3 本で ROI mean=-10.0% / std=5.9pp / 最良 -6.1% でも
    +10% 閾値から 16pp 乖離、bootstrap CI 下限すべて -20pp 以下
  - 詳細: [LAMBDARANK_WALKFORWARD_RESULTS.md](LAMBDARANK_WALKFORWARD_RESULTS.md)
- **T16 Perfect-Oracle Upper Bound 計測完了**（2026-04-26、撤退判定の確証ラン）
  - 現行 strategy（10 場除外 + min_odds 100x + bet 100 円）下で actual 1-2-3 trifecta
    に確率 1.0 を割り当てた場合の Walk-Forward 12 ヶ月通算 **ROI = +29,186%**
    （全月プラス、worst +27,196%、CI [+28,658, +29,673]）
  - **CLAUDE.md +10% 閾値は strategy 上限の 0.034%** = strategy 自体は天井に当たっていない
  - **+10% 達成に必要な hit_rate_per_bet = 0.376%**、T07 (現状唯一の pass) 実績 = 0.36% で
    相対 +4.5% の改善で届く水準。にも関わらず 16 trial の構造変更で達成不能
  - 撤退判定のニュアンス更新: 旧「strategy / model 天井で達成不能」→
    新「strategy 天井から見れば容易な閾値だが、現行モデル系統の **seed ノイズ床
    (T07/T10/T11 ROI std 17pp)** に埋没して再現性のある +10% 達成は不能」
  - **B-3 (馬券種転換で控除率を下げる) の正当性が補強**: 必要 hit rate を緩めることで
    seed ノイズ床問題を構造的に回避できる可能性
  - 詳細: [MODEL_LOOP_RESULTS.md](MODEL_LOOP_RESULTS.md)「T16 reference」セクション
- **フェーズ B-1「市場効率の歪み分析」完全撤退確定**（2026-04-26）
  - Step 1: 古典的 favorite-longshot bias の競艇版を統計的に確認（採用基準達成
    4 / 9 ビン、ただし `ev_all_buy` 全ビン < 1.0）
  - Step 2 単軸 + 2 軸組合せ: **採用基準達成 0 / 全 62 サブセグメント**
  - 最有望は **7. Gamagori（蒲郡）× 1 コース勝ち** で `lift=1.27, ev=0.98, CI=[0.90, 1.06]`。
    控除率 25% を破る確信なし
  - 構造的結論: 競艇 3 連単市場の favorite-longshot bias は「控除率を縮める効果」
    止まりで「収支プラス化」までは至らない
  - 詳細: [NEXT_PHASE_B1_PLAN.md](NEXT_PHASE_B1_PLAN.md) §9「B-1 撤退結果」 / [MARKET_EFFICIENCY_SEGMENT_RESULTS.md](MARKET_EFFICIENCY_SEGMENT_RESULTS.md) / [MARKET_EFFICIENCY_RESULTS.md](MARKET_EFFICIENCY_RESULTS.md)
- **🛑 全フェーズ撤退状態へ移行**（2026-04-26）
  - フェーズ 3 凍結（`/inner-loop`） + フェーズ 6 完全撤退（`/model-loop`） + フェーズ 7 撤退（B-1）
  - 実運用は引き続き停止、`/inner-loop` `/model-loop` `run_market_efficiency.py` の改善ループはすべて停止
- **次フェーズ B-3「単勝市場効率分析」を着手予定として保留**（2026-04-26 ユーザー合意、別セッションで進める）
  - 控除率 20%（3 連単 25% より 5pp 低い）の単勝で同じ favorite-longshot bias 分析を試みる
  - B-1 で観測した「lift 1.20〜1.27」が単勝でも観測されれば、控除率破壊閾値 1.25 をクリアの可能性
  - **追加 DL 必要**: 単勝オッズ 12 ヶ月分（推定 12〜24 時間バックグラウンド DL）
  - 実装スコープ: `openapi_client.py` / `odds_downloader.py` への単勝対応追加 +
    `run_market_efficiency.py` への `--bet-type win` 拡張
  - 次セッション着手用: [NEXT_SESSION_PROMPT.md](NEXT_SESSION_PROMPT.md) を貼り付け
  - 詳細計画: [NEXT_PHASE_B3_PLAN.md](NEXT_PHASE_B3_PLAN.md)
- **キャリブレーション確認、月次バックテスト**は `run_calibration.py` / `run_backtest.py`
  で継続実施可能。ただし ROI 数値の絶対値で判断せず、**月次トレンドと破局月の有無**で評価する
- **月次ベット額等の資金管理基準**は策定保留。通算 ROI 黒字化を達成してから再設計する

## 3連複検討履歴（2026-04 完結）

→ 詳細は `TRIO_BET_PLAN.md` を参照。

### 結論：**3連複の追加購入は非推奨**（2026-04-22 確定）

T6〜T6-B の検証を経て 3連複追加を否定する根拠が確認された。

| 検証ステップ | 結果 |
|------------|------|
| T6 パイロット (prob=0.10, ev=2.0) | ROI +62.1%（3連単+1,312%の1/21） |
| T6-A グリッドサーチ (最良: prob=0.20, ev=4.0) | ROI +118.0%（依然3連単の1/11） |
| T6-B リカバリー分析（合成オッズ） | 3連単+3連複組合せROI +56.2% ＜ 3連単単独+78.5% |

**リカバリー分析の主要知見（2025-10〜12、11,895レース）:**
- 純リカバリー（3連複のみ的中）: 190件、払戻1,057,204円 / 投資27,100円 → 単体ROI +3,801%
- ただし3連複の投資コスト増（848,300円）が3連単ROIを22pp相殺
- 3連単+3連複同時購入ROI: +56.2%（3連単単独+78.5%より悪化）
- **3連単・3連複の相関が強い**（3連単的中28件のうち82%は3連複も的中 → 補完でなく重複）

**方針**: 現行の3連単専念戦略を継続。3連複関連コードはバックテスト用として保持するが実運用には使用しない。

## 自律改善ループ（内ループ）の運用

**原則: バックテストの自律改善ループを実行する際は、必ず GitHub Actions 経由で実行する。ローカル実行（`python ml/src/scripts/run_backtest.py`）は使わない。**

### 実行方法

Claude Code セッションで `/inner-loop <year> <month> [max-iter]` を実行する。例:

```
/inner-loop 2025 12
/inner-loop 2025 12 3   # 最大3イテレーション
```

`/inner-loop` は以下のフローを自動実行する:

1. `gh workflow run claude_fix.yml` で baseline ランをキック
2. `gh run watch` で完了待機
3. `gh run download` で artifacts（CSV/JSON/TXT）を取得
4. `gate_result_*.json` と `segment_*.txt` を読んで分析
5. `ml/configs/strategy_default.yaml` を修正（1 パラメータのみ）
6. 修正後のパラメータで candidate ランをキック
7. baseline vs candidate を比較
8. 改善が確認できれば PR 作成、ダメなら次イテレーションまたは撤退

### 前提

- `gh` CLI がインストール済み・認証済みであること（`winget install GitHub.cli` → `gh auth login`）
- GitHub リポジトリに `auto-loop-candidate` ラベルが存在すること
- `BACKTEST_DATABASE_URL` が GitHub Secrets に設定されていること（`--retrain` を使う場合）

### なぜローカル実行してはいけないか

- 実オッズダウンロードに数時間かかり、PC を占有する
- GitHub Actions 側のオッズキャッシュが効かない（イテレーションごとに毎回ダウンロード）
- `gh run list` で履歴追跡できない

### 手動で単発バックテストをローカル実行するのは OK

この原則は「自律改善ループ」の話であり、通常のデバッグ・検証目的でのローカルバックテスト（下記「よく使うコマンド」）は従来通り許可される。

詳細: `.claude/commands/inner-loop.md`, `.claude/AGENT_BRIEF.md`, `AUTO_LOOP_PLAN.md`

## モデル構造自律改善ループ（/model-loop）の運用

**用途の違い**: `/inner-loop` と `/model-loop` は変更対象が異なる。両立する。

| 観点 | `/inner-loop` | `/model-loop` |
|---|---|---|
| 変更対象 | `ml/configs/strategy_default.yaml`（購入フィルタ 1 パラメータ） | 学習ハイパラ・学習窓・sample_weight（`trials/pending/*.yaml`） |
| 実行場所 | GitHub Actions 強制 | **ローカル**（Windows / Python 3.12） |
| 1 trial の時間 | 数分〜数十分 | 15〜25 分（Walk-Forward 12 ヶ月 + 3 ヶ月おき再学習） |
| 判定基準 | ROI 500% 基準 | 通算ROI ≥ +10% + broken_months=0（worst > -50%）+ プラス月 ≥ 60% + bootstrap CI 下限 ≥ 0（2026-04-24 改訂、MODEL_LOOP_PLAN §3-5） |
| 背景 | フィルタ探索 | `BET_RULE_REVIEW_202509_202512.md` §30-32 の結論：フィルタでは out-of-sample 黒字化不能 → モデル側の再設計が必要 |

### 実行方法

Claude Code セッションで `/model-loop [trial_id | all]` を実行する。例:

```
/model-loop              # trials/pending/ の全 trial を連続実行
/model-loop T01_window_2024   # 単発
```

`/model-loop` は以下のフローを自動実行する:

1. `trials/pending/*.yaml` の有無を確認（空なら新 trial 設計フェーズへ）
2. `py -3.12 ml/src/scripts/run_model_loop.py [--trial <id>]` を実行
3. 各 trial で `get_model_for_month` → `run_backtest_batch` を Walk-Forward 方式で回す
4. KPI を算出して `trials/results.jsonl` に 1 行追記、成功時は YAML を `completed/` へ移動
5. 全 trial 完了後、`primary_score` 順にテーブル形式で報告
6. 設計書 §5 判定ルールで次アクション提案（上位近傍 / 構造変更 / 撤退）

### 前提（ローカル環境）

- **Python 3.12** (`py -3.12 --version`)、`pip install -r ml/requirements.txt` 済み
- データキャッシュが揃っていること:
  - `data/history/`, `data/program/` — 2023-01〜2026-04
  - `data/odds/` — 2025-05〜2026-04 の 12 ヶ月実オッズ（`download_odds.py` で取得）
- **DB 接続不要**（`run_backtest.py` / `run_walkforward.py` はファイルキャッシュだけで完結）
- ディスク容量: モデル ~50MB × 10 trial = 500MB、CSV 数十 MB（2026-04-24 改訂で 8→10）

### なぜローカル実行か

- 1 trial で 3 回 LightGBM を再学習するため GitHub Actions のタイムアウト内に収まらない
- ローカルならモデル `.pkl` を再利用できる（同月は再学習スキップ）
- `/inner-loop` と違い artifacts キャッシュの優位性が小さい

### 代表的な trial 構造

`trials/pending/T01_window_2024.yaml`（例）:

```yaml
trial_id: T01_window_2024
training:
  train_start_year: 2024
  sample_weight: { mode: recency, recency_months: 12, recency_weight: 3.0 }
lgb_params: { learning_rate: 0.02, num_leaves: 31 }
walkforward: { start: "2025-05", end: "2026-04", retrain_interval: 3, real_odds: true }
strategy:  # 比較統一のため全 trial で同一
  prob_threshold: 0.07
  ev_threshold: 2.0
  min_odds: 100.0
  exclude_stadiums: [2, 3, 4, 9, 11, 14, 16, 17, 21, 23]
  bet_amount: 100
  max_bets: 5
  bet_type: trifecta
```

**重要**: `strategy` は全 trial で統一すること。モデル側の差分だけを比較する設計。

詳細: `.claude/commands/model-loop.md`, `MODEL_LOOP_PLAN.md`, `trials/README.md`

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
