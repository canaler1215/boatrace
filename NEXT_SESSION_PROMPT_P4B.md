# P4-β 次セッション用プロンプト（コピペ用）

**最終更新**: 2026-04-27（Day 1 完了 / 192 races 評価済 / Day 2 着手用にリセット）
**前提コミット**: `a1e079e feat(llm-predict): P4-β Day 1 S4 + 評価 - 2026-01-05 全 16 場 192 races 完了`

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
| 1 | 2026-01-05 | 16 | ✅ 完了 (2026-04-27) | 192 | 17 | 1 | 5.88% | **+88.2%** | 正月選抜多発で skip_rate 93.8% |
| 2 | **2026-01-12** | TBD | 🟡 未着手 | — | — | — | — | — | **このセッションで Day 2 全体を実行** |

### Day 1 結果サマリ（参考、Day 2 への引継ぎ用）

- **2026-01-05**: 16 場 / 192 races 全 settled / 17 bets / **1 hit** (平和島 6R `1-3-2` 32.0x)
- **ROI +88.2%** / hit_rate/bet 5.88% / skip_rate **93.8%** / avg_confidence 0.37
- 場別 ROI: 平和島 +357.1% (1 hit / 7 bets)、他 7 場 -100%
- 唯一の hit: 平和島 6R 「1号艇本命+3着候補分散」パターン（S1 セッション）
- Day 1 は正月選抜・準優勝戦・優勝戦が多発し、**A1×3-5 の本命系オッズ薄**で skip 多発
- Day 2 以降の通常開催で skip 率が下がるかが観測ポイント

#### Day 1 セッション別 (S1 〜 S4) 観察知見

| Session | 場 | bets | skip 率 | 主要 bet パターン |
|---|---|---|---|---|
| S1 | 桐生・戸田・江戸川・平和島 | 13 | 73% | 平和島 1-3-2 系の3着候補分散 / 戸田 1-6-X 6号艇A1飛田過小評価 |
| S2 | 多摩川・びわこ・住之江・尼崎 | 3 | 94% | 6号艇A1異常好調 → 60x前後で 6-1-X / 6-3-X / 1-6-X / 3-6-X |
| S3 | 鳴門・丸亀・徳山・下関 | 0 | **100%** | 全 skip（正月選抜 A1 充実 + 異例構図も市場完全織込済） |
| S4 | 若松・福岡・唐津・大村 | 1 | 98% | 福岡 7R `6-1-2` 60.4x（松村A1 全国7.53/直近10走1着4 異常好調 S2 教訓基準） |

#### 確認された定型パターン（Day 2 以降の参考、強要ではない）

- **本命 1号艇 単勝 1.0-1.5x**: 3連単本命 5-10x は EV<0.5、3着候補分散時のみ 30-50x で EV>1.0
- **1号艇弱・2-3-4号艇A1まくり**: 軸選手の3着組合せに妙味（オッズ 25-40x）
- **三者拮抗 (単勝 2-3x が3艇)**: 人気分散で買い目薄、skip 妥当
- **A1×3-4 充実メンバーの予選特選・準優勝戦・優勝戦**: 1号艇単勝 1.0-1.2x で
  3連単オッズが薄く EV<0.5、原則 skip
- **6号艇A1/A2 の異常好調シグナル**（S2 で 3 例採用、S4 で 1 例採用）:
  - 当地直近 6 走で 1 着 3-5 回 + 単勝 2-12x の過小評価がトリガー
  - 6コース勝率 2-3% を覆すには配当 60x 前後が必要（市場が完全に切っている時のみ妙味）
  - パターン: `6-1-X` `6-3-X` `1-6-X` `3-6-X` の捲り or 3着流し
- **異例の外枠 A1/A2 単勝大本命**: 市場が完全織込済で 3連単オッズも凝縮、EV<0.50 で skip 妥当

**EV ボーダー判定**:
- EV ≥ 1.0 → bet 候補
- 0.85 ≤ EV < 1.0 → 微妙（confidence 高ければ bet 検討）
- EV < 0.85 → 原則 skip
- **境界 (EV ≒ 1.0-1.05) で展示欠損下では P 楽観のリスク高、conservative skip 推奨**（S2 教訓）

(以後 Day 3〜12 を 2026-01〜2026-04 から選定して追加)

---

## 今セッションでやること（Day 2 = 2026-01-12 全体）

Day 2 から S1 〜 S4 を分割せず、**1 セッションで全場処理 → 評価実行**を目指す。
Day 1 の skip 率 93.8% を踏まえ、bet が少なければ予想自体は短時間で済む。
ただし context が逼迫した場合は Day 2 を S1+S2 / S3+S4 の 2 セッションに分割しても良い。

### 1. レースカード生成 + 直前情報取得

```bash
py -3.12 ml/src/scripts/build_race_cards.py 2026-01-12
py -3.12 ml/src/scripts/fetch_pre_race_info.py 2026-01-12
```

`build_race_cards.py` で 2026-01-12 の全開催場 race card を `artifacts/race_cards/2026-01-12/` に
生成、`fetch_pre_race_info.py` で各 race card MD に直前情報セクションを追記。

成功確認:
```bash
ls artifacts/race_cards/2026-01-12/ | wc -l   # 場数 × 12 + index.md
grep -l "## ▼ 直前情報" artifacts/race_cards/2026-01-12/*.md | wc -l
```

両方の数が一致していること。

### 2. /predict を場ごとに実行（全開催場 = 約 12-18 場）

開催場が出揃ったら以下を順次実行:

```
/predict 2026-01-12 桐生
/predict 2026-01-12 戸田
/predict 2026-01-12 江戸川
... (全開催場)
```

各 `/predict` で 12 races の予想 JSON を `artifacts/predictions/2026-01-12/` に書き出す。
1 レース 1 ターンの目安で進める。

**ペース配分の目安**:
- 簡明な構図 (1号艇本命 + 拮抗薄) は 1 ターン以内で skip 判定 + JSON 書き出し
- S2 教訓「6号艇A1異常好調 → 60x 前後」シグナルだけは丁寧に EV 計算
- 過去日 mode=past で展示・進入欠損のため、出走表 + 場特性 + オッズだけで判断

### 3. 予想完了レース数の確認

```bash
ls artifacts/predictions/2026-01-12/*.json | grep -v _pre | grep -v index | wc -l
```

開催場 × 12 と一致することを確認。

### 4. index 再生成 + Day 2 評価実行

```bash
py -3.12 ml/src/scripts/build_predictions_index.py 2026-01-12
py -3.12 ml/src/scripts/evaluate_predictions.py 2026-01-12
```

`artifacts/eval/2026-01-12.json` が出力されたら Day 2 完了。

評価結果（ROI / hit_rate / 場別 / confidence 帯別）を確認し、進捗テーブルに追記。

### 5. Day 2 評価結果のコミット & push

```bash
git add artifacts/race_cards/2026-01-12/ artifacts/predictions/2026-01-12/ artifacts/eval/2026-01-12.json
git commit -m "feat(llm-predict): P4-β Day 2 - 2026-01-12 全 N 場 races 完了"
git push origin main
```

その後、本ファイル（NEXT_SESSION_PROMPT_P4B.md）を Day 3 用に更新。
**Day 3 の日付候補**: 2026-01-20 (1月3週目) または 2026-01-26 (1月4週目)。

### 6. ユーザー確認事項（Day 2 完了時）

Day 2 完了後、以下をユーザーに確認:

1. **Day 1+2 累積 ROI のトレンド**: 撤退ライン（通算 < -15% & 月次 < -10% × 3ヶ月 & CI上限 < +5%）
   からの距離。Day 2 単独 ROI が極端に悪い (例 -50% 以下) かつ Day 1 ROI と乖離が大きい場合
   は早期撤退を検討
2. **bet 数のペース確認**: Day 1 = 17 bets。Day 2 で 30-50 bets ペースが出るか。
   出ない場合は **prompt が保守すぎる構造的問題**を疑う必要があり、ユーザーと相談
3. **Day 3 の日付**: 自動で「2026-01-20」を選ぶか、ユーザー指定

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

**早期撤退判定** (Day 4 完了時):
- 4 race-days 累積 ROI < -50% かつ全 race-day マイナス → 12 日完走前に B-3 へ移行検討
- ユーザー判断必須

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

`/predict 2026-01-12 <場名>` の場名は以下のいずれかで OK（漢字推奨）。

| ID | 場名 | ID | 場名 |
|---|---|---|---|
| 01 | 桐生 | 13 | 尼崎 |
| 02 | 戸田 | 14 | 鳴門 |
| 03 | 江戸川 | 15 | 丸亀 |
| 04 | 平和島 | 16 | 児島 |
| 05 | 多摩川 | 17 | 宮島 |
| 06 | 浜名湖 | 18 | 徳山 |
| 07 | 蒲郡 | 19 | 下関 |
| 08 | 常滑 | 20 | 若松 |
| 09 | 津 | 21 | 芦屋 |
| 10 | 三国 | 22 | 福岡 |
| 11 | びわこ | 23 | 唐津 |
| 12 | 住之江 | 24 | 大村 |

休場は B ファイル DL 時に自動除外。`build_race_cards.py 2026-01-12` 実行後、
`ls artifacts/race_cards/2026-01-12/ | grep -E "^[0-9]" | cut -c1-2 | sort -u` で
開催場 ID を確認できる。

---

## Day 2 想定タスク量

Day 1 = 16 場 / 192 races / 17 bets。Day 2 = 同程度〜やや多めを想定。
通常開催日は予選・準優勝戦・優勝戦混在で skip 率は **70-90% 程度**になる見込み。
Day 1 の S3 (100%) は正月選抜の特異例。

**1 セッションで完走を目指す場合の目安**:
- 192 races × 30 秒/race（読み + 分析 + JSON 書き）= 約 90 分
- bet 候補のみ詳細評価で 1-2 分かかるため、bet 30 件想定で +30 分
- 合計 2 時間程度

context 逼迫が見えた時点で S1+S2 / S3+S4 の 2 セッション分割に切り替え。

---

## 参考資料

- 計画書: [NEXT_PHASE_P4B_PLAN.md](NEXT_PHASE_P4B_PLAN.md)
- P4-α 履歴: [NEXT_SESSION_PROMPT_P4.md](NEXT_SESSION_PROMPT_P4.md)（Day 1〜11 詳細）
- 分析スクリプト: `artifacts/analysis_p4a.py` / `analysis_p4a_interactions.py` / `analysis_p4a_samplesize.py`
- 設計書: [LLM_PREDICT_DESIGN.md](LLM_PREDICT_DESIGN.md)
- B-3 撤退時の代替: [NEXT_SESSION_PROMPT.md](NEXT_SESSION_PROMPT.md)
- Day 1 結果: `artifacts/eval/2026-01-05.json`（17 bets / 1 hit / ROI +88.2%）
