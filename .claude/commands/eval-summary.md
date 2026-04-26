---
description: P3 で出力した日次評価 JSON を期間横断で集約し、月次トレンド・場別累積・confidence 帯別 ROI と判定ステータスを算出する (P3.5)
argument-hint: --from <YYYY-MM-DD> --to <YYYY-MM-DD> | --month <YYYY-MM>
---

# /eval-summary — 累積評価サマリー

引数: `$ARGUMENTS`

例:
- `/eval-summary --from 2025-12-01 --to 2025-12-01` — 単日（退化テスト用）
- `/eval-summary --month 2025-12`                    — その月の累積（糖衣構文）
- `/eval-summary --from 2025-09-01 --to 2025-12-31`  — 4 ヶ月通算

**用途**: P3 `/eval-predictions` で出力した `artifacts/eval/<YYYY-MM-DD>.json`（場フィルタなし版）
を期間内で集約し、**月次 ROI トレンド・場別累積 ROI・confidence 帯別 ROI・bootstrap CI 下限・
判定ステータス**を算出する。

**前提**: 期間内で `/predict` → `/eval-predictions` を実施済みで `artifacts/eval/<日付>.json`
が複数存在すること。

---

## 実行手順 (Claude が順守する)

### Step 1: 引数パース

`$ARGUMENTS` の形式:
- `--from <YYYY-MM-DD> --to <YYYY-MM-DD>` （明示指定）
- `--month <YYYY-MM>` （その月の月初〜月末を自動展開）

`--month` と `--from`/`--to` は同時指定不可（CLI 側でエラー）。

### Step 2: CLI を 1 回呼ぶ

```bash
py -3.12 ml/src/scripts/eval_summary.py <引数そのまま>
```

これで:
- `artifacts/eval/summary_<from>_<to>.json` が出力される
- ターミナルに月次テーブル + 場別テーブル + confidence 帯別テーブル + 日次/月次 ROI 統計 +
  判定ステータス + warning が表示される

### Step 3: 出力 JSON を Read して中身を把握

`artifacts/eval/summary_<from>_<to>.json` の構造:

```json
{
  "from": "2025-12-01",
  "to": "2025-12-31",
  "evaluated_at": "2026-04-27T...+09:00",
  "n_days": 31,
  "n_days_with_data": 5,
  "n_days_missing": 26,
  "missing_dates": ["2025-12-02", ...],
  "input_files": ["2025-12-01.json", "2025-12-05.json", ...],
  "summary": {
    "n_races": ..., "n_settled": ..., "n_skipped_by_claude": ..., "n_no_result": ...,
    "n_bet_races": ..., "n_hit_races": ..., "n_bets": ..., "n_hits": ...,
    "total_stake": ..., "total_payout": ...,
    "roi": ..., "hit_rate_per_bet": ..., "hit_rate_per_race": ...,
    "skip_rate": ..., "avg_confidence": ...,
    "bootstrap_ci": {"n": 1000, "lower": ..., "upper": ...}
  },
  "by_month": [{"month": "2025-12", "n_days": 5, "roi": ..., ...}],
  "by_stadium": [{"stadium_id": 1, "name": "桐生", "roi": ..., ...}],
  "by_stadium_month": [{"stadium_id": 1, "month": "2025-12", "roi": ..., ...}],
  "by_confidence_band": [{"band": "0.0-0.3", "roi": ..., ...}, ...],
  "daily_roi_stats": {"min": ..., "median": ..., "mean": ..., "max": ..., "stddev": ...,
                      "worst_day": "2025-12-15", "best_day": "2025-12-08", "n": 5},
  "monthly_roi_stats": {... "worst_month": "2025-12", "best_month": "2025-12"},
  "verdict": {
    "status": "fail" | "breakeven" | "production_ready",
    "label": "✗ 未達" | "△ トントン以上" | "✓ 実運用再開条件達成",
    "roi": ..., "worst_month_roi": ..., "bootstrap_ci_lower": ...,
    "criteria": {...},
    "note": "判定は参考値。後付けフィルタで合わせ込んではならない"
  },
  "warnings": [...]
}
```

### Step 4: ユーザーへの報告

ターミナル出力をそのまま貼るだけでなく、以下を加えて報告:

- **判定ステータス + 全体 ROI + bootstrap CI 下限**（1〜2 行で結論）
- **月次 ROI トレンド**: worst_month / best_month の差・破局月（ROI < -50%）の有無
- **場別累積 ROI**: 最良・最悪ストラクチャ（場依存性が極端に出ているか）
- **confidence 帯別**: 高 confidence 帯のほうが ROI が高ければ Claude の自信スコアが
  機能している証拠、逆相関や無相関なら confidence は機能していない
- **データ不足の警告**: `n_days_with_data` / `missing_dates` の件数、
  `n_bet_races < 30` の場合のサンプル不足
- **次アクション提案**:
  - `production_ready` → P4 実走運用テストへ進める
  - `breakeven` → サンプル拡張 + プロンプト改善で `production_ready` を狙うか、撤退検討
  - `fail` → プロンプト改善 / サンプル拡張 / 撤退判断のトリアージ

---

## 入力ファイル選別ルール

- **対象**: `artifacts/eval/<YYYY-MM-DD>.json`（場フィルタなし版）のみ
- **対象外**: `artifacts/eval/<YYYY-MM-DD>_<NN>.json`（場フィルタ付き）— P4 で別途対応
- **理由**: フィルタなし版とフィルタ付き版が同一日に混在すると二重計上になる地雷を回避

期間内に対応する `<日付>.json` が無い日 → warning + skip。
1 件も見つからなければエラー終了（コード 2）。

---

## 集計指標

### 必須
- 期間 ROI（`Σpayout / Σstake - 1`）
- 月次 ROI トレンド（`YYYY-MM` ごとの ROI / 投資 / 払戻 / hit_rate_per_bet）
- 場別累積 ROI + 場×月次クロス表
- confidence 帯別 ROI（P3 と同じ境界 `[0.0-0.3, 0.3-0.5, 0.5-0.7, 0.7-1.0]`）
- 全体 hit_rate_per_bet / hit_rate_per_race / 平均 confidence / 見送り率
- 日次 ROI 統計（min / median / mean / max / stddev + worst_day / best_day）
- 月次 ROI 統計（同上 + worst_month / best_month）

### 任意
- bootstrap CI（ROI の 95% 信頼区間、N=1000、bet 単位リサンプル、`--no-bootstrap` で無効化可能）

confidence vs ROI の Spearman 相関 / primary_axis 別ヒット率は P4 以降に後送り。

---

## 判定ステータス

| status | 条件 | 意味 |
|---|---|---|
| `production_ready` | ROI ≥ +10% かつ worst_month > -50% かつ bootstrap_ci_lower ≥ 0 | ✓ 実運用再開条件達成 |
| `breakeven` | ROI ≥ 0% かつ worst_month > -50% | △ トントン以上 |
| `fail` | 上記以外 | ✗ 未達 |

判定基準は `BET_RULE_REVIEW_202509_202512.md §30-32` および `MODEL_LOOP_PLAN §3-5`
の実運用再開条件と整合。

**この判定は参考値。後付けフィルタで合わせ込んではならない**
（フェーズ 3〜6 の教訓: 後付けフィルタは out-of-sample で必ず崩れる）。

---

## 警告ルール

CLI が JSON `warnings[]` に積み + ターミナル末尾に表示:

| 条件 | warning 内容 |
|---|---|
| 期間内に `<日付>.json` が一部不在 | `期間内 N 日分の <日付>.json が見つからない（取得済みのみで集計）` |
| `n_bet_races < 30` | `n_bet_races=N < 30: 統計的信頼性低い、N≥100 を推奨` |
| `n_days_with_data < 5` | `累積評価 N=N 日（推奨 30 日以上）— P3.5 完了判定には早期` |

---

## 注意事項

- **既存 `evaluate_predictions.py` を書き換えない**（出力スキーマだけ依存）
- **`predict_llm/` / `collector/` のコードは触らない**
- **累積評価サンプル拡張**: `/prep-races` → `/predict` → `/eval-predictions` を
  ユーザーが手動で複数日繰り返す必要あり。CLI 側はファイル集約のみ
- **実運用購入には使わない**。あくまで Claude の予想精度検証フェーズ
- **ROI が悪い結果でも後付けフィルタを足してチューニングしない**

---

## 実装の場所

- CLI: `ml/src/scripts/eval_summary.py`
- 流用: `predict_llm/stadium_resolver.py`（場名表示のみ）
- 出力: `artifacts/eval/summary_<from>_<to>.json`

詳細: `LLM_PREDICT_DESIGN.md` §3.3「累積評価」 / P3.5 完了メモ
