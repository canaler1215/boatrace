# MARKET_EFFICIENCY_WIN_RESULTS — フェーズ B-3 単勝市場効率分析の結果

最終更新: 2026-04-26
ステータス: **Step 1 完了、Step 2（12 ヶ月本番 DL）待機中（ユーザー確認待ち）**
位置付け: フェーズ B-1（3 連単市場効率分析）完全撤退後の方針転換 = 控除率 20% の単勝で同分析

参照: [NEXT_PHASE_B3_PLAN.md](NEXT_PHASE_B3_PLAN.md), [NEXT_PHASE_B1_PLAN.md](NEXT_PHASE_B1_PLAN.md) §9, [MARKET_EFFICIENCY_RESULTS.md](MARKET_EFFICIENCY_RESULTS.md), [MARKET_EFFICIENCY_SEGMENT_RESULTS.md](MARKET_EFFICIENCY_SEGMENT_RESULTS.md)

## 1. Step 1 概要 — 単勝オッズ DL の API 動作確認

### 目的

12 ヶ月本番 DL（推定 12〜24 時間）に入る前に、boatrace.jp で単勝オッズが取得可能か、データ形式は分析に使えるかを 1 ヶ月試行 DL で確認する。

### 実装

| ファイル | 変更内容 |
|---|---|
| `ml/src/collector/openapi_client.py` | `fetch_win_odds(stadium_id, race_date, race_no) -> dict[str, float]` 追加 |
| `ml/src/collector/odds_downloader.py` | `_win_cache_path`, `download_win_odds_for_races`, `load_or_download_month_win_odds` 追加 |

### DL ソース

- **エンドポイント**: `https://boatrace.jp/owpc/pc/race/oddstf?hd=YYYYMMDD&jcd=XX&rno=N`
  （boatrace.jp の単勝・複勝合算ページ）
- **方式**: 既存 trifecta (`odds3t`) / trio (`odds3f`) と同様の HTML スクレイピング
- **判別**: ページ内 2 表（単勝表 / 複勝表）のうち、オッズ列が範囲表記（`"X.X-Y.Y"`）でない方を単勝として採用 → 表順序が変わってもロバスト
- **キャッシュ形式**: `data/odds/win_odds_YYYYMM.parquet`（カラム: `race_id`, `combination` ∈ {"1"〜"6"}, `odds`）
  既存 `_df_to_map` ヘルパーで再利用可能

## 2. 試行 DL 結果（2025-12）

### 取得サマリー

| 指標 | 値 | 評価 |
|---|---:|---|
| 対象レース数（K ファイル） | 4,771 | — |
| 取得成功レース数 | **4,771（100%）** | ✅ |
| 取得失敗（empty）レース数 | 0 | ✅ |
| Parquet 行数 | 28,332 | — |
| 全艇取得率 | 28,332 / (4,771 × 6) = **98.97%** | ✅ |
| 所要時間 | 4,469.7 秒（74.5 分） | 12 ヶ月で約 **15 時間**見込み |

### レース内取得艇数の分布

| 艇数 | レース数 | 割合 |
|---:|---:|---:|
| 6 | 4,495 | 94.2% |
| 5 | 259 | 5.4% |
| 4 | 16 | 0.3% |
| 3 | 1 | 0.02% |

→ 6 艇全揃い 94.2%、欠場（B欠）等で艇数が減るレース 5.8%。**通常範囲**。

### 艇番別取得数

| 艇番 | 取得数 |
|---:|---:|
| 1 | 4,762 |
| 2 | 4,756 |
| 3 | 4,760 |
| 4 | 4,758 |
| 5 | 4,722 |
| 6 | 4,574 |

→ 艇番 6 がやや少ない（欠場が他艇よりやや多い）が想定範囲。

### オッズ統計

| 指標 | 値 |
|---:|---:|
| 件数 | 28,332 |
| 平均 | 14.64 |
| 中央値 | 7.9 |
| 最小 | 1.0 |
| 最大 | 943.5 |
| 25% 分位 | 3.4 |
| 75% 分位 | 16.5 |

→ 単勝らしい分布（中央値 7.9）。1.0〜10.0 帯と低本命層が混在し、サンプル分散が安定する想定通り。

### Overround（控除率推定）— ⚠️ 注意事項

100 レース sample で各レースの単勝 implied probability 合計を算出:

| 指標 | 値 |
|---:|---:|
| 平均 overround | **1.3556** |
| 中央値 | 1.3546 |
| p10 / p90 | 1.3412 / 1.3796 |
| 実勢控除率（個別レース） | **26.2%** |

⚠️ 単勝の理論控除率（払戻原資率 80%、控除 20%）に対し、**レース個別の overround は実勢 26%** で +6pp 高い。理由として:

- 単勝オッズの最小単位が 1.0 で切り上げ（implied prob 0.95 でもオッズ 1.05 → overround が膨らむ方向）
- 締切前の予測残量バッファ（売上分布の不均衡を運営側がオッズ調整で吸収）
- 個別レースの overround は「組合せごとの売上シェア × オッズ」の重み付けで決まり、長期 `ev_all_buy` の理論値（≒ 0.80）とは別概念

**Step 2 への含意**: `ev_all_buy = mean(odds_t × hit_t)` を bin 単位で集計するとき、ベースラインは `~0.80` ではなく **実勢 `~0.74`（= 1 / 1.3556）** に近い可能性。bin ごとの `ev_all_buy` が 1.0 を超えるかどうか（控除率破壊閾値）を判定する際は、長期平均の実勢 overround で再校正する必要がある。

## 3. Step 1 終了条件チェック

[NEXT_PHASE_B3_PLAN.md](NEXT_PHASE_B3_PLAN.md) §2 Step 1 終了条件に対する達成状況:

| 終了条件 | 状態 |
|---|---|
| `fetch_win_odds` が実装され、1 レース分の動作確認 OK | ✅ 桐生 2025-12-01 1R で `{1: 1.7, 2: 14.0, 3: 4.2, 4: 3.1, 5: 16.8, 6: 16.8}` 取得確認 |
| `load_or_download_month_win_odds` が実装され、1 ヶ月試行 DL で `data/odds/win_odds_202512.parquet` が出る | ✅ 4,771 races / 28,332 entries |
| parquet の中身を `race_id × 6 通り × odds` で確認 | ✅ schema 一致、件数妥当 |
| ユーザーへ 12 ヶ月本番 DL 実行可否を確認 | ⏳ **本ドキュメント提示後に確認** |

## 4. Step 1 判定

[NEXT_PHASE_B3_PLAN.md](NEXT_PHASE_B3_PLAN.md) §8 撤退基準に対する判定:

- API 取得不能 / 認証エラー → **該当せず**（100% 取得成功）
- API スキーマが想定と違う → **該当せず**（schema 一致）
- 1 ヶ月試行 DL でデータ取れない → **該当せず**

→ **Step 2（12 ヶ月本番 DL + 市場効率分析）に進める判定**。

## 5. Step 2 着手前のユーザー確認事項

12 ヶ月本番 DL（2025-05〜2026-04）について:

- **対象期間**: 2025-05, 2025-06, ..., 2026-04（12 ヶ月、2025-12 は試行で取得済み → 残り 11 ヶ月）
- **見込み時間**: 1 ヶ月 ≈ 75 分 → 11 ヶ月 ≈ **14 時間**（バックグラウンド推奨）
- **ディスク使用量**: 1 ヶ月 ≈ 0.5 MB（parquet 圧縮）→ 11 ヶ月 ≈ 5.5 MB
- **保存先**: `data/odds/win_odds_YYYYMM.parquet`（既存 trifecta `odds_*.parquet` / trio `trio_odds_*.parquet` と分離）

ユーザーが本番 DL 実行を承認した場合、Step 2 で:

1. 残り 11 ヶ月をバックグラウンド DL（並列 10 ワーカー、partial キャッシュ復帰機能あり）
2. DL 完了後、`run_market_efficiency.py` に `--bet-type win` 拡張を実装
3. 暗黙確率ビニング（実勢 overround ≒ 1.36 で正規化、または `(1-θ)/odds` 両方 CSV 列に出す）
4. 12 ヶ月集計で lift / `ev_all_buy` / bootstrap CI を計算

## 6. 次フェーズ判定の予告（Step 2 の合格条件）

[NEXT_PHASE_B3_PLAN.md](NEXT_PHASE_B3_PLAN.md) §3 より:

- ある暗黙確率帯（n ≥ 1,000）で `lift ≥ 1.10` または `≤ 0.85`
- 90% bootstrap CI で lift = 1.0 を含まない
- 前半 6 ヶ月 / 後半 6 ヶ月で同方向

**全帯で lift が 0.95〜1.05 → B-3 撤退**（NEXT_PHASE_B3_PLAN §8）。

## 7. 厳守事項（Step 2 以降に向けて）

- ❌ 既存モデル（trainer / predictor / engine）は触らない
- ❌ Step 4 のバックテスト前に Step 2-3 の歪み確認を完了する
  （フェーズ 6 + B-1 の教訓: 「精度改善 → ROI 改善」「歪み発見 → ROI プラス」の素朴な期待は何度も裏切られた）
- ❌ Step 2 の 12 ヶ月 DL 着手はユーザー承認後
- ❌ 既存 `data/odds/odds_*.parquet`（trifecta） / `data/odds/trio_odds_*.parquet`（trio）を上書きしない（**`win_odds_*.parquet` 別ファイル**で管理）
