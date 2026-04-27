# P4-β 次セッション用プロンプト（コピペ用）

**最終更新**: 2026-04-27（Day 1 セッション 3 完了 / 12 場 = 144 races 予想実行済）
**前提コミット**: `bd45e07 feat(llm-predict): P4-β Day 1 S3 - 2026-01-05 鳴門・丸亀・徳山・下関 4 場予想実行`

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
| 1 | 2026-01-05 | 16 | 🟡 12/16 場 完了 (S1+S2+S3) | 192 | 16 (S1+S2+S3 部分) | 未集計 | 未集計 | 未集計 | 残り 4 場で S4 → 完了 |

### Day 1 セッション内訳

| Session | 場 | 状態 | races | bets | 備考 |
|---|---|---|---|---|---|
| S1 | 桐生・戸田・江戸川・平和島 | ✅ 完了 (2026-04-27) | 48 | 13 | skip 35 (skip 率 73%) |
| S2 | 多摩川・びわこ・住之江・尼崎 | ✅ 完了 (2026-04-27) | 48 | 3 | skip 45 (skip 率 94%) |
| S3 | 鳴門・丸亀・徳山・下関 | ✅ 完了 (2026-04-27) | 48 | 0 | skip 48 (skip 率 100%) |
| S4 | 若松・福岡・唐津・大村 | 🟡 未着手 | 48 | — | **このセッションでやる + Day 1 評価実行** |

### S1 bet 内訳（参考、前セッションの判断基準確認用）

- 桐生 R1 `2-4-1` (16.2x, conf 0.4) — 1号艇弱・2号艇A2当地強の流し
- 戸田 R8 `1-6-2` (21.1x, conf 0.45), `1-6-4` (37.9x, conf 0.4) — 6号艇A1飛田過小評価
- 江戸川 R3 `4-3-1` (28.6x, conf 0.4) — 4号艇A1渡邉まくり時の3着 1号艇内枠流し残り
- 江戸川 R7 `3-2-1` (33.2x, conf 0.45), `3-1-2` (27.0x, conf 0.4) — 3号艇A1石渡当地レジェンドの本命まくり
- 平和島 R6 `1-3-2` (32.0x, conf 0.4), `1-3-4` (44.7x, conf 0.35), `1-4-2` (38.8x, conf 0.35) — 1号艇本命+3着候補分散
- 平和島 R7 `1-3-2` (24.3x, conf 0.35) — 同上
- 平和島 R8 `1-3-2` (51.7x, conf 0.35), `1-2-3` (45.7x, conf 0.35) — 同上
- 平和島 R11 `1-4-3` (39.5x, conf 0.4) — 4号艇2着 (3.6x) を3着想定の妙味組合せ

### S2 bet 内訳（参考、前セッションの判断基準確認用）

- 多摩川 R8 `6-1-2` (45.3x, conf 0.35) — 6号艇A1角谷（当地2連率51%）が単勝2.3xで1号艇A2より低人気の異常値
- びわこ R8 `1-6-3` (50.1x, conf 0.30) — 6号艇A2廣瀬凜（当地直近6走1着3=50%）の好調シグナル、1-3頭固定+6号艇3着捲り差し
- 尼崎 R7 `6-3-1` (60.5x, conf 0.30) — 6号艇A1稲田（当地直近6走1着5・直近10走1着6）の異常好調、6号艇まくり1着シナリオ

### S3 bet 内訳（参考、前セッションの判断基準確認用）

- **bet 0 件 / 全 48 races skip**（skip 率 100%）

### S1 全体傾向

- skip 率 73%（11/12 が桐生で大半 skip、平和島は 7/12 で bet あり）
- bet パターン: ①1号艇本命固定+3着分散組合せ ②内枠弱・センターA1まくり時の3着流し
- **EV ボーダー <1.0 は基本 skip**、本命人気サイドは過剰人気で EV<0.5-0.7 が常態

### S2 全体傾向

- skip 率 94%（多摩川・びわこ・住之江・尼崎は 1 コース勝率 55-69% の 1 強場で本命過剰人気が常態）
- bet パターン 3 件すべて統一: **6 号艇 A1/A2 の異常好調シグナル → 6コース捲り組合せ**
  （6 コース勝率 2-3% を覆す配当 60x 前後で EV ≒ 1.05-1.09）
- A1×3-4 充実メンバーの予選特選では本命系も捲り系も EV<0.5 で買い目なし

### S3 全体傾向

- skip 率 **100%（48/48 races 全 skip、bet 0 件）**
- 主因:
  1. 新年正月選抜・優勝戦・準優勝戦の **A1×3-5 充実構成多発**、
     1号艇 A1 単勝 1.0-1.5x の極端本命で 3連単本命系 EV<0.30 が常態化
  2. 鳴門/徳山 1 コース勝率 64% / 下関 60% の超内枠強場
  3. **異例構図でも市場完全織込済**（丸亀 R7 6号艇 A1 単勝 1.6x、徳山 R7 3号艇 A2 単勝 1.4x、
     下関 R1 4号艇 A2 単勝 1.1x、下関 R2 4号艇 A2 連勝中 1.7x 等）
  4. **S2 教訓「6号艇 A1 異常好調 → 60x 前後で初めて妙味」基準**を満たす組合せ無し
     （最高 37-50x で EV ~0.60-0.75 ボーダー、展示欠損下で慎重 skip 推奨）
- ただし 1 月 5 日特有の「正月特選 A1 充実」が S3 場の 100% skip を引き上げた可能性が高い。
  Day 2 以降の通常開催で skip 率がどう変動するかを観測する

(以後 Day 2〜12 を 2026-01〜2026-04 から選定して追加)

---

## 今セッションでやること（S4: 若松・福岡・唐津・大村 + Day 1 評価実行）

### 1. 状況確認

```bash
# S1+S2+S3 で生成済 = 144 件 (12 場 × 12R) の予想 + 192 件の _pre が並ぶ
ls artifacts/predictions/2026-01-05/*.json | grep -v _pre | grep -v index | wc -l   # 144 + 1 index = 145 を確認
ls artifacts/race_cards/2026-01-05/ | wc -l   # 193 (192 races + index.md) を確認
```

### 2. 直前情報取得（**S1 で実施済 → スキップ**）

S1 セッションで `fetch_pre_race_info.py 2026-01-05` 実行済 = 全 192 race の race card MD に
直前情報セクション追記済 + `*_pre.json` 出力済。**再実行不要**。

ただし、念のため対象場の race card に `## ▼ 直前情報` セクションがあるか確認:

```bash
grep -l "## ▼ 直前情報" artifacts/race_cards/2026-01-05/20_*.md  # 若松 12 件出れば OK
grep -l "## ▼ 直前情報" artifacts/race_cards/2026-01-05/22_*.md  # 福岡
grep -l "## ▼ 直前情報" artifacts/race_cards/2026-01-05/23_*.md  # 唐津
grep -l "## ▼ 直前情報" artifacts/race_cards/2026-01-05/24_*.md  # 大村
```

### 3. /predict を場ごとに実行（4 場 = 48 races）

このセッションでは以下 4 場（48 races）を処理:

```
/predict 2026-01-05 若松
/predict 2026-01-05 福岡
/predict 2026-01-05 唐津
/predict 2026-01-05 大村
```

各 `/predict` で 12 races の予想 JSON を `artifacts/predictions/2026-01-05/` に
書き出す。1 レース 1 ターンの目安で進める（4 場 × 12R = 48 turns）。

**S4 で全場処理完了 → Day 1 完了**。

### 4. 予想完了レース数の確認

```bash
ls artifacts/predictions/2026-01-05/*.json | grep -v _pre | grep -v index | wc -l
```

**192**（全場処理完了）になっているか確認。

### 5. S4 完了後 = 全場処理完了後の Day 1 評価実行（このセッションで実行）

S4 ですべての 192 race の予想 JSON が揃ったら、以下を実行:

```bash
py -3.12 ml/src/scripts/build_predictions_index.py 2026-01-05  # 全 192 件で再生成
py -3.12 ml/src/scripts/evaluate_predictions.py 2026-01-05
```

`artifacts/eval/2026-01-05.json` が出力され、Day 1 完了。

評価結果（ROI / hit_rate / 場別 / confidence 帯別）を確認し、進捗テーブルに追記してコミット。

> **注**: S3 末尾で 144 件分の `index.json` は既に生成済（144 valid / 0 invalid、bet=11 races / skip=133 races）。
> S4 末尾で 192 件全件で再生成 → そのまま `evaluate_predictions.py` に渡す流れ。

### 6. Day 1 評価結果のコミット & push

```bash
git add artifacts/predictions/2026-01-05/index.json artifacts/predictions/2026-01-05/20_*.json \
        artifacts/predictions/2026-01-05/22_*.json artifacts/predictions/2026-01-05/23_*.json \
        artifacts/predictions/2026-01-05/24_*.json artifacts/eval/2026-01-05.json
git commit -m "feat(llm-predict): P4-β Day 1 S4 + 評価 - 2026-01-05 全 16 場 192 races 完了"
git push origin main
```

その後、本ファイル（NEXT_SESSION_PROMPT_P4B.md）を Day 2 用に更新（次の race-day 選定 +
S1 用構成へリセット）してコミット & push。

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

S1+S2+S3 で確認された定型パターン（参考、強要ではない）:
- **本命 1号艇 単勝 1.0-1.5x**: 3連単本命 5-10x は EV<0.5、3着候補分散時のみ 30-50x で EV>1.0
- **1号艇弱・2-3-4号艇A1まくり**: 軸選手の3着組合せに妙味（オッズ 25-40x）
- **三者拮抗 (単勝 2-3x が3艇)**: 人気分散で買い目薄、skip 妥当
- **A1×3-4 充実メンバーの予選特選・準優勝戦・優勝戦**: 1号艇単勝 1.0-1.2x で 3連単
  オッズが薄く EV<0.5、原則 skip（**S3 では正月選抜が多発しほぼ全 skip**）
- **6号艇A1/A2 の異常好調シグナル**（S2 で 3 例採用、S3 では基準満たさず 0 例）:
  - 当地直近 6 走で 1 着 3-5 回 + 単勝 2-12x の過小評価がトリガー
  - 6コース勝率 2-3% を覆すには配当 60x 前後が必要（市場が完全に切っている時のみ妙味）
  - パターン: `6-1-X` `6-3-X` `1-6-X` `3-6-X` の捲り or 3着流し
- **異例の外枠 A1/A2 単勝大本命**（S3 で多発、すべて skip）:
  下関 R1 4号艇 A2 単勝 1.1x、丸亀 R7 6号艇 A1 単勝 1.6x、下関 R2 4号艇 A2 単勝 1.7x 等
  → 市場が完全織込済で 3連単オッズも凝縮、EV<0.50 で skip 妥当

**EV ボーダー判定**:
- EV ≥ 1.0 → bet 候補
- 0.85 ≤ EV < 1.0 → 微妙（confidence 高ければ bet 検討）
- EV < 0.85 → 原則 skip
- **境界 (EV ≒ 1.0-1.05) で展示欠損下では P 楽観のリスク高、conservative skip 推奨**（S2 教訓）

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

## 場ID 対応表（場名→ ID）

`/predict 2026-01-05 <場名>` の場名は以下のいずれかでOK（漢字推奨）。

| ID | 場名 | S グループ |
|---|---|---|
| 01 | 桐生 | S1 ✅ |
| 02 | 戸田 | S1 ✅ |
| 03 | 江戸川 | S1 ✅ |
| 04 | 平和島 | S1 ✅ |
| 05 | 多摩川 | S2 ✅ |
| 11 | びわこ | S2 ✅ |
| 12 | 住之江 | S2 ✅ |
| 13 | 尼崎 | S2 ✅ |
| 14 | 鳴門 | S3 ✅ |
| 15 | 丸亀 | S3 ✅ |
| 18 | 徳山 | S3 ✅ |
| 19 | 下関 | S3 ✅ |
| 20 | 若松 | **S4 (今回)** |
| 22 | 福岡 | **S4 (今回)** |
| 23 | 唐津 | **S4 (今回)** |
| 24 | 大村 | **S4 (今回)** |

(2026-01-05 は 1月開催のため、6/桐生3R 等 ID 06-10/16-17/21 の 8 場は休場)

---

## 参考資料

- 計画書: [NEXT_PHASE_P4B_PLAN.md](NEXT_PHASE_P4B_PLAN.md)
- P4-α 履歴: [NEXT_SESSION_PROMPT_P4.md](NEXT_SESSION_PROMPT_P4.md)（Day 1〜11 詳細）
- 分析スクリプト: `artifacts/analysis_p4a.py` / `analysis_p4a_interactions.py` / `analysis_p4a_samplesize.py`
- 設計書: [LLM_PREDICT_DESIGN.md](LLM_PREDICT_DESIGN.md)
- B-3 撤退時の代替: [NEXT_SESSION_PROMPT.md](NEXT_SESSION_PROMPT.md)
- S3 セッション末尾の index 検証: `artifacts/predictions/2026-01-05/index.json` (144 valid / 0 invalid, bet 11 races / skip 133 races)
