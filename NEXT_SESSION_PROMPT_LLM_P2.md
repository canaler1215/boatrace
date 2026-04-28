> # 🛑 凍結済み (2026-04-28、Q-B 合意 / (P-v) ハイブリッド採用)
>
> 本ファイルは凍結時点の参照記録として保持されている。**新規着手は不可**。
>
> 全 6 系統 (B-1 / B-3 win / 拡張 A / P-v condition / P4-α LLM / Model-loop) で採用基準未達。
> 後続作業は無し。詳細は [CLAUDE.md](CLAUDE.md)「現行の運用方針」冒頭参照。
>
> 手動でレース予想したくなった時は CLAUDE.md「手動レース予想の手順 (P-v 凍結後)」へ。

---

# 次セッション用プロンプト — Claude Code 競艇予想システム P2（`/predict` スキル）

以下を次セッションの最初のユーザープロンプトとして貼り付けてください。

---

## プロンプト本文

boatrace プロジェクトの新フェーズ「Claude Code 競艇予想システム」の **P2 = `/predict` スキル実装** に着手してほしい。

これは **2026-04-26 に P1 基盤実装が完了** した状態からの続き。
P1 で生成済みのレースカード Markdown に「直前情報（展示・直前オッズ・気象）」を追記し、
**Claude（あなた）が読んで予想 JSON を出力するスキル**を作る。
**Anthropic API は使わず、Max プラン内（Claude Code 対話セッション）で完結する設計**。

作業開始前に必ず以下を読むこと:

- `LLM_PREDICT_DESIGN.md`（**本フェーズの設計書**、特に §3.2「`/predict` 仕様」 / §4「レースカード仕様」 / §8「P1 完了メモ」 / §10「残論点」）
- `CLAUDE.md`「現在の仕様」「現行の運用方針」（全 ML 改善ループ撤退状態 + LLM フェーズ P1 完了済み）
- `ml/src/predict_llm/race_card_builder.py`（P1 で生成した直前情報プレースホルダの形式）
- `ml/src/scripts/build_race_cards.py`（P1 の CLI、引数仕様の参考）
- `.claude/commands/prep-races.md`（P1 のスキル定義、フォーマット参考）
- `ml/src/collector/odds_downloader.py`（既存 3 連単オッズ DL、流用候補）
- `ml/src/collector/openapi_client.py`（直前オッズ API、`fetch_odds` の構造確認）
- `artifacts/race_cards/2025-12-01/01_01.md`（P1 で生成した実物サンプル、直前情報追記前の姿）

### これまでの経緯（要約）

| フェーズ | 内容 | 結果 |
|---|---|---|
| 3 `/inner-loop` | 購入フィルタ探索 | out-of-sample 黒字化不能、凍結 |
| 6 `/model-loop` | モデル構造改善 | 完全撤退（採用基準達成 0） |
| 7 (B-1) | 3 連単市場効率分析 | 完全撤退（控除率 25% を破れず） |
| B-3 | 単勝市場効率分析 | 別セッションで進行中 |
| LLM P1 | `/prep-races` 基盤 | **2026-04-26 完了**（72 ファイル動作確認済） |
| **LLM P2**（本タスク）| **`/predict` スキル** | **着手** |

### P1 完了状況（前提）

- `ml/src/predict_llm/` に 4 モジュール（`stadium_resolver` / `program_parser` /
  `history_summarizer` / `race_card_builder`）実装済
- `ml/src/scripts/build_race_cards.py` CLI 実装済
- `.claude/commands/prep-races.md` スキル登録済
- 動作確認: 4/25 桐生 / 4/27 桐生休場+平和島 / 2025-12-01 桐生+平和島休場+多摩川
- レースカード MD 形式: `# YYYY-MM-DD 場名 R番号` → レース情報 → 出走表 6 艇
  （基本情報 + 全国/当地サマリ + 直近 10 走表 + 当地直近 6 走表）→ 場特性 →
  **`## ▼ 直前情報 (/predict 実行時に追記)`** プレースホルダ

P2 はこのプレースホルダを置き換えて Claude が予想する。

### P2 で行うこと（最小スコープ）

`LLM_PREDICT_DESIGN.md` §3.2「`/predict` 仕様」に従い、以下 3 点を実装する:

1. **`fetch_pre_race_info.py`**: 展示タイム / スタート展示の進入・ST / 直前気象 /
   3 連単直前オッズ / 単勝直前オッズ を取得
2. **`prediction_schema.py`**: pydantic で予想 JSON を定義（race_id / analysis /
   primary_axis / verdict / skip_reason / bets[] スキーマ、§3.2 例参照）
3. **`.claude/commands/predict.md`**: スキル定義（Claude が race card MD を読んで
   分析 → 予想 JSON を `artifacts/predictions/<日付>/<場ID>_<R>.json` に書き出す手順）

#### 着手前合意ポイント（実装前にユーザー確認）

以下の設計判断について合意を取ってから着手する:

1. **直前情報の取得方法**:
   - 既存 `openapi_client.py` の `fetch_odds()`（3 連単）は本番運用前から使用可能か?
   - 展示タイム / 進入 ST / 直前気象を取得する API が既存にあるか? なければ
     `predict_llm/pre_race_fetcher.py` に **boatrace.jp の直前情報ページ
     `https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=...&jcd=...&hd=YYYYMMDD`** を
     スクレイプする最小実装で十分か? requests + BeautifulSoup 想定
   - **推奨**: 既存 `openapi_client.py` を読んで使えるなら使う、不足分のみ
     `predict_llm/pre_race_fetcher.py` に追加（既存 collector は書き換えない）

2. **`/predict` の引数仕様（§3.2 通り）**:
   ```
   /predict <YYYY-MM-DD>                    # その日の prep 済み全レース
   /predict <YYYY-MM-DD> <会場>              # 1 会場 12R
   /predict <YYYY-MM-DD> <会場> <R>          # 単発
   ```
   会場は `/prep-races` と同様 stadium_resolver 経由（漢字 / ひらがな / 数字 / ゼロ埋め）

3. **過去日付対応**:
   - 過去日（バックテスト用）も受け付ける
   - 過去日では「直前情報」が再現困難（boatrace.jp の直前ページは当日限定）
   - **方針案**: 過去日では「3 連単オッズ（既存 `data/odds/` キャッシュ）+ K ファイルからの
     展示タイム・気象」で代用、進入予想は「艇番 = コース」で代用
   - **推奨**: ドライランは過去日でも回るようにする（ROI 検証のため不可欠）

4. **Claude が予想 JSON を書き出す方式**:
   - **方式 A**: スキル中で Claude（あなた）が race card MD を Read → 分析を頭で
     行う → Write で JSON ファイルを書き出す（Python スクリプトは JSON のスキーマ
     検証だけ担当）
   - **方式 B**: スキルが Python スクリプトを起動して Claude に「ここに分析結果を
     貼って」と要求し、それを後処理で JSON 化
   - **推奨は方式 A**（スキル UX が Claude Code らしい、API 呼び出し不要）

5. **見送り条件のガードレール**:
   - 設計書 §10.3「最低限のガードレール（`current_odds < 1.5` で skip 強制 など）は
     `/predict` skill 側で持つ」とある
   - **推奨**: 初期は **ガードレールゼロ**（Claude の判断に完全委任、`verdict: "skip"`
     の自由度を保つ）、悪い結果が見えたら追加

6. **1 レース処理時間の見積もり**:
   - Claude が race card 1 つ（~7 KB）を読んで分析 → JSON を書く ≒ 1 ターン分の
     Tool 使用 = ~10〜30 秒
   - 1 日 12R × 1 場 = ~3〜6 分、12R × 5 場 = ~15〜30 分
   - **方式**: 1 ターン 1 レースで処理。スキル側で「対象レース一覧 → 各レースを
     順次 Read + Write」を生成し、Claude（あなた）がそのリストに沿って動く

7. **JSON 出力先の設計**:
   - `artifacts/predictions/<YYYY-MM-DD>/<場ID>_<R>.json`（個別）
   - `artifacts/predictions/<YYYY-MM-DD>/index.json`（その日の全予想サマリ、
     `/eval-predictions` (P3) で読む用）
   - **推奨**: 個別 JSON は Claude が Write、index.json はスキル末尾で Python が
     ディレクトリスキャンして集約

8. **過去日でドライラン時の skip ロジック**:
   - 過去日では「直前情報が再現できない」可能性 → race card のプレースホルダを
     「（過去日のためデータなし）」に置換するか、3 連単オッズ + K ファイル気象だけ
     入れて Claude に「直前情報なしで予想」させるか
   - **推奨**: 後者。Claude には「過去日ドライラン用、直前情報は限定的」と明記
     したうえで予想させる

9. **P2 の打ち切り条件**:
   - 直前情報取得 API が boatrace.jp 仕様変更で取れない → P2 完了基準を「過去日
     ドライランのみ」に縮退
   - 1 レース予想に Claude が 2 ターン以上必要 → 想定外、設計見直し
   - スキーマ検証で Claude の出力が連続 3 レース壊れる → プロンプト改善

これらが合意できたら P2 を実装する。

#### P2 の終了条件

- `ml/src/predict_llm/pre_race_fetcher.py`（直前情報取得）実装完了
- `ml/src/predict_llm/prediction_schema.py`（pydantic JSON スキーマ）実装完了
- `ml/src/scripts/fetch_pre_race_info.py` CLI 実装完了（race card に直前情報追記）
- `.claude/commands/predict.md` スキル定義完了
- 動作確認:
  - 過去日 1 レース `/predict 2025-12-01 桐生 1` で `artifacts/predictions/2025-12-01/01_01.json`
    が生成され、pydantic スキーマを通る
  - 過去日 1 会場 `/predict 2025-12-01 桐生` で 12 個の JSON + index.json
  - 出力 JSON の `verdict` / `bets` の中身が分析結果として妥当（Claude の分析が
    まったく的外れでないことを目視確認）
- 当日（リアル直前情報あり）動作: ユーザー判断で別途実施（boatrace.jp の直前
  ページが利用可能なタイミングで）

### 厳守事項

- ❌ **Anthropic API（API キー）を使用しない**（Max プラン内完結）
- ❌ 既存モデル（`trainer.py` / `predictor.py` / `engine.py`）は**触らない**
- ❌ 既存 `ml/src/collector/` のコードを書き換えない（呼び出すだけ）。
  足りない分は `predict_llm/pre_race_fetcher.py` に独自実装を追加する
- ❌ P1 で実装した `predict_llm/` の 4 モジュールは原則触らない
  （バグ発見時のみ最小修正、その場合はユーザー確認）
- ❌ 着手前合意ポイント（上記 1〜9）を**スキップしない**
- ❌ 動作確認なしに完了報告しない（実際に予想 JSON を出して中身を Read で確認）
- ✅ 過去日付（バックテスト用）対応は P2 から組み込む
- ✅ 実運用購入には **使わない**（あくまで Claude の予想精度検証フェーズ、設計書 §12）

### 成果物（P2 完了時）

1. `ml/src/predict_llm/pre_race_fetcher.py`（直前情報取得：展示・進入・気象・オッズ）
2. `ml/src/predict_llm/prediction_schema.py`（予想 JSON pydantic 定義）
3. `ml/src/scripts/fetch_pre_race_info.py`（CLI、race card に直前情報追記）
4. `.claude/commands/predict.md`（スキル定義）
5. `artifacts/predictions/2025-12-01/01_*.json`（過去日 1 会場分の動作確認）
6. `artifacts/predictions/2025-12-01/index.json`（その日のサマリ）
7. CLAUDE.md / LLM_PREDICT_DESIGN.md の P2 完了反映
8. P3 用次セッションプロンプト `NEXT_SESSION_PROMPT_LLM_P3.md`

### 実行環境

- Python 3.12（`py -3.12`）
- ローカル（Windows）、DB 接続不要
- 必要キャッシュ:
  - `data/program/` — 出走表（既存、4/27 まで揃い済み）
  - `data/history/` — 過去成績（既存、4/26 まで揃い済み）
  - `data/odds/` — 3 連単実オッズ（過去日ドライラン用、2025-05〜2026-04 揃い済み）
- 想定実行時間: P2 全体で 3〜6 時間程度

### 参照すべきドキュメント

- [LLM_PREDICT_DESIGN.md](LLM_PREDICT_DESIGN.md) — **本フェーズの設計書（必読）**
- [CLAUDE.md](CLAUDE.md) — 「現行の運用方針」「現在の仕様」（LLM フェーズ P1 完了反映済み）
- [.claude/commands/prep-races.md](.claude/commands/prep-races.md) — P1 スキル定義（フォーマット参考）
- [ml/src/predict_llm/race_card_builder.py](ml/src/predict_llm/race_card_builder.py) — レースカードの直前情報プレースホルダの形式
- [ml/src/collector/openapi_client.py](ml/src/collector/openapi_client.py) — 既存オッズ API（流用候補）
- [ml/src/collector/odds_downloader.py](ml/src/collector/odds_downloader.py) — 既存オッズ DL のキャッシュパターン
- [artifacts/race_cards/2025-12-01/01_01.md](artifacts/race_cards/2025-12-01/01_01.md) — P1 で生成した実物（追記前の姿）

### 次フェーズ（P3 以降、本セッションでは扱わない）

- **P3**: `/eval-predictions` スキル — 予想 vs 実績の突合、ROI 算出
- **P4**: 複数会場対応の運用検証（P1 で前倒し実装済み、P4 は実走運用テスト）
- **P5**: `/schedule` 連携で夜間自動 prep

P2 完了後、ユーザーに動作報告し、P3 着手の合意を取る。

以上。**着手前合意ポイント 1〜9 をユーザー合意してから実装に入ってほしい**。
