# P4-β 次セッション用プロンプト（コピペ用）

**最終更新**: 2026-04-27（P4-α 完了分析 + P4-β 準備完了）
**前提コミット**: `06e85ae feat(llm-predict): P4-α 完了分析 + P4-β 場拡大フェーズ準備`

このファイルは LLM 予想システム P4-β（場拡大版運用テスト）の進行管理。
次セッションでこのファイル全体をそのまま貼り付けて使う。

---

## あなたのミッション

P4-α（12 日 × 桐生 1 場 = 596 bets）はサンプル不足（CI 半幅 ±32pp）で
ROI -2.78% が「真値の符号」を判定できない不確定領域だった。

P4-β は **predict.md を変えず、1 場固定 → 全開催場 へ拡大** することで
1 race-day あたりの bets を ~50 → ~700-1000 に増やし、CI を縮める。

詳細計画: [NEXT_PHASE_P4B_PLAN.md](NEXT_PHASE_P4B_PLAN.md)

---

## 進捗テーブル

| Day | 日付 | 場数 | 状態 | races | bets | hits | hit_rate/bet | ROI | 備考 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-01-05 | 16 | 🟡 prep 完了 / predict 未 | 192 | — | — | — | — | 4 場ずつ × 4 セッション目安 |

(以後 Day 2〜12 を 2026-01〜2026-04 から選定して追加)

---

## 今セッションでやること

### 1. 状況確認

```bash
ls artifacts/race_cards/2026-01-05/ | wc -l   # 193 (192 races + index.md) を確認
ls artifacts/predictions/2026-01-05/ 2>/dev/null   # 未実行なら no such file
```

### 2. 直前情報取得（全 192 race 一括、初回のみ）

```bash
py -3.12 ml/src/scripts/fetch_pre_race_info.py 2026-01-05
```

過去日 (mode=past) なので `data/odds/odds_202601.parquet` キャッシュ + K ファイル気象を
使う。展示・進入は欠損（正常）。約 1〜3 分で完了。`[fetch-pre] OK NN_RR ...` が
192 件出れば成功。

### 3. /predict を場ごとに実行（4 場 = 48 races / セッション目安）

このセッションでは以下 4 場（48 races）を処理:

```
/predict 2026-01-05 桐生
/predict 2026-01-05 戸田
/predict 2026-01-05 江戸川
/predict 2026-01-05 平和島
```

各 `/predict` で 12 races の予想 JSON を `artifacts/predictions/2026-01-05/` に
書き出す。1 レース 1 ターンの目安で進める（4 場 × 12R = 48 turns）。

**残り 12 場は次セッション以降**:
- セッション 2: 多摩川 / びわこ / 住之江 / 尼崎
- セッション 3: 鳴門 / 丸亀 / 徳山 / 下関
- セッション 4: 若松 / 福岡 / 唐津 / 大村

### 4. 予想完了レース数の確認

```bash
ls artifacts/predictions/2026-01-05/*.json | grep -v _pre | grep -v index | wc -l
```

48（このセッション完了時）/ 192（全場処理完了時）。

### 5. 全場処理完了後（最終セッション末尾）のみ

```bash
py -3.12 ml/src/scripts/build_predictions_index.py 2026-01-05
py -3.12 ml/src/scripts/evaluate_predictions.py 2026-01-05
```

`artifacts/eval/2026-01-05.json` が出力され、Day 1 完了。
このファイルに進捗テーブルを追記してコミット。

---

## 厳守事項

### コードベース変更禁止
- ❌ `predict.md` プロンプト改善禁止（OOS 評価が汚れる）
- ❌ `predict_llm/` モジュール書き換え禁止
- ❌ `evaluate_predictions.py` / `eval_summary.py` 書き換え禁止
- ❌ `build_race_cards.py` / `fetch_pre_race_info.py` 書き換え禁止

### 戦略選択禁止
- ❌ **場サブセット選択禁止** — 必ず全開催場（休場は B ファイル DL 時に自動除外される）
- ❌ **特定レース選択禁止** — 全 R を処理（ドリーム戦・優勝戦のスキップは Claude verdict=skip でのみ）
- ❌ ROI 悪くても後付けフィルタ追加禁止（フェーズ 3〜6 教訓）

### 運用
- ❌ 実運用購入禁止 — dry-run + 評価のみ
- ❌ Anthropic API 不使用 — Max プラン内 Claude Code 対話セッションで完結
- ✅ 各 race-day 完了時に `/eval-predictions` まで自動実行
- ✅ 判定が出た後の意思決定はユーザー

---

## /predict の作業要領（再掲）

各 race card MD を Read → 分析 → 予想 JSON を Write の流れ。詳細は
`.claude/commands/predict.md` 参照。

- `analysis`: 出走表のどの数字を重視したか、なぜ他の組合せでなくこの買い目か
- `primary_axis`: 1〜2 個（本線の軸艇）
- `verdict`: "bet" or "skip"（"skip" なら `bets` は空、`skip_reason` 必須）
- `bets`: 1〜5 件、各 `trifecta` / `stake` / `current_odds` / `expected_prob` / `ev` / `confidence`
- `confidence`: 0.0〜1.0 自由値、`expected_prob × current_odds ≒ ev` を意識

過去日 (mode=past) で展示・進入が欠損する点は P4-α と同じ。出走表 + 場特性 +
オッズだけで判断するか、不確実性が高ければ skip 推奨（P4-α 教訓: 不確実時の
無理 bet は ROI を下げるだけ）。

---

## 撤退ライン（P4-α より厳格化）

12 race-days 完了時点で以下 3 条件を**すべて**満たせば撤退、B-3 単勝市場効率分析へ移行:

1. 通算 ROI < -15%（旧 -20%）
2. 4 ヶ月のうち 3 ヶ月以上で月次 ROI < -10%
3. **bootstrap CI 上限 < +5%**（旧 0%）

→ サンプル増による検出力向上を反映した強化条件。

---

## 完了後の意思決定フロー

12 race-days 終了時の判定 → 次のいずれかへ:

| 判定 | 次アクション |
|---|---|
| production_ready (ROI ≥ +10% & worst > -50% & CI 下限 ≥ 0) | P5 実走テスト計画策定 |
| breakeven (ROI ≥ 0% & worst > -50%) | データ追加 (20 race-days まで延長) |
| 不確定 (CI 半幅 > ±15pp) | データ追加で CI 縮小 |
| 撤退ライン到達 | B-3 単勝市場効率 Step 2 へ移行（[NEXT_SESSION_PROMPT.md](NEXT_SESSION_PROMPT.md)） |

---

## 参考資料

- 計画書: [NEXT_PHASE_P4B_PLAN.md](NEXT_PHASE_P4B_PLAN.md)
- P4-α 履歴: [NEXT_SESSION_PROMPT_P4.md](NEXT_SESSION_PROMPT_P4.md)（Day 1〜11 詳細）
- 分析スクリプト: `artifacts/analysis_p4a.py` / `analysis_p4a_interactions.py` / `analysis_p4a_samplesize.py`
- 設計書: [LLM_PREDICT_DESIGN.md](LLM_PREDICT_DESIGN.md)
- B-3 撤退時の代替: [NEXT_SESSION_PROMPT.md](NEXT_SESSION_PROMPT.md)
