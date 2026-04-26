---
description: Claude (LLM) の予想 JSON を実績と突合して ROI を算出する (P3)
argument-hint: <YYYY-MM-DD> [会場]
---

# /eval-predictions — 予想結果の評価

引数: `$ARGUMENTS`

例:
- `/eval-predictions 2025-12-01 桐生` — 1 会場 12R の集計
- `/eval-predictions 2025-12-01`        — その日の prep 済み全場集計

**用途**: P2 で出力した予想 JSON (`artifacts/predictions/<日付>/<場ID>_<R>.json`)
を、実際のレース結果 (K ファイル + 過去 3 連単オッズ parquet キャッシュ、当日は
boatrace.jp raceresult ページ) と突合して ROI を算出する。

**前提**: `/predict <日付>` で予想 JSON が出力済みであること。

**過去日**: K ファイル `data/history/k*.lzh` + 過去 3 連単オッズ
`data/odds/odds_YYYYMM.parquet` から実績を引く。K ファイルが無ければ自動 DL を試行。

**当日**: boatrace.jp `raceresult` ページから着順 + 払戻金を取得
(`fetch_race_result_full`)。締切直後で結果未確定なら `status: "no_result"`。

---

## 実行手順 (Claude が順守する)

### Step 1: 引数パース

`$ARGUMENTS` を空白で分割:
- `<日付>` (必須、YYYY-MM-DD)
- `<会場>` (任意、漢字 / ひらがな / 数字 / ゼロ埋め ID)

### Step 2: CLI を 1 回呼ぶ

```bash
py -3.12 ml/src/scripts/evaluate_predictions.py <引数そのまま>
```

これで:
- `artifacts/eval/<日付>.json` (場フィルタなし) または
  `artifacts/eval/<日付>_<場ID>.json` (場フィルタあり) が出力される
- ターミナルに集計サマリー (場別・confidence 帯別・全体・的中レース一覧) が表示される

### Step 3: 出力 JSON を Read して中身を把握

`artifacts/eval/<日付>.json` の構造:

```json
{
  "date": "2025-12-01",
  "stadium_filter": 1,
  "stadium_filter_name": "桐生",
  "evaluated_at": "2026-04-27T...+09:00",
  "is_past": true,
  "summary": {
    "n_races": 12,
    "n_settled": 12,
    "n_skipped_by_claude": 0,
    "n_no_result": 0,
    "n_bet_races": 12,
    "n_hit_races": 1,
    "n_bets": 16,
    "n_hits": 1,
    "total_stake": 1600,
    "total_payout": 1100,
    "roi": -0.3125,
    "hit_rate_per_bet": 0.0625,
    "hit_rate_per_race": 0.0833,
    "skip_rate": 0.0,
    "avg_confidence": 0.45,
    "by_stadium": [...],
    "by_confidence_band": [...]
  },
  "races": [
    {
      "race_id": "2025-12-01_01_01",
      "stadium_id": 1,
      "race_no": 1,
      "status": "settled",
      "verdict": "bet",
      "actual_combination": "1-4-3",
      "bets": [
        {
          "trifecta": "1-4-3",
          "stake": 100,
          "current_odds": 11.0,
          "actual_odds": 11.2,
          "is_hit": true,
          "payout": 1120,
          "payout_source": "actual",
          "odds_drift_pct": -0.018,
          "confidence": 0.4
        }
      ],
      "total_stake": 100,
      "total_payout": 1120
    }
  ]
}
```

### Step 4: ユーザーへの報告

ターミナル出力をそのまま貼るだけでなく、以下を加えて報告:

- **全体 ROI / 的中率 / 見送り率** (1〜2 行で要約)
- **場別の最良 / 最悪 ROI** (場フィルタなしの場合)
- **的中レースの組合せ + payout** (1〜3 件抜粋、特に高 confidence のもの)
- **confidence 帯別の傾向**: 高 conf ほど ROI 高い / 倒置 / 区別なし のいずれか
- **odds_drift**: Claude の current_odds と実 actual_odds の乖離が大きいベットがあれば指摘
  (記録された `odds_drift_pct` の絶対値 0.1 超は要注意)
- **no_result があれば原因**: 休場 / 欠番 / DL 失敗

---

## ステータス分類

| status | 意味 | ROI 計算 | 見送り率に算入 |
|---|---|---|---|
| `settled` | 実績取得 + verdict=bet → ヒット判定 | 含む | 含まない |
| `skipped_by_claude` | Claude が verdict=skip | 含まない | 含む |
| `no_result` | K/parquet/raceresult 取得不能 | 含まない | 含まない |

連続 5 レースで `no_result` なら CLI 側で警告 (実装に問題ある可能性)。

---

## 集計指標

- **必須**: 的中率 (per bet, per race), ROI, 見送り率, 平均 confidence
- **任意**: confidence 帯別 ROI (`[0.0-0.3, 0.3-0.5, 0.5-0.7, 0.7-1.0]`),
  場別 ROI

`/eval-predictions` は **チューニング用ではない**。後付けフィルタ追加には使わない
(フェーズ 3〜6 の教訓: 後付けフィルタは out-of-sample で必ず崩れる)。

---

## payout 計算ルール

- **過去日**: parquet の `actual_combo` オッズ × stake が原則
  (parquet に該当組合せが無ければ Claude が JSON に書いた `current_odds` にフォールバック)
- **当日**: `trifecta_payout / 100` × stake
  (raceresult ページが拾えなければ `current_odds` フォールバック)
- **odds drift**: Claude の `current_odds` と parquet/raceresult の actual_odds が
  乖離している場合 `odds_drift_pct = (current - actual) / actual` を JSON に記録
  (集計には影響しない)

各 bet の `payout_source` で `"actual"` / `"fallback_current_odds"` / `"miss"` を区別。

---

## 注意事項

- **既存モデル / collector のコードは触らない** (呼び出すだけ)
- **累積 (期間集計)** は P3.5 `/eval-summary` で別途実装する
- **実運用購入には使わない**。あくまで Claude の予想精度検証フェーズ
- **ROI が悪い結果でも後付けフィルタを足してチューニングしない**

---

## 実装の場所

- CLI: `ml/src/scripts/evaluate_predictions.py`
- 流用:
  - `predict_llm/prediction_schema.py` (validate)
  - `predict_llm/stadium_resolver.py` (場名⇔ID)
  - `collector/history_downloader.py` (K ファイル parse)
  - `collector/odds_downloader.py` (parquet キャッシュパス)
  - `collector/openapi_client.py` (`fetch_race_result_full`)
- 出力先:
  - `artifacts/eval/<日付>.json`
  - `artifacts/eval/<日付>_<場ID:02d>.json` (場フィルタあり)

詳細: `LLM_PREDICT_DESIGN.md` §3.3 / P3 完了メモ
