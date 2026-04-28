# MARKET_EFFICIENCY_RESULTS — フェーズ B-1 Step 1 結果

最終更新: 2026-04-26
ステータス: **Step 1 完了。歪みあり判定 → Step 2 へ進行を提案**
位置付け: [NEXT_PHASE_B1_PLAN.md](NEXT_PHASE_B1_PLAN.md) §2 Step 1 の実行結果

## 1. 実行内容

### スクリプト
[ml/src/scripts/run_market_efficiency.py](ml/src/scripts/run_market_efficiency.py)（新規、~430 行）。
モデルは一切使わず、`data/odds/` と `data/history/` のみで完結する。

### 実行コマンド

```bash
py -3.12 ml/src/scripts/run_market_efficiency.py \
  --start 2025-05 --end 2026-04 --bet-type trifecta \
  --split-halves --bootstrap 2000
```

### 入力データ
- 期間: 2025-05〜2026-04（12 ヶ月）
- オッズ: `data/odds/odds_*.parquet` × 12（646 万行 / 54,179 レース）
- 結果: K ファイルから 1-2-3 着の組合せを抽出（54,154 レース）
- 結合後: 646 万 combo / 54,154 レース

### 暗黙確率の定義
- `implied_p_raw = 1 / odds`
- `implied_p_norm = (1/odds) / Σ(1/odds)` （レース内 sum-to-1 正規化、メイン判定用）
- `implied_p_takeout = 0.75 / odds` （控除率 25% を仮定）

### ビニング
対数等間隔 10 ビン（右スキューに対応）:
`[0.0001, 0.0003, 0.001, 0.003, 0.01, 0.03, 0.05, 0.10, 0.20, 0.50, 1.0]`

### CI
- `actual_p` の Wilson 90% CI（ビン独立確認用）
- `lift = actual_p / implied_p_norm` の bootstrap 90% CI（n_resamples=2000、レース単位復元抽出 × 月 stratify、レース内相関を保つ）

## 2. 主要結果

### 全期間（2025-05〜2026-04, 12 ヶ月）

| 暗黙帯 (norm) | n | actual_p | implied_p | **lift** | mean_odds | **ev_all_buy** | 90% boot CI | 採用基準 |
|---|---:|---:|---:|---:|---:|---:|---|:---:|
| [0.0001, 0.0003) |   321,211 | 0.000097 | 0.000221 | **0.436** | 3,598x | 0.347 | [0.309, 0.564] | ✅ overpriced |
| [0.0003, 0.001)  | 1,381,309 | 0.000387 | 0.000622 | **0.621** | 1,343x | 0.519 | [0.576, 0.664] | ✅ overpriced |
| [0.001, 0.003)   | 1,765,368 | 0.001566 | 0.001829 | 0.856     |   451x | 0.707 | [0.829, 0.882] | — |
| [0.003, 0.01)    | 1,648,754 | 0.005370 | 0.005592 | 0.960     |   150x | 0.808 | [0.946, 0.975] | — |
| [0.01, 0.03)     |   903,725 | 0.017357 | 0.017117 | 1.014     |    48x | 0.836 | [1.003, 1.025] | — |
| [0.03, 0.05)     |   232,561 | 0.039276 | 0.038471 | 1.021     |    20x | 0.780 | [1.006, 1.036] | — |
| [0.05, 0.10)     |   167,087 | 0.069802 | 0.068208 | 1.023     |    11x | 0.795 | [1.010, 1.037] | — |
| [0.10, 0.20)     |    37,509 | 0.138340 | 0.125620 | **1.101** |   6.1x | 0.845 | [1.080, 1.122] | ✅ underpriced |
| [0.20, 0.50)     |     1,123 | 0.266251 | 0.222048 | **1.199** |   3.4x | 0.901 | [1.103, 1.293] | ✅ underpriced |

CSV: [artifacts/market_efficiency_2025-05_2026-04_trifecta.csv](artifacts/market_efficiency_2025-05_2026-04_trifecta.csv)
プロット: [artifacts/market_efficiency_2025-05_2026-04_trifecta.png](artifacts/market_efficiency_2025-05_2026-04_trifecta.png)

### 採用基準（B-1 PLAN §3）
- n ≥ 1,000 のビンで `lift ≥ 1.10` または `≤ 0.85`
- 90% bootstrap CI で `lift = 1.0` を含まない
- 前半 6 ヶ月 / 後半 6 ヶ月で同方向

**該当ビン: 4 / 9（全 9 ビン中 44%）**

### 前半 vs 後半 同方向確認

| 暗黙帯 (norm) | n_h1 | lift_h1 (5月-10月) | n_h2 | lift_h2 (11月-4月) | 同方向? |
|---|---:|---:|---:|---:|:---:|
| [0.0001, 0.0003) | 170,163 | 0.506 | 151,048 | 0.358 | YES |
| [0.0003, 0.001)  | 721,178 | 0.648 | 660,131 | 0.591 | YES |
| [0.001, 0.003)   | 922,195 | 0.860 | 843,173 | 0.852 | YES |
| [0.003, 0.01)    | 863,842 | 0.977 | 784,912 | 0.941 | YES |
| [0.01, 0.03)     | 475,219 | 1.023 | 428,506 | 1.004 | YES |
| [0.03, 0.05)     | 122,553 | 1.010 | 110,008 | 1.033 | YES |
| [0.05, 0.10)     |  87,049 | 1.011 |  80,038 | 1.037 | YES |
| [0.10, 0.20)     |  19,422 | 1.083 |  18,087 | 1.120 | YES |
| [0.20, 0.50)     |     577 | 1.157 |     546 | 1.243 | YES |

**全 9 ビンで前半・後半同方向**（一過性の偶然ではない）。

CSV: [artifacts/market_efficiency_2025-05_2025-10_trifecta.csv](artifacts/market_efficiency_2025-05_2025-10_trifecta.csv)、[artifacts/market_efficiency_2025-11_2026-04_trifecta.csv](artifacts/market_efficiency_2025-11_2026-04_trifecta.csv)

## 3. 解釈

### 観測されたパターン: 古典的 favorite-longshot bias の競艇版

```
暗黙確率帯           lift     解釈
─────────────────────────────────────────────────────────
低（< 0.001）        0.4-0.6  高オッズ過大評価（市場が買いすぎ）
中（0.003 - 0.05）   0.96-1.02 ほぼフェア
高（>= 0.10）        1.10-1.20 人気組合せ過小評価（市場が買い足りない）
```

これは競馬研究で繰り返し報告される **favorite-longshot bias**（高オッズが過大評価され、人気馬が割安）と整合する。**同パターンが競艇 3 連単市場でも統計的に有意に観測された**。

### ⚠️ 重要警告: lift > 1.0 でも控除率の壁は破れていない

`ev_all_buy = mean_odds × actual_p` は「該当ビンの全組合せを買った場合の期待値（1.0 が損益分岐）」。

| 暗黙帯 | lift | ev_all_buy | 全買い時の損益 |
|---|---:|---:|---:|
| [0.10, 0.20) | 1.101 | 0.845 | **-15.5%** |
| [0.20, 0.50) | 1.199 | 0.901 | **-9.9%** |

「lift > 1.10」は **控除率 25% に対して 10〜15% 戻したに過ぎない**。
ビン内の全組合せを買えば依然 -10〜-15% の損失で、**B-1 PLAN §3 Step 3 採用基準（通算 ROI ≥ +10%）** は満たさない。

ただし「ビン内全買い」と「ビン内サブセグメント買い」は別物。ビン内のサブセグメント（場別、コース別、オッズ帯別）で `ev_all_buy > 1.0` となる範囲があれば実用化候補となる。これが **Step 2 の領分**。

## 4. Step 1 判定

### B-1 PLAN §3 Step 1-2 採用基準

| 基準 | 結果 | 判定 |
|---|---|:---:|
| n ≥ 1,000 のビンで lift ≥ 1.10 または ≤ 0.85 | 4 ビン該当 | ✅ |
| 90% bootstrap CI で lift = 1.0 を含まない | 4 ビン全て CI が 1.0 を排除 | ✅ |
| 前半 6 ヶ月 / 後半 6 ヶ月で同方向 | 全 9 ビンで同方向 | ✅ |

**→ 歪みあり判定。Step 2 へ進行を提案。**

ただし **§3 Step 3 の合格条件（ROI ≥ +10%）は Step 1 結果から直接予測できる範囲では達成不能**（ev_all_buy max = 0.901）。Step 2 でサブセグメント分析を行い、ev_all_buy > 1.0 となる範囲が存在するかを確認する必要がある。

## 5. Step 2 提案

### 着手前の判断材料

歪みパターンは確かにある。ただし「全買いでは控除率を破れない」という事実から、Step 2 は以下を最優先で確認する:

1. **lift > 1.10 の高暗黙帯をサブセグメント分割**（implied 0.10〜0.50, n=38,632）
   - 場別 ROI（24 場）
   - コース別 ROI（1〜6 コース、特に 1 コース勝率の場依存性）
   - オッズ帯別 ROI（3-5x, 5-7x, 7-10x 等）
   - 月別（季節性）
2. **ev_all_buy > 1.0 となるサブセグメントの有無を確認**
3. **見つからなければ B-1 撤退**（lift > 1.10 はあるが活用不能）

Step 2 のスクリプト想定:
- 既存 `run_market_efficiency.py` に `--group-by stadium / course / odds_band / month` オプションを追加
- もしくは別途 `run_market_efficiency_segments.py` を新規作成（300 行程度）

### Step 2 の合格条件（B-1 PLAN §3 と整合）
あるサブセグメントで:
- `n ≥ 1,000`
- `lift_boot_lo > 1.0`（CI 下限が 1.0 を超える）
- `ev_all_buy > 1.0`（控除率を破る）
- 前半 / 後半同方向

これを満たすサブセグメントが見つかった場合のみ Step 3（戦略立案 + バックテスト）へ進む。

### Step 2 の撤退基準
- lift > 1.10 帯のどのサブセグメントも `ev_all_buy <= 1.0` → B-1 撤退（NEXT_PHASE_B1_PLAN.md §8）

## 6. ビン内 EV プロファイルの補足観察

`ev_all_buy` の分布から、暗黙確率を変えても「全買い ROI」は控除率程度に収まる:

```
暗黙帯           ev_all_buy    全買い ROI
[0.0001, 0.0003)   0.347        -65%
[0.0003, 0.001)    0.519        -48%
[0.001, 0.003)     0.707        -29%
[0.003, 0.01)      0.808        -19%
[0.01, 0.03)       0.836        -16%
[0.03, 0.05)       0.780        -22%
[0.05, 0.10)       0.795        -21%
[0.10, 0.20)       0.845        -15%   ← lift > 1.10 でも -15%
[0.20, 0.50)       0.901        -10%   ← lift > 1.10 でも -10%
```

**最も損失が小さいのは implied >= 0.20 帯で -10%**。これは「人気帯を狙えば控除率の半分は取り戻せる」程度の歪みであり、絞り込みなしでは黒字化しない。

参考: 既存 `strategy_default.yaml` の `min_odds = 100`（オッズ 100x 未満を除外）は、本分析の最低 ev_all_buy 帯（implied < 0.001、odds 1,343-3,598x）を**除外する方向と逆**であり、実は high-odds bias の活用機会を逃している可能性がある。Step 2 では既存 strategy の縛りを取り払って分析する。

## 7. 次アクション提案

| アクション | 採否 | 理由 |
|---|:---:|---|
| **Step 2: サブセグメント分析** | 推奨 | 歪み確認、ev_all_buy > 1.0 の検出が必要 |
| Step 3 にスキップして戦略バックテスト | 不可 | ev_all_buy が全帯 < 1.0 のまま戦略を立てると確実に負ける |
| B-1 撤退 | 早計 | サブセグメントで黒字化可能な範囲があるか未確認 |

**ユーザーへの確認事項**:
1. Step 2 へ進めるか
2. Step 2 のスコープを (a) 既存スクリプトへ `--group-by` 追加 か (b) 別スクリプト新設 のどちらにするか
3. Step 2 でフォーカスするビン: 最有望は `[0.10, 0.20)` （n=37,509、lift=1.10、ev_all_buy=0.845）。この帯のみ細分するか、全帯サブセグメント分析するか

## 8. 厳守事項（NEXT_PHASE_B1_PLAN §5 より）

- ❌ 既存モデル（trainer / predictor / engine）は触らない（Step 1 で遵守 ✅）
- ❌ オッズ追加 DL はしない（Step 1 で遵守 ✅）
- ❌ Step 1-2 の歪み確認前に Step 3 のバックテストを始めない（Step 2 へ進む前の制約）
- ❌ 既存の購入条件（prob ≥ 7%、EV ≥ 2.0 等）を Step 3 戦略に流用しない
- ❌ サンプル小（n < 1,000）には飛びつかない（Step 2 でも遵守する）

## 9. 関連ドキュメント

- [NEXT_PHASE_B1_PLAN.md](NEXT_PHASE_B1_PLAN.md) — B-1 全体計画、本ドキュメントの上位設計書
- [LAMBDARANK_WALKFORWARD_RESULTS.md](LAMBDARANK_WALKFORWARD_RESULTS.md) — フェーズ 6 撤退の確証
- [BET_RULE_REVIEW_202509_202512.md](BET_RULE_REVIEW_202509_202512.md) §28-32 — 実運用再開条件
- [AUTO_LOOP_PLAN.md](AUTO_LOOP_PLAN.md) — フェーズ 7 セクション
- [CLAUDE.md](CLAUDE.md) — 「現在の仕様」「現行の運用方針」

---

## 10. P-v: race condition × odds_band 事前検証（2026-04-28）

### 10.1 背景

B-1 trifecta / B-3 win / 拡張 A 複勝 の 3 券種すべてで「控除率を縮める弱い歪みはあるが
収支プラス化までは至らない」構造的結論が確定済み（最善 ev: 0.98 / 0.964 / 0.93）。

LLM 予想 (P 系列) の今後を議論する前に、**まだ切っていない race condition × odds 軸**
で歪みが残っていないかを最終 sanity check として確認する。

### 10.2 実装

`run_market_efficiency.py` に以下を追加（既存ロジック書換えなし、~75 行追加）:

- `load_race_conditions(start, end)` — K ファイルから race_id 単位の `weather` / `wind_speed` を抽出
- `add_group_column()` に新軸 2 つ追加:
  - `wind_speed_band`: `[0,2)`, `[2,5)`, `[5,8)`, `[8+)`
  - `weather`: `晴` / `曇` / `雨` / `霧` / `雪` / `unknown`
- argparse choices 拡張、conditions merge は要求された場合のみ実行（履歴データの二重ロードを最小化）

### 10.3 実行コマンド

```bash
py -3.12 ml/src/scripts/run_market_efficiency.py \
  --start 2025-05 --end 2026-04 --bet-type trifecta \
  --skip-step1 --bootstrap 2000 \
  --group-by wind_speed_band weather \
  --group-by-2axis wind_speed_band,odds_band weather,odds_band \
  --focus-bin-lower 0.10 --focus-bin-upper 0.50
```

### 10.4 結果（trifecta、12 ヶ月、focus implied_p_norm ∈ [0.10, 0.50)）

#### 単軸 wind_speed_band

| wind_speed_band | n | lift | ev_all_buy | ev CI | flag |
|---|---:|---:|---:|---|:---:|
| `[0,2)` | 10,739 | 1.13 | 0.88 | [0.85, 0.91] | — |
| `[2,5)` | 22,896 | 1.11 | 0.86 | [0.84, 0.88] | — |
| `[5,8)` |  4,575 | 1.01 | 0.78 | [0.74, 0.83] | — |

`[8+)` は n < 1,000 で除外。**強風で歪むという仮説は逆** — `[5,8)` が最も lift = 1.0 に近く、
市場が風強条件を織り込み済み（むしろ過剰調整気味）。

#### 単軸 weather

| weather | n | lift | ev_all_buy | ev CI | flag |
|---|---:|---:|---:|---|:---:|
| `雨` |  3,547 | 1.15 | 0.89 | [0.84, 0.95] | — |
| `曇` |  9,991 | 1.11 | 0.86 | [0.83, 0.89] | — |
| `晴` | 24,925 | 1.10 | 0.85 | [0.83, 0.87] | — |

雨天は lift 1.15 で最大だが ev 0.89、CI 上限 0.95 < 1.0 で控除率を破らず。

#### 2 軸 wind_speed_band × odds_band（n ≥ 1000、上位 5 セル）

| wind × odds_band | n | lift | ev | ev CI | flag |
|---|---:|---:|---:|---|:---:|
| **`[0,2) \| [1,5)`** | 1,760 | **1.25** | **0.95** | **[0.88, 1.02]** | — |
| `[2,5) \| [5,10)` | 18,959 | 1.11 | 0.84 | [0.82, 0.87] | — |
| `[2,5) \| [1,5)` |  3,937 | 1.11 | 0.84 | [0.80, 0.88] | — |
| `[0,2) \| [5,10)` |  8,979 | 1.10 | 0.83 | [0.80, 0.87] | — |
| `[5,8) \| [5,10)` |  3,887 | 0.99 | 0.75 | [0.70, 0.80] | — |

最善 `[0,2) | [1,5)` で ev 0.95、CI 上限 1.02 が辛うじて 1.0 を超えるが点推定 < 1.0 で確信なし。

#### 2 軸 weather × odds_band（n ≥ 1000、上位 5 セル）

| weather × odds_band | n | lift | ev | ev CI | flag |
|---|---:|---:|---:|---|:---:|
| `曇 \| [1,5)` |  1,692 | 1.19 | 0.90 | [0.84, 0.97] | — |
| `雨 \| [5,10)` |  2,942 | 1.14 | 0.86 | [0.80, 0.92] | — |
| `晴 \| [1,5)` |  4,132 | 1.12 | 0.85 | [0.81, 0.89] | — |
| `晴 \| [5,10)` | 20,793 | 1.10 | 0.83 | [0.81, 0.85] | — |
| `曇 \| [5,10)` |  8,299 | 1.08 | 0.82 | [0.78, 0.85] | — |

### 10.5 採用判定

**flagged = 0 / 全 16 valid segments（n ≥ 1000）**

- 単軸: 6 segments / 0 flagged
- 2 軸: 10 segments / 0 flagged
- 採用基準: `lift_boot_lo > 1.0` かつ `ev_all_buy > 1.0` かつ `ev_boot_lo > 1.0`

### 10.6 構造的結論

B-1 trifecta（最善 0.98） + B-3 win（最善 0.964） + 拡張 A 複勝（最善 0.93）+
本 P-v race condition 軸（最善 0.95）の **4 系統すべてで「控除率を破る歪みなし」を確認**。

合計 200 + segments を across 3 bet types × 6 grouping axes（stadium / course / odds_band /
month / wind_speed_band / weather）で評価しても採用基準達成 0。

**B 系列完全凍結確定**（[CLAUDE.md](CLAUDE.md) 現行運用方針反映済み）。

連系券種（2 連単 / 2 連複 / 拡連複）も控除率 23〜25% で大差なく、組合せ数も中間（15〜30）の
ため、本構造的結論を覆す根拠が薄い → 連系券種 DL も着手しない。

### 10.7 出力 CSV

- [artifacts/market_efficiency_segment_wind_speed_band_focus_0.10-0.50_2025-05_2026-04_trifecta.csv](artifacts/market_efficiency_segment_wind_speed_band_focus_0.10-0.50_2025-05_2026-04_trifecta.csv)
- [artifacts/market_efficiency_segment_weather_focus_0.10-0.50_2025-05_2026-04_trifecta.csv](artifacts/market_efficiency_segment_weather_focus_0.10-0.50_2025-05_2026-04_trifecta.csv)
- [artifacts/market_efficiency_segment_wind_speed_bandXodds_band_focus_0.10-0.50_2025-05_2026-04_trifecta.csv](artifacts/market_efficiency_segment_wind_speed_bandXodds_band_focus_0.10-0.50_2025-05_2026-04_trifecta.csv)
- [artifacts/market_efficiency_segment_weatherXodds_band_focus_0.10-0.50_2025-05_2026-04_trifecta.csv](artifacts/market_efficiency_segment_weatherXodds_band_focus_0.10-0.50_2025-05_2026-04_trifecta.csv)
- ラン log: [artifacts/market_efficiency_condition_2025-05_2026-04_trifecta_run.log](artifacts/market_efficiency_condition_2025-05_2026-04_trifecta_run.log)
