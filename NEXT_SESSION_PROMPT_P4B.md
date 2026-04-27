# P4-β 次セッション用プロンプト（コピペ用）

**最終更新**: 2026-04-28（Day 2 S2b = 住之江・尼崎・鳴門・丸亀 完了 / 48 races / 0 bets / S2 残り 5 場 60 races = S2c）
**前提コミット**: 次セッション開始時に `git log -1 --oneline` で確認すること

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
| 2 | **2026-01-12** | 15 | 🟡 S1+S2a+S2b 完了 / S2c 残り | 120/180 | 8 | — | — | — | **このセッションで S2c (5 場 60 races) を実行 → /eval-predictions** |

### Day 1 結果サマリ（参考）

- **2026-01-05**: 16 場 / 192 races 全 settled / 17 bets / **1 hit** (平和島 6R `1-3-2` 32.0x)
- **ROI +88.2%** / hit_rate/bet 5.88% / skip_rate **93.8%** / avg_confidence 0.37
- 場別 ROI: 平和島 +357.1% (1 hit / 7 bets)、他 7 場 -100%
- 唯一の hit: 平和島 6R 「1号艇本命+3着候補分散」パターン

### Day 2 S1 結果サマリ（参考、S2 への引継ぎ用）

- **2026-01-12 S1 (桐生・戸田)**: 24 races / **8 bets** / skip 16 / skip_rate 67%
- 桐生 12R: 4 bets (R1=3-1-4, R3=2-1-4, R4=1-5-2, R9=4-1-6) / 8 skip
- 戸田 12R: 4 bets (R3=5-2-3, R4=2-4-6, R9=3-1-5, R10=6-1-2) / 8 skip
- avg_confidence: ~0.48
- **観察**: 通常開催で skip 率 67%（Day 1 S1 = 73% より低下、bet 機会増加）
- **採用パターン**: 1号艇B1×3-4号艇A1まくり, 5/6号艇A1異常好調シグナル, A2 当地巧者の差し
- **回避パターン**: A1×3-4本命系凝縮 (EV<1.0), 三者拮抗で人気分散, ドリーム戦

### Day 2 S2a 結果サマリ（参考、2026-04-28 完了）

- **2026-01-12 S2a (江戸川・多摩川・浜名湖・津)**: 48 races / **0 bets** / skip 48 / skip_rate **100%**
- 江戸川 12R: 全 12 skip（A1充実選抜・三者拮抗・1号艇B1過剰人気が支配的）
- 多摩川 12R: 全 12 skip（1号艇B1/B2 単勝1.2-1.4x 凝縮、5号艇A1 当地2走連勝も織込済）
- 浜名湖 12R: 全 12 skip（A1×4優勝戦 12R 含む、3-6号艇 A1まくり差し脅威も EV<0.5）
- 津 12R: 全 12 skip（A1×2 拮抗・1号艇単勝1.0x大本命凝縮多発、3-4号艇欠場で5艇展開複数）

### Day 2 S2b 結果サマリ（参考、S2c への引継ぎ用、2026-04-28 完了）

- **2026-01-12 S2b (住之江・尼崎・鳴門・丸亀)**: 48 races / **0 bets** / skip 48 / skip_rate **100%**
- 住之江 12R: 全 12 skip（1号艇本命凝縮 1.0-1.4x 多発・5R 住之江ファイ1.1x圧倒・11R/12R予選特別A戦で1号艇A1 1.0x大本命）
- 尼崎 12R: 全 12 skip（1号艇本命1.0-2.0x + 6号艇A1中山 R2 (3.3x)・R5 (5.6x前田)・R9 (8.6x) すべて Day 1 S2基準60-110x未達、強風6m R9でも捲り確信なし）
- 鳴門 12R: 全 12 skip（1号艇A1×4 + 5艇戦R6 + ドリーム戦R12、4号艇A1まくり大本命R9 (1.5x) R10 (1.7x)、3号艇A1まくりR7 (1.7x) R8 (2.2x) で本命凝縮）
- 丸亀 12R: 全 12 skip（4号艇A1まくりR4 (1.4x)・R5 (1.7x竹田当地60.98%)、3号艇A1まくりR6 (1.6x)・R7 (1.6x強風6m)、6号艇A1上野R9 (4.6x) で 60-110x基準未達）
- avg_confidence: 推定 0.30 前後（全 skip）
- **観察**: S1 67% skip → S2a 100% skip → S2b 100% skip。1月12日の構造的問題が明白化。
  直近 1/8〜1/11 開催の前検 6 走分が出走表に揃って凝縮人気が支配的、4-6号艇A1まくり脅威ですら市場完全織込済（単勝1.4-3.3x）で本命系・まくり系全EV<1.0
- **Day 2 全体評価は S2c 終了後 (`/eval-predictions 2026-01-12`) に 1 回実行**

---

#### Day 1 セッション別 (S1 〜 S4) 観察知見（参考、Day 2 から削減推奨だが残す）

| Session | 場 | bets | skip 率 | 主要 bet パターン |
|---|---|---|---|---|
| S1 | 桐生・戸田・江戸川・平和島 | 13 | 73% | 平和島 1-3-2 系の3着候補分散 / 戸田 1-6-X 6号艇A1飛田過小評価 |
| S2 | 多摩川・びわこ・住之江・尼崎 | 3 | 94% | 6号艇A1異常好調 → 60x前後で 6-1-X / 6-3-X / 1-6-X / 3-6-X |
| S3 | 鳴門・丸亀・徳山・下関 | 0 | **100%** | 全 skip（正月選抜 A1 充実 + 異例構図も市場完全織込済） |
| S4 | 若松・福岡・唐津・大村 | 1 | 98% | 福岡 7R `6-1-2` 60.4x（松村A1 全国7.53/直近10走1着4 異常好調 S2 教訓基準） |

#### 確認された定型パターン（強要ではない）

- **本命 1号艇 単勝 1.0-1.5x**: 3連単本命 5-10x は EV<0.5、3着候補分散時のみ 30-50x で EV>1.0
- **1号艇弱・2-3-4号艇A1まくり**: 軸選手の3着組合せに妙味（オッズ 25-40x）
- **三者拮抗 (単勝 2-3x が3艇)**: 人気分散で買い目薄、skip 妥当
- **A1×3-4 充実メンバーの予選特選・準優勝戦・優勝戦**: 1号艇単勝 1.0-1.2x で
  3連単オッズが薄く EV<0.5、原則 skip
- **6号艇A1/A2 の異常好調シグナル**（Day 1 S2/S4 で 4 例、Day 2 S1 戸田 R10 で 1 例採用）:
  - 当地直近 6 走で 1 着 3-5 回 + 単勝 2-12x の過小評価がトリガー
  - 6コース勝率 2-3% を覆すには配当 40-60x 前後が必要
  - パターン: `6-1-X` `6-3-X` `1-6-X` `3-6-X` の捲り or 3着流し
- **異例の外枠 A1/A2 単勝大本命**: 市場が完全織込済で 3連単オッズも凝縮、EV<0.50 で skip 妥当

**EV ボーダー判定**:
- EV ≥ 1.0 → bet 候補
- 0.85 ≤ EV < 1.0 → 微妙（confidence 高ければ bet 検討）
- EV < 0.85 → 原則 skip
- **境界 (EV ≒ 1.0-1.05) で展示欠損下では P 楽観のリスク高、conservative skip 推奨**（S2 教訓）

---

## 今セッションでやること（Day 2 S2c = 5 場 60 races + Day 2 全体評価）

S1 (桐生・戸田)、S2a (江戸川・多摩川・浜名湖・津)、S2b (住之江・尼崎・鳴門・丸亀) は完了済み。
次セッションでは S2c として **宮島・徳山・下関・若松・芦屋 5 場 = 60 races** を処理する。

**S2c 残り 5 場**: 宮島(17)・徳山(18)・下関(19)・若松(20)・芦屋(21)

レースカード + 直前情報は **既に全 180 race cards で取得済み**（`artifacts/race_cards/2026-01-12/`）。
S2c セッションでは Step 1 (build/fetch) を **スキップ** して直接 Step 2 から開始する。

### 1. 既存 race cards の確認（建構済み）

```bash
ls artifacts/race_cards/2026-01-12/*.md | wc -l   # 181 (180 + index.md)
ls artifacts/predictions/2026-01-12/*.json | grep -v _pre | grep -v index | wc -l   # 120 (S1+S2a+S2b 完了分)
```

181, 120 を確認すれば既に prep + S1+S2a+S2b 完了済み。

### 2. /predict を S2c 5 場に対して実行

開催場 5 を順次実行:

```
/predict 2026-01-12 宮島
/predict 2026-01-12 徳山
/predict 2026-01-12 下関
/predict 2026-01-12 若松
/predict 2026-01-12 芦屋
```

各 `/predict` で 12 races の予想 JSON を `artifacts/predictions/2026-01-12/` に書き出す。

**ペース配分**:
- 1 場 12 races を 1 ターンずつ。Read 全行 + 短い分析 + Write
- bet 候補のみ詳細評価で 1-2 分かかる
- skip は数十秒で判定 + JSON 書き

**context 逼迫時の判断**:
- S2a/S2b 実績: 各 4 場 48 races を 1 セッションで完走（両方とも全 skip）
- S2c は 5 場 60 races でやや量多いが、本日中に完走可能
- 末尾で `build_predictions_index.py` + `/eval-predictions 2026-01-12` 実行 + commit

### 3. 予想完了レース数の確認

S2c セッション末:

```bash
ls artifacts/predictions/2026-01-12/*.json | grep -v _pre | grep -v index | wc -l
# S2c 完了時 (Day 2 全体完了) は 180 (S1 24 + S2a 48 + S2b 48 + S2c 60)
```

### 4. index 再生成 + Day 2 全体評価

```bash
py -3.12 ml/src/scripts/build_predictions_index.py 2026-01-12
# 期待: total=180 valid=180 bet=? skip=? invalid=0
```

S2c (宮島・徳山・下関・若松・芦屋) 完了時に `/eval-predictions 2026-01-12` を実行する。

### 5. S2c commit & push

```bash
git add artifacts/predictions/2026-01-12/17_*.json artifacts/predictions/2026-01-12/18_*.json artifacts/predictions/2026-01-12/19_*.json artifacts/predictions/2026-01-12/20_*.json artifacts/predictions/2026-01-12/21_*.json artifacts/predictions/2026-01-12/index.json artifacts/eval/2026-01-12.json
git commit -m "feat(llm-predict): P4-β Day 2 完了 - 2026-01-12 全 180 races 評価"
git push origin main
```

S2c コミット後、本ファイル（NEXT_SESSION_PROMPT_P4B.md）を Day 3 用に更新。

### 6. ユーザー確認事項（Day 2 全体完了時 = S2c 後）

Day 2 完了後（S2c 終了 + `/eval-predictions 2026-01-12` 実行後）に確認:

1. **Day 1+2 累積 ROI のトレンド**: 撤退ライン（通算 < -15% & 月次 < -10% × 3ヶ月 & CI上限 < +5%）
   からの距離。Day 2 単独 ROI が極端に悪い (例 -50% 以下) かつ Day 1 ROI と乖離が大きい場合
   は早期撤退を検討
2. **bet 数のペース確認**: Day 1 = 17 bets。Day 2 で 50-100 bets 想定だが、
   S2a 全 skip の影響で大幅下振れの可能性。出ない場合は **prompt が保守すぎる構造的問題**を疑う
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
- ❌ Day 2 累積 bet 数が極端に少ない (8) ため、S2c 後の `/eval-predictions` は意味あるが、**Day 2 単独 ROI が極端な値（例 -100% や +500%）になっても 8 bets では確信度極低、Day 3 へ移行**

### 運用
- ❌ 実運用購入禁止 — dry-run + 評価のみ
- ❌ Anthropic API 不使用 — Max プラン内 Claude Code 対話セッションで完結
- ✅ Day 2 全体完了時のみ `/eval-predictions` 自動実行
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

**2026-01-12 開催場 (15 場)**:
01 桐生 ✅ S1 / 02 戸田 ✅ S1 /
03 江戸川 ✅ S2a / 05 多摩川 ✅ S2a / 06 浜名湖 ✅ S2a / 09 津 ✅ S2a /
12 住之江 ✅ S2b / 13 尼崎 ✅ S2b / 14 鳴門 ✅ S2b / 15 丸亀 ✅ S2b /
**17 宮島 / 18 徳山 / 19 下関 / 20 若松 / 21 芦屋 (S2c の 5 場 = このセッション)**

---

## 想定タスク量（S2c）

**S2c = 5 場 / 60 races / 1.5〜2 時間程度**:
- 各 race ~30 秒〜2 分（読み + 分析 + JSON 書き）
- S2a/S2b 連続全 skip 実績から判断すると S2c も skip 多めの可能性が高い

**Day 2 全体評価は S2c 終了後にのみ** `/eval-predictions 2026-01-12` で実行。

---

## 参考資料

- 計画書: [NEXT_PHASE_P4B_PLAN.md](NEXT_PHASE_P4B_PLAN.md)
- P4-α 履歴: [NEXT_SESSION_PROMPT_P4.md](NEXT_SESSION_PROMPT_P4.md)（Day 1〜11 詳細）
- 分析スクリプト: `artifacts/analysis_p4a.py` / `analysis_p4a_interactions.py` / `analysis_p4a_samplesize.py`
- 設計書: [LLM_PREDICT_DESIGN.md](LLM_PREDICT_DESIGN.md)
- B-3 撤退時の代替: [NEXT_SESSION_PROMPT.md](NEXT_SESSION_PROMPT.md)
- Day 1 結果: `artifacts/eval/2026-01-05.json`（17 bets / 1 hit / ROI +88.2%）
- Day 2 S1+S2a+S2b 部分 index: `artifacts/predictions/2026-01-12/index.json`（120 races / 8 bets, S2c で 180 races へ延伸）
