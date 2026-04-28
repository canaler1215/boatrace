# MARKET_EFFICIENCY_PLACE_RESULTS — フェーズ B-3 拡張 A: 複勝市場効率分析の結果

最終更新: 2026-04-28
ステータス: **R1 + R2 + R3 完了 → B-3 拡張 A 撤退確定（採用基準達成 0 / 全 81 セグメント）**
位置付け: B-3 単勝（win）撤退確定後の保険分析 = 同じ控除率 20% の複勝で歪み構造を再評価する

参照: [NEXT_PHASE_B3_PLAN.md](NEXT_PHASE_B3_PLAN.md), [MARKET_EFFICIENCY_WIN_RESULTS.md](MARKET_EFFICIENCY_WIN_RESULTS.md)（B-3 win 撤退結果）, [NEXT_SESSION_PROMPT_A_R3.md](NEXT_SESSION_PROMPT_A_R3.md)（R3 起点プロンプト）

> ⚠️ **重要訂正（2026-04-28）**: 本ドキュメント §1〜§7 は「複勝 = top-3」を前提とした誤認定で書かれている。
> 競艇の複勝は **top-2 (1〜2 着)** が正しい仕様（公式: BOAT RACE オフィシャル）。
> §9 以降に訂正と R1/R2 の正しい結果を記載。§1〜§7 は履歴として残置。

## 1. Step 1 概要 — 複勝オッズ DL の API 動作確認

### 目的

12 ヶ月本番 DL（推定 12〜24 時間）に入る前に、boatrace.jp で複勝オッズが取得可能か、データ形式は分析に使えるかを 1 ヶ月試行 DL で確認する。

### 実装

| ファイル | 変更内容 |
|---|---|
| `ml/src/collector/openapi_client.py` | `fetch_place_odds(stadium_id, race_date, race_no) -> dict[str, tuple[float, float]]` 追加 |
| `ml/src/collector/odds_downloader.py` | `_place_cache_path`, `_place_df_to_map`, `_save_place_cache`, `download_place_odds_for_races`, `load_or_download_month_place_odds` 追加 |

### DL ソース

- **エンドポイント**: `https://boatrace.jp/owpc/pc/race/oddstf?hd=YYYYMMDD&jcd=XX&rno=N`
  （単勝・複勝合算ページ。`fetch_win_odds` と同じ URL）
- **方式**: `oddstf` ページ内 2 表（単勝表 / 複勝表）のうち、**オッズ列が範囲表記（`"X.X-Y.Y"`）の方**を複勝として採用 → `fetch_win_odds` と論理が逆
- **キャッシュ形式**: `data/odds/place_odds_YYYYMM.parquet`（カラム: `race_id, combination, odds_low, odds_high`）
  - `combination` ∈ {"1"〜"6"}（艇番文字列）
  - `(low, high)` 2 値保存により Step 2 で「保守的評価 = low / 期待値ベース = mid / 最大評価 = high」を選択可能

## 2. 試行 DL 結果（2025-12）

### 取得サマリー

| 指標 | 値 | 評価 |
|---|---:|---|
| 対象レース数（K ファイル） | 4,771 | — |
| 取得成功レース数 | **4,749（99.5%）** | ✅ |
| 取得失敗（empty）レース数 | 22（0.5%） | △ 単勝 (0) より多いが許容範囲 |
| Parquet 行数 | 28,271 | — |
| 全艇取得率 | 28,271 / (4,749 × 6) = **99.2%** | ✅ |
| 6 艇全揃いレース率 | 4,539 / 4,749 = **95.6%** | ✅ |
| 所要時間 | 約 75 分（11:02〜12:17） | 単勝と同等、12 ヶ月で約 **15 時間**見込み |

### レース内取得艇数の分布

| 艇数 | レース数 | 割合 |
|---:|---:|---:|
| 6 | 4,539 | 95.6% |
| 5 | 199 | 4.2% |
| 4 | 9 | 0.2% |
| 3 | 2 | 0.04% |

→ 6 艇全揃い 95.6%（単勝の 94.2% より +1.4pp 良い）。欠場（B欠）等で艇数が減るレース 4.4%。

### 艇番別取得数

| 艇番 | 取得数 |
|---:|---:|
| 1 | 4,740 |
| 2 | 4,733 |
| 3 | 4,736 |
| 4 | 4,730 |
| 5 | 4,699 |
| 6 | 4,633 |

→ 艇番 6 がやや少ない（欠場が他艇よりやや多い）。単勝と同じ傾向。

### オッズ統計

| 指標 | odds_low | odds_high | odds_mid | range (high-low) |
|---:|---:|---:|---:|---:|
| 件数 | 28,271 | 28,271 | 28,271 | 28,271 |
| 平均 | 3.27 | 6.71 | 4.99 | 3.44 |
| 中央値 | 2.10 | 3.80 | 3.05 | 1.40 |
| 最小 | 1.00 | 1.00 | 1.00 | 0.00 |
| 最大 | 87.3 | 793.1 | 402.9 | 780.4 |
| p25 | 1.30 | 2.00 | 1.65 | 0.50 |
| p75 | 3.70 | 7.50 | 5.70 | 3.40 |

→ 複勝らしい分布（mid 中央値 3.05、単勝中央値 7.9 の約 1/2.5）。range 平均 3.44、中央値 1.4 → 多数のレースで low と high の差は 1〜3 程度、極端に広がるのは longshot のみ。

### 取得失敗 22 レースの内訳

すべて `032025120901-...05` 等、**江戸川 (jcd=03) 2025-12-09 の連続レース**に集中。boatrace.jp の `oddstf` ページが空応答（おそらく中止 / 順延等で oddstf ページが消されている）。

→ 単勝 (empty=0) より多い理由は不明。**単勝 / 複勝でリクエストタイミングが異なる時に発生する可能性**（同じページから 2 回取得しているため、取得時刻のずれで一方だけ失敗するなどありうる）。Step 2 では K ファイル `finish_position` を見て「未確定 / 中止」を識別し、12 ヶ月集計から自動除外する設計が必要。

### Overround（複勝の構造的特殊性）— ⚠️ 重要観察

複勝のオッズは range 表記で、3 通り（low / mid / high）の implied probability を計算した:

| 計算法 | mean | median | p10 | p90 |
|---|---:|---:|---:|---:|
| `sum(1/odds_high)` (lower bound) | 2.14 | 2.20 | 1.79 | 2.36 |
| `sum(2/(low+high))` (mid) | 2.47 | 2.55 | 2.14 | 2.66 |
| `sum(1/odds_low)` (upper bound) | **3.09** | 3.11 | 2.93 | 3.22 |

⚠️ **複勝オッズは単勝と全く違う構造**:

- 複勝の理論的な「sum of P(top 3)」は **3.0**（3 艇が必ず top 3 に入るため確率の和は 3）
- 控除率 20% を考慮した理論 overround = `3 / (1 - 0.20) = 3.75`（単勝の `1.25` 相当）
- 試行結果は **3 通りすべて 3.75 を下回る**（最大の `sum(1/odds_low) = 3.09 < 3.75`）

これは複勝オッズの **range 構造**に起因する：
- `low` = 「他の 2 艇の top-3 がともに高人気艇」のときの最低保証払戻 → bet 主に有利な評価
- `high` = 「他の 2 艇の top-3 がともに低人気艇」のときの最高払戻 → bet 主に有利な評価
- pari-mutuel pool の分配ルールから、**実勢の払戻は 3 艇の組合せに依存**し、単一値で表せない

**Step 2 への含意**:

1. **単純な「sum implied で控除率推定」は不能**。複勝は単勝のように `1 / overround = (1 - takeout)` の単純関係が成り立たない
2. 控除率を厳密に推定するには **実払戻金（finishing 3 艇に応じた payout）** を K ファイル + 別ソース（`raceresult` の払戻金欄）から取得する必要がある
3. lift / `ev_all_buy` 計算時には **実 ROI ベース**（sum of payout / sum of stake）が必須。`mean(odds × hit)` は B-3 win で +20〜39pp の上方バイアス確認済み（Cov(odds, hit) < 0 のため）
4. range の中で **どのオッズを評価に使うか** が結論を左右する:
   - 保守的評価（low の使用）: bet 主に最も厳しい → 黒字化判定に保守的、推奨
   - 楽観的評価（high の使用）: bet 主に最も有利 → 上振れ余地確認のための補助

### 桐生 1R での win-place 不整合（2025-12-01）について

開発時の sanity check で boat 1 が「win 1.7（断然 1 番人気）なのに place 2.4-3.1（高い）」という mathematically inconsistent な値を観察。HTML パーサは正しくページ内容を読んでおり、boatrace.jp 側の表示が実際にこの値である。

仮説:
- 出場辞退（B欠）等で複勝オッズが調整されきっていない
- 単勝・複勝で表示更新タイミングがずれた

5 サンプルでの整合性検証では 1/5 (20%) が同様の不整合を示した。**Step 2 集計では実 ROI ベースで評価するため直接の影響はない**が、`raceresult` ページの payout も含めた精緻な検証が必要。

## 3. Step 1 終了条件チェック

[NEXT_SESSION_PROMPT_A.md](NEXT_SESSION_PROMPT_A.md)「拡張 A Step 1 の終了条件」に対する達成状況:

| 終了条件 | 状態 |
|---|---|
| `fetch_place_odds` が実装され、1 レース動作確認 OK | ✅ 桐生 12R / 住之江 1R で 6 艇分取得確認、整合性 OK |
| `load_or_download_month_place_odds` が実装される | ✅ |
| 試行 DL（2025-12）で `data/odds/place_odds_202512.parquet` が出る | ✅ 4,749 races / 28,271 entries |
| parquet の中身を `race_id × 6 通り × (low, high)` で確認 | ✅ schema 一致、件数妥当 |
| 1 レース sample で複勝 implied probability 計算と overround 観察 | ✅ overround_mid = 2.47、overround_high (1/low) = 3.09 |
| 結果を `MARKET_EFFICIENCY_PLACE_RESULTS.md` に記録 | ✅ 本ドキュメント |
| ユーザーへ 12 ヶ月本番 DL 実行可否を確認 | ⏳ **本ドキュメント提示後に確認** |

## 4. Step 1 判定

[NEXT_SESSION_PROMPT_A.md](NEXT_SESSION_PROMPT_A.md)「拡張 A Step 1 の判定」に対する判定:

- API 取得不能 / 認証エラー → **該当せず**（99.5% 取得成功）
- API スキーマが想定と違う → **該当せず**（schema 一致、range 表記も期待通り）
- 1 ヶ月試行 DL でデータ取れない → **該当せず**
- overround が想定外（控除率 30%+ 等） → **該当せず**（複勝は単純な overround 解釈不能、control 不要）

→ **Step 2（12 ヶ月本番 DL + 市場効率分析）に進める判定**。

## 5. 12 ヶ月本番 DL 結果（2026-04-27〜28）

### 実行サマリー

| 指標 | 値 |
|---|---:|
| 期間 | 2025-05 〜 2026-04（12 ヶ月） |
| 開始 → 完了 | 2026-04-27 12:27:44 → 2026-04-28 01:23:47 |
| 所要 | **12 時間 56 分**（事前見積もり 14 時間より少し早い） |
| 並列度 | 10 workers |
| 総 races | **54,277** |
| 総 rows | 321,952（avg 5.93 艇/レース） |
| エラー / empty / partial 残存 | **すべて 0**（クリーン完走） |
| 平均所要/月 | 約 1 時間 4 分 |
| 容量 | 12 parquet で約 1.5 MB（圧縮済み） |

### 月別取得結果

| 月 | races | rows | 6艇全揃い率 | 容量 (KB) |
|---|---:|---:|---:|---:|
| 2025-05 | 5,026 | 29,644 | 90.8% | 125.2 |
| 2025-06 | 4,766 | 28,232 | 92.9% | 118.3 |
| 2025-07 | 5,144 | 30,439 | 92.3% | 130.4 |
| 2025-08 | 5,048 | 29,911 | 93.1% | 127.5 |
| 2025-09 | 4,248 | 25,215 | 94.0% | 101.2 |
| 2025-10 | 4,128 | 24,496 | 93.8% | 102.5 |
| 2025-11 | 3,937 | 23,420 | 95.2% | 94.6 |
| 2025-12 | 4,749 | 28,271 | 95.6% | 119.3 |
| 2026-01 | 5,166 | 30,695 | 94.4% | 133.6 |
| 2026-02 | 4,171 | 24,788 | 94.6% | 106.1 |
| 2026-03 | 4,653 | 27,581 | 93.2% | 116.5 |
| 2026-04 | 3,241 | 19,260 | 94.6% | 78.0 |

### 単勝 12 ヶ月 DL との比較

| 指標 | 単勝 (B-3 win) | 複勝 (B-3 拡張 A) |
|---|---:|---:|
| races | 54,299 | 54,277 |
| 12 ヶ月 empty | 22（江戸川 12-09 集中） | **0** |
| 所要 | 12.9 時間 | 12.9 時間 |
| 6 艇全揃い率（試行 DL） | 94.2% | 95.6% |

複勝側は単勝より取得が安定（empty 0、6 艇全揃い率も +1.4pp 高い）。`oddstf` ページの 2 表（単勝表 / 複勝表）で取得タイミングのずれが単勝側にだけ稀に発生していた可能性。Step 2 集計用データとして全 12 ヶ月クリーンに揃った。

## 6. Step 2（12 ヶ月本番 DL 後）で取り組む課題

参考までに記載（本セッション対象外）:

1. **`run_market_efficiency.py` を `--bet-type place` 拡張**
   - `LINEAR_BINS_PLACE`（複勝向け、mean_implied 0.3〜0.7 想定 → 等幅 10 ビン or 等密度）
   - 複勝の hit 判定: `combination ∈ {boat_no(1着), boat_no(2着), boat_no(3着)}`
   - **複勝は 1 レースに 3 hit を許容する集計**が必要（単勝の sum-to-1 前提は使えない）
2. **odds 評価モード 3 通り併記** — `low` / `mid` / `high` の各前提で lift / `ev_all_buy` を計算
3. **実 ROI ベースの計算が必須** — B-3 win の教訓で `ev_all_buy = mean_odds × mean_hit` の上方バイアスを回避するため、sum-aggregated 実 ROI も必ず併記
4. **K ファイル `finish_position` から実払戻計算**
   - 過去日: `raceresult` ページの「複勝払戻金」を取得（`fetch_race_result_full` の payout 拡張が必要）
   - 払戻 / 100 でオッズ確定（複勝は 1 つの finishing 組合せに対し 3 艇分の payout がある）
5. **採用判定基準（B-3 win と同等）**:
   - `lift ≥ 1.25` かつ `ev_all_buy ≥ 1.0` かつ bootstrap CI 下限 ≥ 1.0 のセグメントを採用
   - 控除率 20% 理論を破るには `lift ≥ 1.25` だが、実勢でどの程度の歪みが許容されるかは Step 2 集計時に再評価

## 7. Step 2 進行 / 撤退判定（仮）

- **取得 OK + 採用基準達成セグメントあり**: Step 3（サブセグメント詳細分析）へ
- **取得 OK + 採用基準達成 0**: B-3 拡張 A 撤退、複勝も控除率を破れない結論
- **取得 NG / overround 異常**: B-3 拡張 A 撤退（Step 1 判定で取得 OK 確認済みなのでここには来ない見込み）

## 8. 関連ドキュメント

- [MARKET_EFFICIENCY_WIN_RESULTS.md](MARKET_EFFICIENCY_WIN_RESULTS.md) — B-3 win 全結果（実 ROI、ev_all_buy 上方バイアス、`oddstf` 構造等）
- [NEXT_PHASE_B3_PLAN.md](NEXT_PHASE_B3_PLAN.md) §1 — 券種別控除率表
- [NEXT_SESSION_PROMPT_A.md](NEXT_SESSION_PROMPT_A.md) — Step 2 着手用（top-3 誤認定版、参考）
- [NEXT_SESSION_PROMPT_A_R3.md](NEXT_SESSION_PROMPT_A_R3.md) — **R3 着手用（top-2 訂正後 + R2 補正係数反映、現行版）**
- [CLAUDE.md](CLAUDE.md) — 「現行の運用方針」「現在の仕様」

---

## 9. ⚠️ 重要訂正: 競艇の複勝は top-2（2026-04-28、Step 2 着手セッション中に発覚）

### 9.1 §1〜§7 の誤認定

§1〜§7 は **「複勝 = top-3 (1〜3 着)」** という競馬準拠の前提で書かれているが、これは誤り。
競艇の複勝は **top-2 (1〜2 着)** のみが払戻対象。3 着艇への払戻はなし。

### 9.2 公式根拠

> 「複勝は1着か2着に入る艇を当てるもので、選んだ艇が1着でも2着でも当たり。**的中率は1/3**」
> — [LEVEL.1 複勝（複勝式）| BOAT RACE オフィシャルウェブサイト](https://www.boatrace.jp/owpc/pc/extra/enjoy/guide/level1/l1_03_01_02.html)

### 9.3 raceresult ページでの実証（5 sample races）

| race | 結果 (1-2-3) | 複勝表示 | 評価 |
|---|---|---|---|
| 桐生 1R 12/01 | 3-1-4 | boat 3 ¥150, boat 1 ¥250 | 3 着艇 (boat 4) の payout 無し ✅ |
| 桐生 12R 12/01 | 1-3-? | boat 1 ¥120, boat 3 ¥290 | 2 艇のみ ✅ |
| 住之江 5R 12/01 | 1-3-? | boat 1 ¥100, boat 3 ¥150 | 2 艇のみ ✅ |
| 若松 3R 11/30 | 4-5-? | boat 4 ¥100, boat 5 ¥210 | 2 艇のみ ✅ |
| 平和島 8R 11/30 | (取得失敗) | — | parser 失敗または未開催 |

### 9.4 Step 1 観察「sum(1/odds_low) = 3.09」の再解釈

§2.7「Overround」で観察した `sum(1/odds_low) = 3.09` は overround の意味を持たない:

- 競艇の複勝は **top-2** なので理論 sum implied = 2.0 のはず
- 観察値 3.09 はそれより +1.09 過剰
- 理由: `odds_low / odds_high` は **条件付き payout の範囲**（pari-mutuel メカニズムでもう 1 艇の人気度に依存）であり、`(1-takeout)/odds_low` は真の hit 確率にならない
- → 単純な「sum implied」分析は **odds データだけでは不能**、実 payout が必須

### 9.5 影響範囲

1. `load_winning_top3_boats` → `load_winning_top2_boats` に修正（`finish_position ∈ {1, 2}`）
2. `attach_place_hit_label` を 1 レース 2 hits 仕様に修正
3. §6 で書いた「Step 2 で取り組む課題」のヒット判定式は誤り（§10 R1 で訂正）
4. §1〜§7 は履歴として残置、現行は §10 以降を参照

---

## 10. R1: top-2 修正後の smoke test（2025-12 単月、2026-04-28）

### 10.1 実装変更

| ファイル | 変更内容 |
|---|---|
| [ml/src/scripts/run_market_efficiency.py](ml/src/scripts/run_market_efficiency.py) | `--bet-type place` 拡張、`load_winning_top2_boats` / `attach_place_hit_label` (top-2)、`bin_summary_place` (3 odds モード併記)、`bootstrap_lift_ci_place` (low ベース)、`evaluate_place_distortion` |
| 同上（R1 訂正）| `top3_set` → `top2_set`、`finish_position ∈ {1, 2}`、1 race 2 hits 仕様 |

### 10.2 実行結果（2025-12, 4,537 races / 27,222 combos）

| bin (implied_low) | n | actual_p | implied_low | lift | ev_all_buy_low | ev_all_buy_mid | ev_all_buy_high | ev_actual_low | 90% boot CI (lift) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| [0.0, 0.1) | 1,868 | 0.053 | 0.069 | 0.77 | 0.716 | **1.082** | 1.448 | 0.686 | [0.65, 0.90] |
| [0.1, 0.2) | 4,339 | 0.106 | 0.151 | 0.71 | 0.586 | 0.914 | 1.242 | 0.566 | [0.66, 0.76] |
| [0.2, 0.3) | 4,611 | 0.196 | 0.248 | 0.79 | 0.639 | 0.992 | 1.344 | 0.630 | [0.75, 0.83] |
| [0.3, 0.4) | 3,469 | 0.279 | 0.345 | 0.81 | 0.650 | 1.004 | 1.359 | 0.645 | [0.78, 0.84] |
| [0.4, 0.5) | 2,960 | 0.335 | 0.435 | 0.77 | 0.617 | 0.928 | 1.239 | 0.614 | [0.74, 0.80] |
| [0.5, 0.6) | 2,793 | 0.408 | 0.535 | 0.76 | 0.611 | 0.881 | 1.151 | 0.610 | [0.73, 0.79] |
| [0.6, 0.7) | 2,220 | 0.506 | 0.642 | 0.79 | 0.631 | 0.846 | 1.060 | 0.630 | [0.76, 0.81] |
| [0.7, 0.8) | 1,263 | 0.591 | 0.727 | 0.81 | 0.650 | 0.809 | 0.968 | 0.650 | [0.79, 0.84] |
| [0.8, 0.9) | 3,699 | 0.715 | 0.800 | 0.89 | 0.715 | 0.785 | 0.855 | 0.715 | [0.88, 0.91] |

### 10.3 観察

1. **integrity check ✅**: actual_p × n 合計 = 9,073 ≈ 4,537 races × 2 hits → top-2 仕様と整合
2. **lift 全 bin で 1.0 未満** (0.71〜0.89): odds_low ベース implied は真の hit rate より一様に過大評価。これは pari-mutuel の「最低保証 payout」構造から予測される通り
3. **`ev_all_buy_low` 全 bin で 1.0 未満** (0.59〜0.72): 控除率破壊不能の強い示唆
4. **`ev_all_buy_mid` が 4 bin で 1.0 超** ([0.0, 0.4)): ただし「全 hit が odds_mid で払戻」の楽観仮定。実 payout 分布次第で無効化される可能性
5. **flagged 1 bin** ([0.0, 0.1) で secondary 採用)、ただし `ev_actual_low = 0.686` で実勢は -31%

→ R1 単独では撤退判定に至らず（`ev_all_buy_mid` のシナリオが残存）。R2 で実 payout 分布を確定させる必要。

### 10.4 出力ファイル

- [artifacts/market_efficiency_2025-12_2025-12_place.csv](artifacts/market_efficiency_2025-12_2025-12_place.csv)
- [artifacts/market_efficiency_2025-12_2025-12_place.png](artifacts/market_efficiency_2025-12_2025-12_place.png)

---

## 11. R2: 実 payout sample 取得と構造分析（50 races / 100 hit boats、2026-04-28）

### 11.1 実装

| ファイル | 変更内容 |
|---|---|
| [ml/src/collector/openapi_client.py](ml/src/collector/openapi_client.py) | `fetch_place_payouts(stadium_id, race_date, race_no) -> dict[str, int]` 追加。raceresult ページの「複勝」セクションから 2 艇分の payout を抽出 |
| [ml/src/scripts/sample_place_payouts.py](ml/src/scripts/sample_place_payouts.py) | 新規。`place_odds_202512.parquet` から N race ランダムサンプリング → `fetch_place_payouts` で実 payout 取得 → odds_low/mid/high と比較 |

### 11.2 実行結果（50 races, 100 hit boats）

| 指標 | 値 |
|---|---:|
| 取得成功率 | **50 / 50 races（100%）**、100 / 100 hit boats |
| **in_range（payout ∈ [odds_low, odds_high]）** | **100% ✅** |
| payout_x mean | 2.392 |
| odds_low mean | 2.126 |
| odds_mid mean | 2.753 |
| odds_high mean | 3.379 |
| **pos_in_range mean**（0=low, 1=high） | **0.245** |
| pos_in_range median | **0.000** |
| pos_in_range p25 / p75 | 0.000 / 0.500 |

### 11.3 implied_low bin 別分析

| bin | n | odds_low | odds_mid | odds_high | payout_x | pos_in_range |
|---|---:|---:|---:|---:|---:|---:|
| [0, 0.1) | 3 | 14.10 | 18.60 | 23.10 | 15.80 | 0.31 |
| [0.1, 0.3) | 13 | 3.90 | 5.14 | 6.38 | 4.49 | 0.27 |
| [0.3, 0.6) | 38 | 1.87 | 2.56 | 3.25 | 2.08 | 0.23 |
| [0.6, 1.0) | 46 | 1.05 | 1.20 | 1.35 | 1.18 | 0.25 |

### 11.4 主要な発見

1. **odds_low / odds_high の意味は確定** — 100% in_range で実 payout は range 内に収まる
2. **実 payout は odds_low に強く偏る** — pos_in_range mean = **0.245**、median = 0.0 で**半数以上のレースで payout = odds_low ピッタリ**
3. **bin 全帯で偏りは一様**（0.23〜0.31）— 人気艇 / 人気薄艇で偏りに大きな差はない
4. **R1 の `ev_all_buy_mid > 1.0` 観察は無効** — 実 payout は mid に達せず低位に偏る
5. **補正係数の確立**: 実 ev ≈ `(1 - 0.245) × ev_actual_low + 0.245 × ev_actual_high` ≈ `0.755 × ev_actual_low + 0.245 × ev_actual_high`

### 11.5 控除率破壊判定への含意

R1 の `ev_actual_low` 最大値 = 0.715 (bin [0.8, 0.9))。R2 補正で:

```
ev_actual_corrected ≈ 0.755 × ev_actual_low + 0.245 × ev_actual_high
```

bin [0.8, 0.9) で `ev_actual ≈ 0.755 × 0.715 + 0.245 × 0.855 = 0.749` → **控除率 20% (0.80) 未達**

全 bin で R1 の `ev_actual_low` を 25% 楽観補正で 0.80 を超えるのは困難。**B-3 拡張 A 撤退の方向に強く示唆**するが、12 ヶ月集計で確証取得すべき。

### 11.6 出力ファイル

- [artifacts/place_payouts_sample_2025-12.parquet](artifacts/place_payouts_sample_2025-12.parquet) — 50 races × 2 hit boats = 100 行（race_id, combination, payout_yen）

---

## 12. R3 (次セッション): 12 ヶ月集計 + 補正後 ev で控除率破壊判定

### 12.1 タスク内容

1. R2 補正係数 (pos_in_range = 0.245) を `bin_summary_place` に反映 → `ev_actual_corrected = 0.755 × ev_actual_low + 0.245 × ev_actual_high`
2. `bootstrap_lift_ci_place` に `ev_actual_corrected_boot_lo / boot_hi` を追加
3. `evaluate_place_distortion` を「`ev_actual_corrected > 1.0` & `ev_actual_corrected_boot_lo > 1.0`」に変更
4. 12 ヶ月集計（`run_market_efficiency.py --bet-type place --start 2025-05 --end 2026-04 --split-halves --bootstrap 2000 --group-by stadium --group-by-2axis stadium,odds_band --focus-bin-lower 0.10 --focus-bin-upper 0.50`）
5. segment 分析（stadium 単軸、stadium × odds_band 2 軸）
6. 採用判定 → Step 3（サブセグメント詳細）or B-3 拡張 A 撤退

### 12.2 期待される結果（仮説）

R1 + R2 から、12 ヶ月集計でも **採用基準達成 0 セグメント** が予測される。最善でも `ev_actual_corrected ≈ 0.75` 程度に留まり、控除率 20% を破れない見込み。

### 12.3 起点プロンプト

[NEXT_SESSION_PROMPT_A_R3.md](NEXT_SESSION_PROMPT_A_R3.md) を新セッションで使用。

---

## 13. R3 集計結果（2026-04-28）

### 13.1 実装変更

| ファイル | 変更内容 |
|---|---|
| [ml/src/scripts/run_market_efficiency.py](ml/src/scripts/run_market_efficiency.py) | `POS_IN_RANGE_R2 = 0.245` 定数追加、`bin_summary_place` に `ev_actual_corrected` 列追加、`bootstrap_lift_ci_place` に `ev_corrected_boot_lo/hi` を iter 内合成で追加、`evaluate_place_distortion` を補正後 ev 主基準のみに変更（R1 補助基準 mid 廃止）、segment 系 place 専用関数 (`segment_summary_within_focus_place` / `bootstrap_segment_lift_ci_place` / `evaluate_segment_distortion_place`) 追加、`run_subsegment_group(_2axis)` に `bet_type` 分岐、`print_segment_table` に place 表示モード追加 |

### 13.2 実行サマリー

```bash
py -3.12 ml/src/scripts/run_market_efficiency.py \
  --start 2025-05 --end 2026-04 --bet-type place \
  --split-halves --bootstrap 2000 \
  --group-by stadium --group-by-2axis stadium,odds_band \
  --focus-bin-lower 0.10 --focus-bin-upper 0.50
```

| 指標 | 値 |
|---|---:|
| 期間 | 2025-05〜2026-04（12 ヶ月） |
| 入力 | place_odds 304,944 行 / 50,824 races（6 艇全揃いのみ、3,453 races 除外） |
| 結合後 | 304,914 combo / **50,819 races**（2 hits/race 確認済 50,819）|
| 所要 | 約 **1 分 20 秒**（bootstrap 2000 × 4 系統含む）|
| 出力 | `artifacts/market_efficiency_2025-05_2026-04_place.{csv,png}` + segment 2 種 |

### 13.3 全期間ビン別集計（9 bins、補正後 ev = 0.755 × ev_low + 0.245 × ev_high）

| bin (implied_low) | n | actual_p | implied_low | lift | ev_low | ev_corr | ev_high | ev_corr 90% CI |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| [0.0, 0.1) | 20,201 | 0.0522 | 0.0686 | 0.761 | 0.631 | **0.789** | 1.276 | [0.741, 0.840] |
| [0.1, 0.2) | 47,828 | 0.1132 | 0.1506 | 0.751 | 0.600 | 0.750 | 1.211 | [0.732, 0.767] |
| [0.2, 0.3) | 52,907 | 0.1895 | 0.2490 | 0.761 | 0.608 | 0.768 | 1.260 | [0.755, 0.781] |
| [0.3, 0.4) | 39,037 | 0.2666 | 0.3453 | 0.772 | 0.618 | 0.779 | 1.276 | [0.768, 0.791] |
| [0.4, 0.5) | 33,758 | 0.3369 | 0.4353 | 0.774 | 0.619 | 0.774 | 1.251 | [0.763, 0.784] |
| [0.5, 0.6) | 31,303 | 0.4163 | 0.5348 | 0.778 | 0.623 | 0.756 | 1.166 | [0.747, 0.765] |
| [0.6, 0.7) | 24,707 | 0.5108 | 0.6423 | 0.795 | 0.636 | 0.735 | 1.041 | [0.727, 0.743] |
| [0.7, 0.8) | 14,026 | 0.5980 | 0.7273 | 0.822 | 0.658 | 0.734 | 0.970 | [0.723, 0.748] |
| [0.8, 0.9) | 41,147 | 0.7126 | 0.8000 | 0.891 | 0.713 | 0.742 | 0.833 | [0.738, 0.746] |

**観察**:

1. **採用基準達成 0 / 9 bins**（`ev_corr > 1.0 & ev_corrected_boot_lo > 1.0` で flag）
2. **全 bin で `ev_corr < 1.0`**、最善は bin [0.0, 0.1) の `ev_corr=0.789`、CI 上限 0.840 < 1.0
3. **lift 全 bin で 1.0 未満**（0.751〜0.891）、odds_low ベース implied は systematic に過大評価
4. R1 単月（2025-12）で flag されていた bin [0.0, 0.1) の `ev_all_buy_mid = 1.082` は R2 補正で `ev_corr = 0.789` まで圧縮 → R1 の secondary 基準が楽観的すぎたことを実証

### 13.4 前後半同方向チェック（split-halves）

- 前半 (2025-05〜2025-10) vs 後半 (2025-11〜2026-04) の lift 比較
- **9 / 9 bins で同方向**（全 bin で lift < 1.0、両期間とも一致）
- 期間横断で安定した overestimation 構造 → 単発の偶然ではない

### 13.5 stadium 単軸（24 場、focus 0.10-0.50 内、173,530 combos / 50,716 races）

| 順位 | stadium | n | lift | ev_low | ev_high | ev_corr | ev_corr CI |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | 5.Tamagawa | 6,780 | 0.81 | 0.66 | 1.38 | **0.84** | [0.79, 0.89] |
| 2 | 4.Heiwajima | 6,764 | 0.82 | 0.66 | 1.22 | 0.80 | [0.77, 0.82] |
| 3 | 1.Kiryu | 8,027 | 0.81 | 0.65 | 1.14 | 0.77 | [0.74, 0.79] |
| 4 | 2.Toda | 7,870 | 0.81 | 0.65 | 1.18 | 0.78 | [0.75, 0.81] |
| 5 | 17.Miyajima | 7,273 | 0.78 | 0.63 | 1.37 | 0.81 | [0.77, 0.85] |
| ... | ... | ... | ... | ... | ... | ... | ... |
| - | 16.Kojima | 7,267 | 0.76 | 0.60 | 1.67 | 0.87 | [0.82, 0.91] |
| - | 7.Gamagori | 7,751 | 0.71 | 0.55 | 1.84 | 0.86 | [0.83, 0.90] |

(全 24 場の詳細: `artifacts/market_efficiency_segment_stadium_focus_0.10-0.50_2025-05_2026-04_place.csv`)

**観察**:

1. **採用基準達成 0 / 24 場**（最善 5.Tamagawa で `ev_corr CI 上限 = 0.89 < 1.0`）
2. ev_low 最高 = 0.66（玉川 / 平和島）、ev_corr 最高 = 0.87（児島、ただし `ev_high=1.67` の楽観評価依存）
3. **odds_high の幅が広い場（児島 1.67 / 蒲郡 1.84）でも補正後は 0.87 / 0.86 に圧縮** → range の `high` 端が頻発する仮定（pos_in_range = 0.245）が黒字化に届かない構造を再確認
4. 最弱 24.Omura（大村）で `ev_corr=0.68` → 場別差は最大 0.20pp、全場が控除率 20% を破れていない

### 13.6 stadium × odds_band 2 軸（48 cells、focus 0.10-0.50 内）

| 順位 | cell | n | lift | ev_low | ev_high | ev_corr | ev_corr CI |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | 5.Tamagawa \| [5,10) | 1,215 | 0.90 | 0.72 | 1.55 | **0.93** | [0.80, **1.07**] |
| 2 | 4.Heiwajima \| [5,10) | 1,051 | 0.89 | 0.70 | 1.47 | 0.89 | [0.75, **1.04**] |
| 3 | 8.Tokoname \| [5,10) | 1,279 | 0.88 | 0.69 | 1.25 | 0.83 | [0.72, 0.93] |
| 4 | 3.Edogawa \| [5,10) | 1,043 | 0.83 | 0.68 | 1.22 | 0.81 | [0.69, 0.93] |
| 5 | 2.Toda \| [5,10) | 1,150 | 0.83 | 0.67 | 1.29 | 0.82 | [0.70, 0.94] |
| ... | ... | ... | ... | ... | ... | ... | ... |

(全 48 cells: `artifacts/market_efficiency_segment_stadiumXodds_band_focus_0.10-0.50_2025-05_2026-04_place.csv`)

**観察**:

1. **採用基準達成 0 / 48 cells**
2. 上位 2 cell (5.Tamagawa | [5,10), 4.Heiwajima | [5,10)) は `ev_corr CI 上限が初めて 1.0 を超える` (1.07 / 1.04) が、`点推定 < 1.0` かつ `CI 下限 < 1.0` で確信度なし
3. ev_corr CI 下限が 1.0 を超える cell は **1 つもない**
4. 最大 ev_corr 点推定でも 0.93（5.Tamagawa | [5,10)）、控除率 20% (= 0.80) を **わずかに上回る**程度で、`ev_high` 楽観仮定の救済範囲を超えていない

### 13.7 出力ファイル

- [artifacts/market_efficiency_2025-05_2026-04_place.csv](artifacts/market_efficiency_2025-05_2026-04_place.csv) — 全期間 9 bins
- [artifacts/market_efficiency_2025-05_2026-04_place.png](artifacts/market_efficiency_2025-05_2026-04_place.png) — キャリブレーションプロット
- [artifacts/market_efficiency_2025-05_2025-10_place.csv](artifacts/market_efficiency_2025-05_2025-10_place.csv) — 前半 (split-halves)
- [artifacts/market_efficiency_2025-11_2026-04_place.csv](artifacts/market_efficiency_2025-11_2026-04_place.csv) — 後半 (split-halves)
- [artifacts/market_efficiency_segment_stadium_focus_0.10-0.50_2025-05_2026-04_place.csv](artifacts/market_efficiency_segment_stadium_focus_0.10-0.50_2025-05_2026-04_place.csv) — stadium 単軸
- [artifacts/market_efficiency_segment_stadiumXodds_band_focus_0.10-0.50_2025-05_2026-04_place.csv](artifacts/market_efficiency_segment_stadiumXodds_band_focus_0.10-0.50_2025-05_2026-04_place.csv) — stadium × odds_band 2 軸
- [artifacts/market_efficiency_2025-05_2026-04_place_run.log](artifacts/market_efficiency_2025-05_2026-04_place_run.log) — 実行ログ

---

## 14. R3 採用判定 → B-3 拡張 A 撤退確定

### 14.1 採用判定基準（合意済 R3 基準、§12.1 §13 で実行）

主基準:
- `n ≥ 1,000`
- `ev_actual_corrected > 1.0`（点推定で控除率 20% を破る）
- `ev_corrected_boot_lo > 1.0`（90% CI 下限が 1.0 を超え、確信あり）
- 前後半同方向（split-halves で同方向の lift / ev 動向）

R1 の補助基準（`ev_all_buy_mid > 1.05`）は R2 で「実 payout は odds_low に偏り mid は楽観すぎ」と判明したため廃止。

### 14.2 判定結果

| 集計対象 | 採用基準達成 | 最善 | 最善の CI 上限 | 結論 |
|---|---:|---|---:|---|
| 全期間 9 bins | **0 / 9** | bin [0.0, 0.1) ev_corr=0.789 | 0.840 | × |
| stadium 単軸 24 場 | **0 / 24** | 5.Tamagawa ev_corr=0.84 | 0.89 | × |
| stadium × odds_band 2 軸 48 cells | **0 / 48** | 5.Tamagawa\|[5,10) ev_corr=0.93 | 1.07 | △（上限超えだが点推定 < 1.0） |
| 前後半同方向チェック | **9 / 9 bins YES** | — | — | 全期間で安定した overestimation 構造 |

**全 81 セグメントで `ev_actual_corrected` 採用基準達成 0 件**。

### 14.3 構造的結論

1. **競艇複勝市場には『odds_low 帯の系統的な過大評価』があるが、控除率 20% を破る規模ではない**
   - 全 bin で `lift < 1.0`、ev_low 最大 0.713（bin [0.8, 0.9)）、ev_corr 最大 0.789（bin [0.0, 0.1)）
   - これは odds_low が「最低保証 payout」として保守的に提示されている pari-mutuel メカニズムの帰結
2. **ev_high の楽観評価で 1.0 超えるビン / セグメントはあるが、実 payout の偏り（pos_in_range mean = 0.245）で補正すると 0.93 が天井**
3. **B-1 trifecta（最善 ev=0.98）と B-3 win（最善 ev=0.964）と同じ「控除率を縮める効果はあるが収支プラス化までは至らない」構造**を複勝でも確認
4. 控除率 20% の券種だからといって複勝市場が単勝市場より歪みやすいという仮説は否定された

### 14.4 撤退判定

- **R3 不合格** = `ev_actual_corrected > 1.0` セグメント = 0 件
- **B-3 拡張 A 撤退確定**（2026-04-28）
- 12 ヶ月本番実 payout DL（13 時間）は **不実施**（採用基準達成セグメントが 0 のため。R2 sample による補正で十分な判定根拠あり）

### 14.5 次候補

- **C: 連系券種（2 連単 / 2 連複 / 拡連複）DL 実装**: [NEXT_SESSION_PROMPT_C.md](NEXT_SESSION_PROMPT_C.md) / [NEXT_SESSION_PROMPT_C_R1.md](NEXT_SESSION_PROMPT_C_R1.md)
- **完全凍結**: 全フェーズ撤退状態継続、`run_market_efficiency.py` の改善ループは停止

### 14.6 厳守事項（撤退後継続）

- ❌ R3 結果（採用基準 0 セグメント）を疑わずに次候補へ移行する前提
- ❌ 既存 trifecta / win / place の集計コード破壊禁止（`--bet-type {trifecta,win,place}` の互換維持）
- ❌ 後付けで補正係数を緩める / 採用基準を緩める変更禁止（フェーズ 3〜6 の教訓）
- ❌ 実運用は引き続き停止（`BET_RULE_REVIEW_202509_202512.md` §30-32 の通算 ROI ≥ +10% & 最悪月 > -50% 達成まで）
