# P4-β 次セッション用プロンプト（コピペ用）

**最終更新**: 2026-04-27（Day 2 S1 = 桐生・戸田 完了 / 24 races / 8 bets / S2 残り 13 場 156 races）
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
| 2 | **2026-01-12** | 15 | 🟡 S1 完了 / S2 残り | 24/180 | 8 | — | — | — | **このセッションで S2 (13 場 156 races) + 評価を実行** |

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
- **評価は Day 2 全体完了時 (S2 終了後) に `/eval-predictions 2026-01-12` を 1 回実行**

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

## 今セッションでやること（Day 2 S2 = 残り 13 場 156 races + Day 2 全体評価）

S1 で桐生・戸田は完了済み。次セッションでは S2 として残り **13 場 156 races** を処理する。

**残り 13 場**: 江戸川・多摩川・浜名湖・津・住之江・尼崎・鳴門・丸亀・宮島・徳山・下関・若松・芦屋

レースカード + 直前情報は **既に全 180 race cards で取得済み**（`artifacts/race_cards/2026-01-12/`）。
S2 セッションでは Step 1 (build/fetch) を **スキップ** して直接 Step 2 から開始する。

### 1. 既存 race cards の確認（建構済み）

```bash
ls artifacts/race_cards/2026-01-12/*.md | wc -l   # 181 (180 + index.md)
ls artifacts/predictions/2026-01-12/*.json | grep -v _pre | grep -v index | wc -l   # 24 (S1 完了分)
```

181, 24 を確認すれば既に prep + S1 完了済み。

### 2. /predict を残り 13 場に対して実行

開催場 13 を順次実行:

```
/predict 2026-01-12 江戸川
/predict 2026-01-12 多摩川
/predict 2026-01-12 浜名湖
/predict 2026-01-12 津
/predict 2026-01-12 住之江
/predict 2026-01-12 尼崎
/predict 2026-01-12 鳴門
/predict 2026-01-12 丸亀
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
- Day 1 セッションは 4 場 = 48 races を 1 セッションで完走できた
- S1 (桐生・戸田 = 24 races) は context 半分使って完走。残り 13 場 156 races は 1 セッションでは厳しい
- **推奨**: S2 を 4 場ずつ (S2a/S2b/S2c) で分割。各セッション 48 races
  - S2a = 江戸川・多摩川・浜名湖・津 (4 場 / 48 races)
  - S2b = 住之江・尼崎・鳴門・丸亀 (4 場 / 48 races)
  - S2c = 宮島・徳山・下関・若松・芦屋 (5 場 / 60 races)
- **代替**: 6 場 6 場 1 場で 3 セッション分割 (S2a/S2b/S2c)
- 各 S2x 完了時に `build_predictions_index.py` で部分 index 作成 + commit

### 3. 予想完了レース数の確認

各 S2x セッション末 + Day 2 全体完了時:

```bash
ls artifacts/predictions/2026-01-12/*.json | grep -v _pre | grep -v index | wc -l
# Day 2 全体完了時は 180
```

### 4. index 再生成 + Day 2 全体評価実行（**S2 全部完了後のみ**）

```bash
py -3.12 ml/src/scripts/build_predictions_index.py 2026-01-12
py -3.12 ml/src/scripts/evaluate_predictions.py 2026-01-12
```

`artifacts/eval/2026-01-12.json` が出力されたら Day 2 完了。

### 5. Day 2 評価結果のコミット & push

```bash
git add artifacts/race_cards/2026-01-12/ artifacts/predictions/2026-01-12/ artifacts/eval/2026-01-12.json
git commit -m "feat(llm-predict): P4-β Day 2 完了 - 2026-01-12 全 15 場 races 評価済"
git push origin main
```

その後、本ファイル（NEXT_SESSION_PROMPT_P4B.md）を Day 3 用に更新。
**Day 3 の日付候補**: 2026-01-20 (1月3週目) または 2026-01-26 (1月4週目)。

### 6. ユーザー確認事項（Day 2 完了時）

Day 2 完了後、以下をユーザーに確認:

1. **Day 1+2 累積 ROI のトレンド**: 撤退ライン（通算 < -15% & 月次 < -10% × 3ヶ月 & CI上限 < +5%）
   からの距離。Day 2 単独 ROI が極端に悪い (例 -50% 以下) かつ Day 1 ROI と乖離が大きい場合
   は早期撤退を検討
2. **bet 数のペース確認**: Day 1 = 17 bets。Day 2 で 50-100 bets 程度を想定。
   出ない場合は **prompt が保守すぎる構造的問題**を疑う
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
- ❌ S2 完了前に部分評価実行禁止（Day 2 全体評価のみ意味あり）

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
01 桐生 ✅ S1 完了 / 02 戸田 ✅ S1 完了 / 03 江戸川 / 05 多摩川 / 06 浜名湖 / 09 津 /
12 住之江 / 13 尼崎 / 14 鳴門 / 15 丸亀 / 17 宮島 / 18 徳山 / 19 下関 / 20 若松 / 21 芦屋

---

## 想定タスク量（S2 残り）

S1 (桐生・戸田 = 24 races) で context の半分以上を消費した。
S2 = 156 races は 1 セッションでは無理、推奨 3 セッション分割（S2a/S2b/S2c）。

**1 セッション = 4-5 場 / 48-60 races / 1.5-2 時間程度**:
- 各 race ~30 秒〜2 分（読み + 分析 + JSON 書き）
- bet 候補のみ詳細評価で 1-2 分かかる

**S2 完了時 (Day 2 全 180 races 完了時)** → `/eval-predictions 2026-01-12` で評価。

---

## 参考資料

- 計画書: [NEXT_PHASE_P4B_PLAN.md](NEXT_PHASE_P4B_PLAN.md)
- P4-α 履歴: [NEXT_SESSION_PROMPT_P4.md](NEXT_SESSION_PROMPT_P4.md)（Day 1〜11 詳細）
- 分析スクリプト: `artifacts/analysis_p4a.py` / `analysis_p4a_interactions.py` / `analysis_p4a_samplesize.py`
- 設計書: [LLM_PREDICT_DESIGN.md](LLM_PREDICT_DESIGN.md)
- B-3 撤退時の代替: [NEXT_SESSION_PROMPT.md](NEXT_SESSION_PROMPT.md)
- Day 1 結果: `artifacts/eval/2026-01-05.json`（17 bets / 1 hit / ROI +88.2%）
- Day 2 S1 部分 index: `artifacts/predictions/2026-01-12/index.json`（24 races / 8 bets, S2 で延伸）
