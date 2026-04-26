---
description: race card に直前情報を追記して Claude が予想 JSON を出力する (P2)
argument-hint: <YYYY-MM-DD> [会場] [R番号]
---

# /predict — Claude による競艇予想

引数: `$ARGUMENTS`

例:
- `/predict 2025-12-01 桐生 1` — 1 レース予想
- `/predict 2025-12-01 桐生`   — 1 会場 12R
- `/predict 2025-12-01`        — その日の prep 済み全レース
- `/predict 2026-04-27 桐生 5 --mode live` — 当日リアル取得を強制

**用途**: P1 で生成済みのレースカード Markdown に「直前情報 (展示・進入・気象・
オッズ)」を追記し、Claude (あなた) が分析して予想 JSON を書き出す。

**前提**: `/prep-races <日付> <会場>` で race card が生成済みであること
(なければ「先に `/prep-races` を実行してください」と返す)。

**過去日対応**: race_date < today なら自動で `past` モード
(`data/odds/` キャッシュ + K ファイル気象、展示・進入は欠損)。
当日は `live` モード (boatrace.jp スクレイプ)。

---

## 実行手順 (Claude が順守する)

### Step 1: 引数パース

`$ARGUMENTS` を空白で分割:
- `<日付>` (必須、YYYY-MM-DD)
- `<会場>` (任意、漢字 / ひらがな / 数字 / ゼロ埋め ID)
- `<R番号>` (任意、1〜12)
- `--mode live|past|auto` (任意、デフォルト `auto`)

### Step 2: 直前情報の取得 + race card 上書き

CLI を 1 回呼ぶ:

```bash
py -3.12 ml/src/scripts/fetch_pre_race_info.py <引数そのまま>
```

これで:
- 対象 race card MD ファイルの `## ▼ 直前情報 (...)` プレースホルダが
  実データセクションに置換される
- `artifacts/predictions/<日付>/<場ID>_<R>_pre.json` に直前情報の生データが
  デバッグ用に書かれる

CLI 出力で `[fetch-pre] OK NN(場名)_RR ...` が出ていれば成功。

### Step 3: 各レースの予想 JSON を Claude (あなた) が書く

Step 2 で更新された各 race card を順に処理する。1 レース 1 ターンを目安に:

1. **Read** で `artifacts/race_cards/<日付>/<場ID>_<R>.md` を開く
   (P1 出走表 + Step 2 で追記された直前情報セクションを読む)

2. 自分自身 (Claude) で以下を分析する:
   - **1 号艇の地力**: 全国/当地勝率、級別、平均 ST、モーター 2 連率、直近成績
   - **2 号艇の差し / まくり余地**: ST 速度、当地相性
   - **3〜6 号艇に高評価選手がいないか**: 地元 A1 / 高勝率
   - **場特性 + 気象**: 1 コース勝率の場差、強風時の捲り傾向、波高による荒れ
   - **オッズ妙味**: 自分の評価する組合せのオッズが「人気以上に過小評価」か
   - **過去日 (`mode: past`) の場合**: 展示・進入が無い前提で、出走表 + 場特性 +
     オッズだけから判断 (限定情報下の参考分析)

3. 以下の JSON スキーマで `artifacts/predictions/<日付>/<場ID>_<R>.json` に
   **Write** する:

   ```json
   {
     "race_id": "2025-12-01_01_01",
     "predicted_at": "2025-12-01T15:00:00+09:00",
     "model": "claude-opus-4-7",
     "analysis": "本選択の根拠を 2〜4 行で。出走表のどの数字を重視したか、
                  なぜ他の組合せでなくこの買い目か。",
     "primary_axis": [1, 4],
     "verdict": "bet",
     "skip_reason": null,
     "bets": [
       {
         "trifecta": "1-4-3",
         "stake": 100,
         "current_odds": 12.5,
         "expected_prob": 0.10,
         "ev": 1.25,
         "confidence": 0.6
       }
     ]
   }
   ```

   **必須事項**:
   - `race_id` 形式: `YYYY-MM-DD_NN_RR` (例 `2025-12-01_01_01`)
   - `model`: 自分の正式モデル ID (`claude-opus-4-7` 等)
   - `predicted_at`: ISO8601 (タイムゾーン付き、JST 推奨)
   - `verdict: "bet"` の場合 `bets` は 1〜5 件、`skip_reason` は null
   - `verdict: "skip"` の場合 `bets` は空、`skip_reason` を必ず書く
     (例: "1〜2 号艇とも信頼度低くオッズ妙味なし")
   - `primary_axis` は 1〜2 個 (本線の軸艇)
   - `expected_prob × current_odds ≒ ev` を意識する (厳密一致は不要)
   - `confidence` は自由値 0.0〜1.0 (P3 で confidence vs ROI 相関を集計する)

   **判断指針**:
   - 初期は **ガードレールゼロ**。`verdict: "skip"` の自由度を保つ
   - 強気な見送り (skip) も歓迎。後付けフィルタ追加を防ぐため
   - 過去日のため不確実性が高い場合は `confidence` を低めに、`skip_reason` に
     "過去日ドライランで情報限定" と明記して skip しても良い

4. 1 レースが終わったら次のレースへ。`<会場> <R>` 指定なら 1 件で終わり。
   `<会場>` のみ指定なら 12 件。日付のみなら全 race card を処理。

### Step 4: index.json を生成

全レース処理後、最後に:

```bash
py -3.12 ml/src/scripts/build_predictions_index.py <日付>
```

これで:
- `artifacts/predictions/<日付>/index.json` が生成される
- スキーマ違反 (Claude の出力ミス) は CLI 出力の `invalid files:` に列挙される
- 違反があれば該当ファイルを Read してミスを修正、再 Write してから再実行

### Step 5: ユーザーへの報告

- 処理レース数、bet / skip 内訳
- 注目した買い目 (高 confidence なもの 2〜3 件)
- スキーマ違反があれば修正済みかどうか
- 次のステップ (P3 `/eval-predictions` で実績突合可能) を案内

---

## 注意事項

- **既存モデル (LightGBM trainer/predictor/engine) には触らない**
- **既存 collector のコードを書き換えない** (呼び出すだけ)
- **過去日では展示・進入が欠損**するのは正常動作。"判断材料が足りない" 旨を
  `analysis` に書きつつ、出走表だけで予想するか skip するかを Claude が判断
- スキーマ違反が連続 3 レースで発生した場合は実装に問題あり。
  ユーザーに報告して停止
- 1 レース処理に 2 ターン以上かかる場合 (race card が大きすぎる等) も
  ユーザーに報告

---

## 実装の場所 (参考)

- CLI 1: `ml/src/scripts/fetch_pre_race_info.py` (直前情報取得 + race card 上書き)
- CLI 2: `ml/src/scripts/build_predictions_index.py` (index.json 集約)
- ロジック: `ml/src/predict_llm/`
  - `pre_race_fetcher.py` — 直前情報取得 (live: boatrace.jp / past: cache + K)
  - `prediction_schema.py` — 予想 JSON のバリデーション (dataclass)
- 出力先:
  - `artifacts/race_cards/<日付>/<場ID>_<R>.md` (上書き)
  - `artifacts/predictions/<日付>/<場ID>_<R>.json` (Claude が Write)
  - `artifacts/predictions/<日付>/<場ID>_<R>_pre.json` (デバッグ用、CLI が Write)
  - `artifacts/predictions/<日付>/index.json` (CLI が集約)

詳細: `LLM_PREDICT_DESIGN.md` §3.2
