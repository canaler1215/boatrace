# MARKET_EFFICIENCY_SEGMENT_RESULTS — フェーズ B-1 Step 2 結果

最終更新: 2026-04-26
ステータス: **🛑 B-1 撤退確定（2026-04-26 ユーザー合意）。案 A 完全凍結状態へ移行。全フェーズ撤退完了**
位置付け: [NEXT_PHASE_B1_PLAN.md](NEXT_PHASE_B1_PLAN.md) §2 Step 2 / [MARKET_EFFICIENCY_RESULTS.md](MARKET_EFFICIENCY_RESULTS.md) §5 の続き

## 1. 実行内容

### スクリプト
[ml/src/scripts/run_market_efficiency.py](ml/src/scripts/run_market_efficiency.py) を Step 2 用に拡張（`--group-by`, `--focus-bin-lower/upper` 引数追加、サブセグメント集計 / bootstrap / 採用判定関数を追加）。

### 実行コマンド

```bash
py -3.12 ml/src/scripts/run_market_efficiency.py \
  --start 2025-05 --end 2026-04 \
  --bootstrap 2000 --skip-step1 \
  --group-by stadium course odds_band month
```

### Focus 帯
`implied_p_norm ∈ [0.10, 0.50)` — Step 1 で採用基準達成した「人気組合せ過小評価」帯
- focus combos: 38,632 / 23,768 races / 5,488 hits
- mean odds = 6.03

### 採用基準（Step 2）
- `n ≥ 1,000`
- `lift_boot_lo > 1.0` （CI 下限が 1.0 を超える = 確信を持って割安）
- `ev_all_buy > 1.0` （控除率を破る点推定）
- `ev_boot_lo > 1.0` （控除率を破る確信あり）

## 2. 結果サマリー

### 採用基準該当: **0 / 21 サブセグメント**

| 軸 | サブセグメント数 (n≥1000) | ev_all_buy 最高 | ev CI 上限 | 採用 |
|---|---:|---:|---:|:---:|
| stadium | 21 / 21 | 0.96 (7.Gamagori) | 1.03 | 0 |
| course  | 2 / 6 | 0.86 (1コース) | 0.87 | 0 |
| odds_band | 2 / 6 | 0.87 ([1,5)) | 0.90 | 0 |
| month | 12 / 12 | 0.89 (2026-04) | 0.96 | 0 |

**lift > 1.0 は多数だが、控除率を破る組合せは単軸では発見できなかった。**

### 軸別上位 5 サブセグメント

#### Stadium（場別）

| stadium | n | lift | lift CI | ev_all_buy | ev CI | 採用 |
|---|---:|---:|---|---:|---|:---:|
| 7. Gamagori（蒲郡）  | 1,931 | 1.24 | [1.14, 1.33] | 0.96 | [0.88, 1.03] | × |
| 24. Omura（大村）    | 2,316 | 1.20 | [1.12, 1.28] | 0.93 | [0.87, 1.00] | × |
| 1. Kiryu（桐生）     | 1,325 | 1.20 | [1.08, 1.32] | 0.92 | [0.83, 1.02] | × |
| 20. Wakamatsu（若松）| 1,676 | 1.17 | [1.07, 1.27] | 0.92 | [0.84, 0.99] | × |
| 13. Amagasaki（尼崎）| 1,640 | 1.17 | [1.06, 1.27] | 0.90 | [0.82, 0.98] | × |

24 場のうち 21 場が `n ≥ 1,000`、`ev_all_buy` の範囲は 0.75〜0.96。

最有望は **7. Gamagori（蒲郡）** で `ev_all_buy=0.96, CI=[0.88, 1.03]`。CI 上限は 1.0 を含むため、控除率を破る確信は持てない。

#### Course（1 着艇番別）

focus 帯（implied 0.10〜0.50）は本質的に「1 コース勝ちの組合せ」のみ:
- 1 コース勝ち: n=36,969（全体の 96%）、lift=1.11, ev=0.86
- 2 コース勝ち: n=1,034（3%）、lift=1.10, ev=0.84

3〜6 コース勝ちは focus 帯内に存在しない（高人気組合せの 1 着は 1 コース支配）。
**course 軸の分離効果は無い**。

#### Odds_band（オッズ帯）

| 帯 | n | lift | lift CI | ev_all_buy | ev CI |
|---|---:|---:|---|---:|---|
| [1, 5)   | 6,454 | 1.14 | [1.10, 1.19] | 0.87 | [0.83, 0.90] |
| [5, 10)  | 32,178 | 1.10 | [1.07, 1.12] | 0.83 | [0.81, 0.85] |

オッズ 1〜5 倍の超人気組合せでも `ev_all_buy=0.87`。**オッズ低下方向にさらに絞っても控除率を破れない**。

#### Month（月別）

12 ヶ月すべてで `lift > 1.0`（最大 1.15、最小 1.02）、`ev_all_buy 0.79〜0.89`。
- 最高: 2026-04（ev=0.89, CI=[0.83, 0.96]）
- 最低: 2025-07（ev=0.79, CI=[0.74, 0.84]）

季節性は弱く、**特定月での顕著な歪みは無い**。

## 3. 観察

### 観察 1: lift と ev_all_buy のギャップ

`lift > 1.10` のサブセグメントは多数（stadium 上位、odds_band [1,5)、複数月）。しかし `ev_all_buy` は最大 0.96 で控除率を破れない。

これは構造的に説明できる:
- 控除率 25% が原理上限。lift = 1.0 なら ev_all_buy = 0.75
- lift = 1.10 なら ev_all_buy ≈ 0.825、lift = 1.20 で ev_all_buy ≈ 0.90
- 控除率を破るには **lift ≈ 1.33 以上が必要**
- 単軸では最高 lift = 1.24（蒲郡）まで。あと 1.09 倍足りない

### 観察 2: course 軸は事実上機能していない

focus 帯は構造的に「1 コース勝ち」がほぼ全て。course を group_by しても本質的な分離にならない。

### 観察 3: stadium 上位場の解釈

蒲郡・大村・桐生・若松・尼崎の 5 場は:
- いずれも 1 コース勝率が高いことで知られる場
- 人気組合せが期待通り決まりやすい → lift > 1.10
- ただし市場もそれを反映しており、控除率を破るほどの「読み残し」は無い

### 観察 4: 2 軸組合せの未確認

単軸分析は完了したが、**2 軸組合せ**（例: 蒲郡 × オッズ [1,5)、大村 × 1 コース勝ち）は未確認。
2 軸では `ev_all_buy > 1.0` の可能性は数学的には残る。ただし:
- 単軸最高でも CI 上限 1.03 にしか届かない（蒲郡）
- 2 軸組合せで n が小さくなると n ≥ 1,000 を満たせない懸念
- 仮に黒字化サブセグメントが見つかっても、サンプルサイズの問題で実用性は限定的になりやすい

## 4. Step 2 判定

### 単軸分析の結論
**B-1 PLAN §3 の Step 2-3 採用基準（ev_all_buy > 1.0 + ev CI 下限 > 1.0）達成サブセグメント = 0**

これは [NEXT_PHASE_B1_PLAN.md](NEXT_PHASE_B1_PLAN.md) §8 の撤退基準:
> Step 2 でセグメントを細分しても有意な歪みが見つからない

に**ほぼ該当**するが、2 軸組合せが未確認のため厳密には撤退確定ではない。

## 5. Step 2 / 2 軸組合せ追加分析（2026-04-26、ユーザー指示で実施）

### 実行内容
ユーザー判断（案 B）を受けて 2 軸組合せ分析を実施。

```bash
py -3.12 ml/src/scripts/run_market_efficiency.py \
  --start 2025-05 --end 2026-04 \
  --bootstrap 2000 --skip-step1 \
  --group-by-2axis stadium,odds_band stadium,course stadium,month
```

### 採用基準達成: **0 / 41 サブセグメント**（n ≥ 1,000 のみカウント）

| ペア | 全 cell 数 | n≥1000 cell 数 | ev_all_buy 最高 | ev CI 上限 | 採用 |
|---|---:|---:|---:|---:|:---:|
| stadium × odds_band | 48 | 20 | 0.94 (7.Gamagori \| [5,10)) | 1.03 | 0 |
| stadium × course    | 127 | 21 | **0.98** (7.Gamagori \| 1) | 1.06 | 0 |
| stadium × month     | 278 | 0 | — | — | 0 |

### ペア別最有望 cell

#### stadium × odds_band
| cell | n | lift | lift CI | ev_all_buy | ev CI |
|---|---:|---:|---|---:|---|
| 7. Gamagori \| [5, 10)  | 1,597 | 1.24 | [1.13, 1.36] | 0.94 | [0.86, 1.03] |
| 24. Omura \| [5, 10)    | 1,854 | 1.20 | [1.11, 1.31] | 0.91 | [0.84, 0.99] |
| 20. Wakamatsu \| [5, 10)| 1,336 | 1.20 | [1.07, 1.32] | 0.90 | [0.81, 1.00] |
| 13. Amagasaki \| [5, 10)| 1,384 | 1.18 | [1.05, 1.31] | 0.89 | [0.80, 0.99] |
| 1. Kiryu \| [5, 10)     | 1,142 | 1.14 | [1.01, 1.28] | 0.87 | [0.76, 0.97] |

n ≥ 1,000 セルは ほぼすべて `[5, 10)` 帯のみ（focus implied 0.10〜0.50 が odds 5〜10 倍に集中）。
**stadium 単軸 ev=0.96 → stadium × odds_band 最高 ev=0.94 でわずかに低下**。

#### stadium × course（最有望ペア）
| cell | n | lift | lift CI | ev_all_buy | ev CI |
|---|---:|---:|---|---:|---|
| **7. Gamagori \| course=1**   | 1,821 | 1.27 | [1.16, 1.37] | **0.98** | [0.90, 1.06] |
| 1. Kiryu \| course=1          | 1,247 | 1.21 | [1.09, 1.33] | 0.93 | [0.84, 1.03] |
| 24. Omura \| course=1         | 2,228 | 1.18 | [1.10, 1.26] | 0.92 | [0.86, 0.98] |
| 20. Wakamatsu \| course=1     | 1,637 | 1.17 | [1.07, 1.27] | 0.91 | [0.84, 0.99] |
| 5. Tamagawa \| course=1       | 1,311 | 1.16 | [1.04, 1.28] | 0.89 | [0.80, 0.98] |

**最有望 cell: 7. Gamagori（蒲郡）× course=1（1 コース勝ち）**
- n=1,821（十分なサンプル）
- lift=1.27、`lift_boot_lo=1.16 > 1.0`（割安は確信を持って言える）
- ev_all_buy=0.98（控除率まであと **2pp**）
- ev CI=[0.90, 1.06] → **CI 上限が 1.0 を超える唯一のセル**だが、CI 下限が 0.90 で破る確信は持てない

#### stadium × month
278 cell すべてが `n < 1,000`。focus 内 38,632 / 288 ≈ 134/cell 平均でサンプル不足。**集計効果なし**。

### 観察 5: 蒲郡 × course=1 の境界線

最有望 cell（蒲郡 × 1 コース勝ち）でも `ev_all_buy=0.98` で控除率を破れない。
- lift=1.27 は強い歪みだが、控除率破壊には `lift ≈ 1.33` が必要
- CI 上限が 1.06 まで達するため「サンプル変動次第では破れる」可能性は数学的に残るが、CI 下限 0.90 で **黒字化の確信なし**
- これ以上絞り込んでも n が小さくなり統計的有意性を失う

## 6. Step 2 統合判定

### B-1 PLAN §3 Step 2-3 採用基準（ev_boot_lo > 1.0 が必須）達成: **0 / 全 62 サブセグメント**

| 段階 | サブセグメント数（n≥1000） | 採用 |
|---|---:|---:|
| Step 2 単軸 | 21 (stadium 21 + course 2 + odds_band 2 + month 12 → 重複ありで 37、ユニーク n≥1000 で 21) | 0 |
| Step 2 / 2 軸組合せ | 41 (stadiumXodds_band 20 + stadiumXcourse 21 + stadiumXmonth 0) | 0 |
| **合計** | **62** | **0** |

### 結論: **B-1 撤退条件を満たす**

[NEXT_PHASE_B1_PLAN.md](NEXT_PHASE_B1_PLAN.md) §8 の撤退条件:
> Step 2 でセグメントを細分しても有意な歪みが見つからない

に該当。

- 単軸最高 ev=0.96（蒲郡）→ 2 軸最高 ev=0.98（蒲郡 × 1 コース）でわずかに改善するも、控除率を破る確信を得られない
- 控除率破壊に必要な `lift ≈ 1.33` を超えるサブセグメントは n ≥ 1,000 では存在しない
- stadium × month のさらなる細分は n 不足で集計不能
- これ以上の細分はサンプルサイズ問題で統計的有意性を失う

### 構造的説明

競艇 3 連単市場には favorite-longshot bias が確かに存在し、人気組合せで `lift > 1.10〜1.27` が観測されるが、**控除率 25% を破るほど大きくはない**。市場参加者は人気組合せをわずかに過小評価しているが、その歪みは控除率の半分程度（lift 1.10〜1.27、ev_all_buy で 0.83〜0.98）に留まる。

これは競馬研究で報告される favorite-longshot bias が「収支マイナス幅を縮める」効果に留まり「収支プラス化」までは至らないという観測と整合する。

## 7. 次アクション提案

### 案 A: B-1 撤退、案 A 完全凍結（推奨）
- 根拠: 単軸 21 + 2 軸 41 = **計 62 サブセグメントすべてで控除率破れず**
- 撤退後の状態: フェーズ 3 凍結 + フェーズ 6 完全撤退 + フェーズ 7 (B-1) 撤退 = **全フェーズ撤退**
- NEXT_PHASE_B1_PLAN §8 に従って:
  - 本ドキュメントに「B-1 撤退結果」セクションを追加 ✅（本セクション）
  - CLAUDE.md / AUTO_LOOP_PLAN.md を「全フェーズ撤退（A 完全凍結）状態」に更新

### 案 B': さらなる細分（非推奨）
- 蒲郡 × 1 コース × オッズ [5, 10) → n=? の 3 軸組合せは n が 1,000 を割る蓋然性が高い
- focus_bin を [0.20, 0.50) に絞る → n=1,123 でサブセグメントが軒並み n < 1,000
- いずれも統計的有意性を失う方向

### 案 C': B-2 / B-3 等の他候補（B-1 PLAN §8 の最終段落）
- データソース拡張、馬券種転換等は別フェーズの話
- 本セッションでは扱わない

## 8. 推奨

**案 A（B-1 撤退、案 A 完全凍結）を推奨**。理由:

1. **62 サブセグメント全敗**は十分な検証で、これ以上の細分は統計的有意性を失う
2. LAMBDARANK_WALKFORWARD_RESULTS の「採用基準達成 0」の確証パターンと整合
3. 競艇 3 連単市場の favorite-longshot bias は「控除率を縮める効果」止まりという構造的結論が出た
4. 2 軸最高 ev=0.98（蒲郡 × 1 コース）が最終的な天井であり、これでは実運用再開条件（通算 ROI ≥ +10%）を満たせない

ユーザー合意後に NEXT_PHASE_B1_PLAN §8 に従ってドキュメント更新を行う。

## 9. 成果物

### 新規 / 更新ファイル
- [ml/src/scripts/run_market_efficiency.py](ml/src/scripts/run_market_efficiency.py) — Step 2 単軸 + 2 軸拡張（合計 ~830 行）
- 単軸:
  - [artifacts/market_efficiency_segment_stadium_focus_0.10-0.50_2025-05_2026-04_trifecta.csv](artifacts/market_efficiency_segment_stadium_focus_0.10-0.50_2025-05_2026-04_trifecta.csv)
  - [artifacts/market_efficiency_segment_course_focus_0.10-0.50_2025-05_2026-04_trifecta.csv](artifacts/market_efficiency_segment_course_focus_0.10-0.50_2025-05_2026-04_trifecta.csv)
  - [artifacts/market_efficiency_segment_odds_band_focus_0.10-0.50_2025-05_2026-04_trifecta.csv](artifacts/market_efficiency_segment_odds_band_focus_0.10-0.50_2025-05_2026-04_trifecta.csv)
  - [artifacts/market_efficiency_segment_month_focus_0.10-0.50_2025-05_2026-04_trifecta.csv](artifacts/market_efficiency_segment_month_focus_0.10-0.50_2025-05_2026-04_trifecta.csv)
- 2 軸:
  - [artifacts/market_efficiency_segment_stadiumXodds_band_focus_0.10-0.50_2025-05_2026-04_trifecta.csv](artifacts/market_efficiency_segment_stadiumXodds_band_focus_0.10-0.50_2025-05_2026-04_trifecta.csv)
  - [artifacts/market_efficiency_segment_stadiumXcourse_focus_0.10-0.50_2025-05_2026-04_trifecta.csv](artifacts/market_efficiency_segment_stadiumXcourse_focus_0.10-0.50_2025-05_2026-04_trifecta.csv)
  - [artifacts/market_efficiency_segment_stadiumXmonth_focus_0.10-0.50_2025-05_2026-04_trifecta.csv](artifacts/market_efficiency_segment_stadiumXmonth_focus_0.10-0.50_2025-05_2026-04_trifecta.csv)

### 関連ドキュメント
- [MARKET_EFFICIENCY_RESULTS.md](MARKET_EFFICIENCY_RESULTS.md) — Step 1 結果
- [NEXT_PHASE_B1_PLAN.md](NEXT_PHASE_B1_PLAN.md) — B-1 全体計画
- [LAMBDARANK_WALKFORWARD_RESULTS.md](LAMBDARANK_WALKFORWARD_RESULTS.md) — フェーズ 6 撤退の確証（参考流儀）

## 10. 厳守事項チェック（NEXT_PHASE_B1_PLAN §5）

- ✅ 既存モデル（trainer / predictor / engine）は触らない
- ✅ オッズ追加 DL はしない
- ✅ Step 1-2 の歪み確認前に Step 3 のバックテストを始めていない
- ✅ 既存購入条件（prob ≥ 7%、EV ≥ 2.0 等）を Step 2 採用判定に流用していない
- ✅ サンプル小（n < 1,000）には飛びついていない（min_n=1,000 縛り適用）
