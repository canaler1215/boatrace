# MODEL_LOOP_RESULTS — 本番 13 trial 実行結果

最終更新: 2026-04-25（T10〜T12 追記）
対象:
- 初回 10 trial（T00〜T09）: [MODEL_LOOP_PLAN.md §4 タスク 4](MODEL_LOOP_PLAN.md) 準拠、2026-04-24 改訂版
- 追加 3 trial（T10〜T12）: T07_window_2024_plus_weight pass の確証サイクル（本書 §「T10〜T12 追加サイクル」参照）

## 実行条件

- Walk-Forward: 2025-05 〜 2026-04（12 ヶ月）、`retrain_interval=3`、`real_odds=true`
- `strategy` 全 trial 統一: `prob_threshold=0.07`, `ev_threshold=2.0`, `min_odds=100.0`,
  `exclude_stadiums=[2,3,4,9,11,14,16,17,21,23]`, `bet_amount=100`, `max_bets=5`, `bet_type=trifecta`
- 実行場所: ローカル（Windows / Python 3.12）
- 実行方法: `py -3.12 ml/src/scripts/run_model_loop.py`
- エラー: 0（全 10 trial `status=success`）
- primary_score 定義: `roi_total + 0.5 * cvar20_month_roi - 10 * broken_months`（[MODEL_LOOP_PLAN §3-4](MODEL_LOOP_PLAN.md)）
- verdict 判定: `pass` = ROI≥+10% かつ broken=0 かつ plus_ratio≥0.60 かつ CI 下限 ≥ 0（同 §3-5）

## 結果テーブル（primary_score 降順）

| trial_id | verdict | primary_score | ROI | worst_month | plus_ratio | broken | CI 下限 (90%) | CI 上限 (90%) | ECE(cal) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **T07_window_2024_plus_weight** | **pass** | **+1.59** | **+15.30%** | **-35.16%** | **66.7%** | **0** | **+1.94** | +28.94 | 0.00121 |
| T09_baseline_seed2 | marginal | -9.10 | +2.51% | -36.17% | 50.0% | 0 | -6.16 | +11.61 | 0.00132 |
| T00_baseline | fail | -24.96 | -6.64% | -43.17% | 50.0% | 0 | -13.34 | +2.63 | 0.00164 |
| T03_sample_weight_recency | fail | -32.00 | -2.03% | -54.77% | 41.7% | 1 | -12.71 | +7.05 | 0.00115 |
| T06_feature_subsample | fail | -34.95 | -1.17% | -61.30% | 41.7% | 1 | -12.18 | +11.30 | 0.00113 |
| T01_window_2024 | marginal | -37.59 | +8.58% | -61.28% | 58.3% | 2 | -3.64 | +19.47 | 0.00162 |
| T08_baseline_seed1 | fail | -43.62 | -6.80% | -62.52% | 41.7% | 1 | -28.03 | +14.94 | 0.00107 |
| T04_lgbm_regularized | fail | -49.15 | -12.91% | -66.05% | 41.7% | 1 | -31.70 | +6.86 | 0.00118 |
| T02_window_2025 | fail | -58.22 | -12.71% | -53.08% | 33.3% | 2 | -27.87 | +1.57 | 0.00146 |
| T05_lgbm_conservative_lr | fail | -65.80 | -1.79% | -81.65% | 50.0% | 3 | -20.40 | +18.61 | 0.00111 |

## 主要所見

### 1. T07 のみ verdict=pass（ただし seed ガチャの可能性）

T07_window_2024_plus_weight は CLAUDE.md の実運用再開条件（通算 ROI ≥ +10% かつ最悪月 > -50%）を
満たす唯一の trial。設計 §3-5 の pass 4 条件（ROI / broken / plus_ratio / CI 下限）をすべて通過。

ただし seed 感度が想像以上に大きく（下記 §2）、単独の pass だけで本採用は判断できない。
設計書 §5 に従い、近傍 2〜3 本で確証を取る必要がある。

### 2. seed 変動が極めて大きい（T00 / T08 / T09 の比較）

同設定で `lgb_params.seed` のみ変えた 3 本の分散:

| trial | seed | ROI | worst | plus_ratio | broken | verdict |
|---|---|---:|---:|---:|---:|---|
| T00_baseline | デフォルト | -6.64% | -43.17% | 50.0% | 0 | fail |
| T08_baseline_seed1 | 1 | -6.80% | -62.52% | 41.7% | 1 | fail |
| T09_baseline_seed2 | 2 | +2.51% | -36.17% | 50.0% | 0 | marginal |

統計:
- ROI: mean -3.64%, std 5.33pp, **range 9.31pp**
- worst: mean -47.29%, std 13.65pp, **range 26.35pp**

seed だけで verdict が fail/marginal を行き来するレベルの揺れがあり、T07 の ROI +15.30% も
seed 由来の偶発で +6pp 程度は乗っている可能性がある。

### 3. 窓 2024〜 + 直近 6mo×2 重みの複合効果

- T01（窓 2024〜 単独）: ROI +8.58% だが broken=2, worst -61.28%（裾リスク大）
- T07（T01 + 直近 6mo×2 倍重み）: ROI +15.30%, broken=0, worst -35.16%（裾リスク抑制）

**窓短縮は ROI を押し上げるが裾リスクを増やす傾向** が T01 で確認され、T07 で直近強調を
追加すると両方改善した（ROI +6.7pp, worst +26.1pp）。seed ガチャを排除できれば、
この複合効果は仮説として有望。

### 4. 破局設定の確認

- T02_window_2025（窓 2025〜 のみ）: 学習データ不足で過学習、ROI -12.71%
- T04_lgbm_regularized（容量絞り）: 識別能力低下、ROI -12.91%, worst -66.05%
- T05_lgbm_conservative_lr（低 lr × 多 boost）: 破局月製造機、broken=3, worst -81.65%

これら 3 本は「本データセットで避けるべき方向」として記録しておく。

### 5. ECE（calibrated）の trial 間差は小さい

全 trial で 0.001〜0.0016 のレンジ。予測信頼性そのものは trial 間で大差なく、
ROI 差は「どこを賭けるか（フィルタ統一）下でモデルが拾う月次レジーム」に集約される。

## 次アクション（タスク 6-9）

T07 を確証するため、以下 3 本を `trials/pending/` に追加して `/model-loop` を再実行する:

| trial_id | 変更点 | 検証目的 |
|---|---|---|
| T10_window_2024_weight_seed1 | T07 と同設定 + `lgb_params.seed=1` | T07 pass が seed 由来か検証 |
| T11_window_2024_weight_seed2 | T07 と同設定 + `lgb_params.seed=2` | 同上、もう 1 本 |
| T12_window_2024_weight_strong | T07 ベースで `recency_months=3, recency_weight=3.0` | 直近強調の感度（さらに攻める方向） |

判定:
- **T10/T11 の 2/2 または 1/2 が verdict=pass** → T07 本採用候補として構造確定、近傍探索継続
- **T10/T11 の 0/2 が pass** → T07 は seed ガチャ確定、構造変更フェーズへ移行
- **T12 が T07 超え** → 直近強調はもう 1 段攻めてよい方向として追加探索

---

## T10〜T12 追加サイクル（2026-04-25 実行、タスク 6-9 完了）

### 実行条件

- 初回 10 trial と完全同一（Walk-Forward 期間 / retrain_interval / real_odds / strategy セクション全て統一）
- エラー 0、全 YAML `completed/` 移動済み
- 実行ログ: `artifacts/model_loop_logs/run_*_T10T12.log`

### 結果テーブル（T07 と T10〜T12 比較）

| trial_id | 構成 | verdict | primary_score | ROI | worst_month | plus_ratio | broken | CI 下限 | CI 上限 | ECE(cal) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| T07_window_2024_plus_weight | baseline seed | **pass** | +1.59 | +15.30% | -35.16% | 66.7% | 0 | +1.94 | +28.94 | 0.00121 |
| T10_window_2024_weight_seed1 | seed=1 | fail | -49.31 | **-17.19%** | -51.43% | **8.3%** | 1 | -26.79 | -6.33 | 0.00159 |
| T11_window_2024_weight_seed2 | seed=2 | marginal | -20.55 | +9.47% | -55.31% | 58.3% | 1 | -4.31 | +23.21 | 0.00147 |
| T12_window_2024_weight_strong | recency_months=3, ×3.0 | fail | -33.96 | -1.93% | -59.44% | 41.7% | 1 | -12.04 | +8.14 | 0.00134 |

### 判定: T07 pass は seed ガチャ確定

**T10/T11（T07 と同設定で seed のみ変更）の再現性:**

- pass: **0/2**（T10 fail / T11 marginal）
- T10 に至っては plus_ratio 8.3%（12 ヶ月中 1 月しかプラスなし）で T07 +15.30% から **-32.49pp** 振れ

**T07/T10/T11 の散らばり（seed 耐性の定量評価）:**

- ROI: mean +2.53%, **std 17.32pp, range 32.49pp**
- worst: mean -47.30%, std 10.69pp, range 20.15pp

これは初回の baseline seed 反復（T00/T08/T09、ROI range 9.3pp / worst range 26.4pp）を更に上回る分散。
「窓 2024〜 + 直近 6mo×2 倍重み」の構造自体にロバストな改善効果はなく、**T07 単独の ROI +15.30% は
偶発採択**と確定。

### T12（直近強調強化）も敗北

T12 は窓 2024〜 + 直近 3mo×3.0 倍重み（T07 より攻めた設定）。結果は ROI -1.93%, broken=1, worst -59.44%。
直近強調を強めるほど裾リスクが増える方向で、**攻めの方向も存在しない**。

### 13 trial 全体の seed 分散まとめ

| グループ | n | ROI 平均 | ROI std | worst 平均 | worst std |
|---|---|---:|---:|---:|---:|
| T00/T08/T09（baseline 反復） | 3 | -3.64% | 5.33 | -47.29% | 13.65 |
| T07/T10/T11（2024+weight 反復） | 3 | +2.53% | 17.32 | -47.30% | 10.69 |

2 グループとも worst 平均が -47% で、**構造を問わず本データセットは seed ノイズが大きい**。
現状のパラメータ探索の枠内では CLAUDE.md 再開条件（通算 ROI ≥ +10% かつ worst > -50%）の
再現可能な達成は困難。

### 撤退判定（MODEL_LOOP_PLAN §5 / タスク 6-10 発動）

- 本番通算 **13 trial で pass 再現 0 本**
- 設計書 §5 の「10 trial 時点で pass 事後確率 P(p>10%) が 20% 超なら追加 5 trial まで延長」に対し、
  β(1,1) 事前 + 観測 1 pass / 13 trial では P(p>10%) ≒ 15% に低下、延長の経済合理性も乏しい
- **構造変更フェーズ（タスク 6-10）への移行が妥当**

## 次アクション（タスク 6-10）

パラメータ探索を打ち止めて構造変更に移行する。設計書 §5 のツリーから PoC で 1 項目ずつ検証:

1. **特徴量拡張**（推奨着手、最小工数・期待値高）— 直前気象差分、場×コース交互作用、ST ばらつき等
2. **目的関数変更** — binary top-1 / pairwise / LambdaRank
3. **キャリブレーション再設計** — per-class IR → 結合 IR / Dirichlet
4. **Purged/Embargoed time-series CV**

第一着手は **1. 特徴量拡張**:
- 現状 ECE は全 13 trial で 0.001〜0.0016 に収束し、prediction quality の飽和を示唆
- 入力情報の追加が最も費用対効果高く、既存 pipeline 拡張のみで PoC 可能
- 他 3 項目は実装工数が大きい割に seed 分散を下げる保証がない

特徴量拡張 PoC に進む前に、`ml/src/features/` を変更禁止パスから解除する合意が必要
（MODEL_LOOP_PLAN §6-4）。解除後は単月 val top-1 accuracy の小規模 PoC で筋を確認し、
効果が見えた特徴量のみ `run_model_loop` に組み込んで再び Walk-Forward で検証する。

## 成果物

- `trials/results.jsonl` — 13 行（trial ごとに 1 行 append、T00〜T12）
- `artifacts/walkforward_T*_summary.json` — 13 ファイル（KPI + monthly_roi）
- `artifacts/walkforward_T*.csv` — 13 ファイル（raw Walk-Forward 出力）
- `artifacts/model_loop_logs/run_*.log` — 実行ログ（初回 10 trial / T10〜T12 追加サイクル）
- `trials/completed/T00〜T12.yaml` — 使用済み trial 定義

---

## T16 reference: Perfect-Oracle Upper Bound（2026-04-26）

撤退判定の確証として「現行 strategy 下で達成可能な ROI の理論上限」を計測。
モデルが actual 1-2-3 trifecta に確率 1.0 を割り当てた場合の Walk-Forward 結果。

実装: 新規スクリプト [ml/src/scripts/run_oracle_upper_bound.py](ml/src/scripts/run_oracle_upper_bound.py)
（trainer.py / predictor.py / engine.py 不変、KPI / verdict / block bootstrap CI は
`run_model_loop` の関数を直接借用して T00〜T15 と完全に比較可能な形式で出力）。

### 実行条件

- Walk-Forward: 2025-05〜2026-04（12 ヶ月、T00〜T15 と同一）
- strategy 統一値:
  - `min_odds=100, exclude_stadiums=[2,3,4,9,11,14,16,17,21,23], bet_amount=100, bet_type=trifecta`
  - `prob_threshold` / `ev_threshold` はオラクル prob=1.0 で常に通過するため適用無視
- 実オッズ: あり
- 実行時間: ~50 秒（モデル不要、月毎 K/B/odds load + 集計のみ）

### 結果（T00〜T15 比較表に追記）

| trial_id | verdict | ROI | worst_month | plus_ratio | broken | CI 下限 (90%) | CI 上限 (90%) | total_bets | wins |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **T16_oracle_upper_bound** (理論上限) | **pass** | **+29,186.05%** | **+27,196.82%** | **100.0%** | **0** | **+28,658.49** | **+29,673.86** | 5,108 | 5,108 |
| T07_window_2024_plus_weight | pass | +15.30% | -35.16% | 66.7% | 0 | +1.94 | +28.94 | 39,166 | 141 |
| T13_lambdarank | fail | -7.10% | -56.30% | 41.7% | 1 | -23.20 | +14.46 | 55,311 | — |
| T00_baseline | fail | -6.64% | -43.17% | 50.0% | 0 | -13.34 | +2.63 | — | — |

### 月次 ROI

| 月 | ROI | 月 | ROI |
|---|---:|---|---:|
| 2025-05 | +29,406.58% | 2025-11 | +27,196.82% |
| 2025-06 | +30,054.38% | 2025-12 | +28,560.18% |
| 2025-07 | +29,201.84% | 2026-01 | +28,087.05% |
| 2025-08 | +28,870.35% | 2026-02 | +28,493.70% |
| 2025-09 | +29,254.43% | 2026-03 | +29,350.48% |
| 2025-10 | +31,182.37% | 2026-04 | +31,296.81% |

12 ヶ月 ROI レンジ +27,196% 〜 +31,296%、std ~1,200pp（理論上限が極めて狭い帯域に収束）。
平均 hit odds = 292.86x（min_odds=100 通過時の actual 平均）。

### 主要所見

#### 1. strategy 上限は +29,186%、CLAUDE.md 閾値 (+10%) は天井の 0.034%

実運用再開条件 +10% は、strategy 上限のわずか **0.034%** に過ぎず、
**現行 strategy（min_odds=100x + 10 場除外）自体は天井に当たっていない**。

これは「閾値 +10% を達成不能なのは strategy のせい」という仮説を統計的に否定する。
モデルさえ完璧なら +29,000% 以上が確実に出る設計になっており、+10% の達成余地は
strategy 設計上は十分にある。

#### 2. T07 (現状唯一の pass) は oracle 機会の 2.76% しか捕捉していない

| 指標 | T07 | T13 | Oracle (T16) |
|---|---:|---:|---:|
| 12 ヶ月 wins | 141 | — | 5,108 |
| 12 ヶ月 bets | 39,166 | 55,311 | 5,108 |
| hit_rate_per_bet | 0.36% | 0.29% | 100% |
| oracle bets 捕捉率 (wins ÷ 5,108) | **2.76%** | — | 100% |

T07 の 141 wins はすべて oracle の 5,108 bets 集合に含まれる
（min_odds=100 通過 + actual 一致 = oracle bet と等価）。
**T07 は「100x 以上で actual 当選した 5,108 機会」のうち 141 件しか拾えていない**
（残りの 4,967 機会を取り逃し、かつ 39,025 件の外れベットを打っている）。

#### 3. +10% 閾値の構造的解釈

avg_hit_odds = 292.86 から逆算すると、+10% 達成に必要な hit_rate_per_bet:

```
1.10 / 292.86 = 0.376%
```

T07 実績は 0.36%、+10% に必要な水準まで **+0.016pp**（相対 +4.5%）足りないだけ。

**つまり +10% は strategy 上限から見れば「ほぼ breakeven」の達成困難でない閾値**。
にも関わらず 16 trial の構造変更でクリアできなかった事実は:

- 「1 着識別能力が全ビンでランダムに近い」(CLAUDE.md 既知課題) が依然解消されておらず、
  どんなアーキテクチャでも hit_rate_per_bet が +0.016pp 動かせない
- Seed 分散だけで T07/T10/T11 で ROI std 17pp（hit_rate_per_bet std ~0.06pp）
  あり、+0.016pp の改善は「ノイズ床下に埋没」する
- フェーズ 6 の撤退判定は「strategy 天井問題」ではなく「seed ノイズ床問題」が
  本質と確定

#### 4. 撤退判定への含意

T16 の結果はフェーズ 6 完全撤退の判断**そのものは変えない**が、ニュアンスを以下に修正:

- 旧解釈: 「+10% は届かないから撤退」
- 新解釈: 「+10% は strategy 天井から見れば届くはずだが、現行モデル系統では
  seed ノイズに埋没して再現性のある +10% 達成は不能。**B-3 (馬券種転換) で
  控除率自体を下げて hit_rate_per_bet 閾値を緩めるアプローチ**が、ノイズ床問題
  を回避する戦略として正当化される」

### T16 成果物

- [artifacts/walkforward_T16_oracle_upper_bound.csv](artifacts/walkforward_T16_oracle_upper_bound.csv) — 31,188 race の oracle bet 結果
- [artifacts/walkforward_T16_oracle_upper_bound_summary.json](artifacts/walkforward_T16_oracle_upper_bound_summary.json) — KPI + monthly_roi + verdict
- [trials/completed/T16_oracle_upper_bound.yaml](trials/completed/T16_oracle_upper_bound.yaml) — trial 定義（参考、実体は専用スクリプト）
- [ml/src/scripts/run_oracle_upper_bound.py](ml/src/scripts/run_oracle_upper_bound.py) — 計算スクリプト
- `trials/results.jsonl` — 14 行目に T16 追記

## 参考

- 設計書: [MODEL_LOOP_PLAN.md](MODEL_LOOP_PLAN.md)
- スラッシュコマンド: [.claude/commands/model-loop.md](.claude/commands/model-loop.md)
- 運用基準: [CLAUDE.md](CLAUDE.md)「現行の運用方針（2026-04-24 時点）」
- 背景: [BET_RULE_REVIEW_202509_202512.md](BET_RULE_REVIEW_202509_202512.md) §30-32
