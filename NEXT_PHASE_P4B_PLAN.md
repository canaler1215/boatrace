# P4-β 計画書 — 場拡大による測定問題解決

**作成**: 2026-04-27
**前提**: P4-α 完了（12 race-days × 桐生 1 場 = 596 bets / ROI -2.78% / 判定 fail）
**目的**: predict.md のエッジ有無を統計的に判定可能なサンプル数を集める

---

## 1. なぜ P4-β か (動機)

P4-α の `/eval-summary --from 2025-09-01 --to 2025-12-31` 結果:

- 通算 ROI: -2.79%
- bootstrap 95% CI: **[-33.6%, +30.7%]**（半幅 ±32pp）
- P(真の ROI > 0%) = 41.2%、P(真の ROI > +10%) = 22.2%

サンプルサイズ分析（artifacts/analysis_p4a_samplesize.py）の結論:

| 検出したい真値 | 必要 bets | 日数 (50 bets/day) |
|---|---|---|
| ROI = +10% を 0% から区別 | **9,979 bets** | **200 日** |
| ROI = +15% を 0% から区別 | 4,435 bets | 89 日 |
| ROI = +20% を 0% から区別 | 2,495 bets | 50 日 |

**結論**: 12 日 596 bets では Production Ready 基準（ROI ≥ +10% を CI 下限 ≥ 0 で示す）を判定できない。
「fail」判定は統計的に不当。場拡大でサンプル密度を上げる必要がある。

---

## 2. P4-β の設計

### 2.1 中核戦略
**predict.md は変更しない**。同じ prompt が **より多くのレース** で signal を持つかを測る。
これは「測定問題の解決」であり「prompt 改善」ではない。

### 2.2 場拡大方針

| 項目 | P4-α | P4-β |
|---|---|---|
| 1 race-day あたりの場 | 1 場（桐生固定） | **その日の全開催場**（典型 12〜18 場） |
| 1 race-day あたりの races | 12 | **約 144〜216** |
| 1 race-day あたりの bets | ~50 | **~700〜1,000** |
| 期間 | 2025-09〜2025-12 | **2026-01〜2026-04**（OOS、未着手） |
| 目標 race-days | 12 | **12 を最低、可能なら 20+** |
| 目標 bets | (達成 596) | **8,000〜15,000+** |

### 2.3 場選択ポリシー
**全開催場を採用**。場サブセット選択は selection bias を生むため避ける。
B ファイル DL 時に休場場は自動除外される（既存挙動）。

### 2.4 日付選択

OOS 用に **2026-01〜2026-04** から選定（P4-α は 2025-09〜2025-12 = 4 ヶ月をカバー済み、
2026-01〜2026-04 = 4 ヶ月の OOS が必要）。

**P4-α と同じ「月内ほぼ等間隔 3 日」パターンに準拠**:

| 月 | 候補日 | 備考 |
|---|---|---|
| 2026-01 | **05** / 19 / 30 | Day 1 = 2026-01-05 prep 済み（16 場 / 192 races） |
| 2026-02 | 04 / 18 / 28 | (28 は土曜) |
| 2026-03 | 04 / 18 / 30 | |
| 2026-04 | 01 / 15 / 25 | (25 は土曜、open 場確認要) |

**12 race-days 完了で第一次評価**。CI 半幅が ±15pp 未満 + 月次トレンド明瞭になれば判定可能。

### 2.5 1 セッションあたりの作業量と分割

192 races / 1 race-day を 1 セッションで処理するのは現実的でない。**場単位で分割可**:

```
Session A: /predict 2026-01-05 桐生   (12 races)
Session A: /predict 2026-01-05 戸田   (12 races)
Session A: /predict 2026-01-05 江戸川 (12 races)
Session A: /predict 2026-01-05 平和島 (12 races)
→ 計 48 races / セッション、~1.5〜2 時間
```

複数セッションに分けた後、最後に:
```
/predict 2026-01-05  (残り全場、または何もせず)
py -3.12 ml/src/scripts/build_predictions_index.py 2026-01-05  # 集約
py -3.12 ml/src/scripts/evaluate_predictions.py 2026-01-05      # 評価
```

**1 race-day を最大 4 セッションで完了** を目安とする（場 16〜18 を 4 場 × 4 セッション）。

---

## 3. 評価基準

### 3.1 判定ステータス（P4-α と同基準）
- **production_ready**: 通算 ROI ≥ +10% かつ worst_month > -50% かつ bootstrap CI 下限 ≥ 0
- **breakeven**: 通算 ROI ≥ 0% かつ worst_month > -50%
- **fail**: それ以外

### 3.2 P4-β 期間中の中間判定指標（参考）

12 race-days 完了時点で以下を確認:

1. CI 半幅が ±15pp 以下に縮んでいるか
2. 月次 ROI の symbols が一致しているか（4 ヶ月すべてプラス / すべてマイナス / 一部のみ）
3. P(真の ROI > 0%) が 60% 超 or 40% 未満（不確定領域 [40%, 60%] を脱したか）

### 3.3 撤退ライン（P4-α より厳格化）

P4-α の撤退ライン 3 条件は維持しつつ、サンプル増による検出力向上を反映:

1. 通算 ROI < -15%（旧 -20%）
2. 4 ヶ月のうち 3 ヶ月以上で月次 ROI < -10%（変更なし）
3. **bootstrap CI 上限 < +5%（旧 0%）**

3 条件すべて満たせば撤退、B-3 単勝市場効率分析へ移行。

---

## 4. 厳守事項

### P4-α から継承
- ❌ Anthropic API（API キー）使用禁止 — Max プラン内完結
- ❌ `predict_llm/` `evaluate_predictions.py` `eval_summary.py` 書き換え禁止
- ❌ **`predict.md` プロンプト改善禁止**（OOS 評価が汚れる）
- ❌ ROI 悪くても後付けフィルタ追加禁止
- ❌ 実運用購入禁止 — dry-run + 評価のみ
- ✅ 各日の予想完了時に `/eval-predictions` まで自動実行
- ✅ 判定が出た後の意思決定はユーザー

### P4-β 新規
- ❌ **場サブセット選択禁止**（selection bias）— 全開催場を必ず処理
- ❌ **特定レース選択禁止** — 全 R を処理（ドリーム戦・優勝戦などのスキップは Claude の verdict=skip でのみ可）
- ✅ 1 race-day を複数セッションで分割実行可
- ✅ 残り場 / 残り R は `ls artifacts/predictions/<date>/` で確認

---

## 5. Day 1 状況（2026-01-05、prep 済み）

```
date: 2026-01-05
open stadiums: 16 場
  01 桐生 / 02 戸田 / 03 江戸川 / 04 平和島 / 05 多摩川
  11 びわこ / 12 住之江 / 13 尼崎 / 14 鳴門 / 15 丸亀
  18 徳山 / 19 下関 / 20 若松 / 22 福岡 / 23 唐津 / 24 大村
closed: 06 浜名湖 / 07 蒲郡 / 08 常滑 / 09 津 / 10 三国 / 16 児島 / 17 宮島 / 21 芦屋
total races: 192
race cards: artifacts/race_cards/2026-01-05/ に 192 ファイル + index.md 配置済み
```

次セッションでの作業手順:

```
# 1. 直前情報取得（1 回で全場 192 race 分の odds parquet キャッシュを使う）
py -3.12 ml/src/scripts/fetch_pre_race_info.py 2026-01-05

# 2. 場ごとに /predict（4 場ずつ × 4 セッション目安）
/predict 2026-01-05 桐生
/predict 2026-01-05 戸田
/predict 2026-01-05 江戸川
/predict 2026-01-05 平和島
（次セッションで残り 12 場）

# 3. 全場処理完了後
py -3.12 ml/src/scripts/build_predictions_index.py 2026-01-05
py -3.12 ml/src/scripts/evaluate_predictions.py 2026-01-05
```

---

## 6. 進捗管理

- 各 race-day 完了時に `/eval-predictions <date>` で日次 JSON を生成
- 累計 `/eval-summary --from 2026-01-01 --to 2026-04-30` で進捗確認
- このファイルの「進捗テーブル」を都度更新

### 進捗テーブル

| Day | 日付 | 状態 | 場数 | races | bets | hits | hit_rate/bet | ROI | 備考 |
|---|---|---|---|---|---|---|---|---|---|
| Prep | 2026-01-05 | 🟡 prep 完了 / predict 未 | 16 | 192 | — | — | — | — | Day 1 候補 |

---

## 7. 完了後の意思決定フロー

12 race-days 終了時の判定 → 次のいずれかへ:

| 判定 | 次アクション |
|---|---|
| production_ready 達成 (ROI ≥ +10% & CI 下限 ≥ 0) | P5 実走テスト計画策定 |
| breakeven (ROI ≥ 0%) | データ追加 (20 race-days まで延長) で精度向上 |
| 不確定 (CI 半幅 > ±15pp) | データ追加で CI 縮小 |
| 撤退ライン到達 | B-3 単勝市場効率 Step 2 へ移行（[NEXT_SESSION_PROMPT.md](NEXT_SESSION_PROMPT.md)） |

---

## 8. 参考データ

- 分析スクリプト: `artifacts/analysis_p4a.py` / `analysis_p4a_interactions.py` / `analysis_p4a_samplesize.py`
- P4-α 結果: [NEXT_SESSION_PROMPT_P4.md](NEXT_SESSION_PROMPT_P4.md) Day 1〜11 詳細
- 設計書: [LLM_PREDICT_DESIGN.md](LLM_PREDICT_DESIGN.md)
- B-3 撤退時の代替: [NEXT_SESSION_PROMPT.md](NEXT_SESSION_PROMPT.md)
