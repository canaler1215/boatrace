# MARKET_EFFICIENCY_PLACE_RESULTS — フェーズ B-3 拡張 A: 複勝市場効率分析の結果

最終更新: 2026-04-27
ステータス: **拡張 A Step 1 完了 → Step 2（12 ヶ月本番 DL + 集計）の判定待ち**
位置付け: B-3 単勝（win）撤退確定後の保険分析 = 同じ控除率 20% の複勝で歪み構造を再評価する

参照: [NEXT_PHASE_B3_PLAN.md](NEXT_PHASE_B3_PLAN.md), [MARKET_EFFICIENCY_WIN_RESULTS.md](MARKET_EFFICIENCY_WIN_RESULTS.md)（B-3 win 撤退結果）

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

## 5. 12 ヶ月本番 DL 提案

### 期間

2025-05〜2026-04（単勝 12 ヶ月 DL と同じ期間、race_id 突合可能）

### コスト見積もり

| 月 | races（推定） | 所要時間 |
|---|---:|---:|
| 月平均 | ~4,500 | ~75 分 |
| 12 ヶ月合計 | ~54,000 | **~15 時間**（並列 10、単勝 12.9h と同等） |

### 実行方法

```bash
# バックグラウンド実行（単勝と同じ pattern）
PYTHONIOENCODING=utf-8 nohup py -3.12 -c "
import logging, sys
sys.path.insert(0, 'ml/src')
logging.basicConfig(level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s')

from collector.odds_downloader import load_or_download_month_place_odds
from scripts.run_backtest import load_month_data

for ym in [(2025,5),(2025,6),(2025,7),(2025,8),(2025,9),(2025,10),(2025,11),
           (2026,1),(2026,2),(2026,3),(2026,4)]:
    y, m = ym
    race_df = load_month_data(y, m)
    load_or_download_month_place_odds(y, m, race_df)
" > artifacts/odds_dl_logs/place_full_dl.log 2>&1 &
```

注: `2025-12` は本ドキュメント Step 1 で取得済みのためスキップ可。

### 容量見積もり

- 1 ヶ月 ~28,000 行 × 4 カラム ≒ 700 KB（実測 766 KB）
- 12 ヶ月 ≒ 8 MB

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
- [NEXT_SESSION_PROMPT_A.md](NEXT_SESSION_PROMPT_A.md) — 本セッションのプロンプト
- [CLAUDE.md](CLAUDE.md) — 「現行の運用方針」「現在の仕様」
