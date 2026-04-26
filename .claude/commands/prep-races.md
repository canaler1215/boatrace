---
description: LLM 予想用レースカードを生成する (P1 基盤)
argument-hint: <YYYY-MM-DD> <会場1> [会場2] ...
---

# /prep-races — LLM 予想用レースカード準備

引数: `$ARGUMENTS`

例:
- `/prep-races 2026-04-27 桐生`
- `/prep-races 2026-04-27 桐生 平和島 住之江`
- `/prep-races 2025-12-01 1 4 12`
- `/prep-races 2026-04-27 蒲郡`

**用途**: 指定日の指定会場について、Claude (LLM) がレース予想する際に
読むレースカード Markdown を一括生成する.
P2 の `/predict` で「直前情報 (展示・オッズ・気象)」を追記する設計.

過去日付も受け付ける (バックテスト・ドライラン用).
B ファイル未取得の場合は DL を試行する. 該当日に該当場が休場の場合は警告のみ.

---

## 実装の場所 (参考)

- CLI: `ml/src/scripts/build_race_cards.py`
- ロジック: `ml/src/predict_llm/`
  - `stadium_resolver.py` — 場名 ⇔ ID 解決
  - `program_parser.py` — 独自 B ファイルパーサ (LLM 用フル情報)
  - `history_summarizer.py` — 直近 N 走集計
  - `race_card_builder.py` — Markdown 生成
- 出力先: `artifacts/race_cards/<YYYY-MM-DD>/`
  - `<場ID>_<R>.md` (例: `01_05.md`)
  - `index.md` (一覧)

---

## 実行手順

1. 引数の日付・会場をそのまま CLI に渡す:

   ```bash
   py -3.12 ml/src/scripts/build_race_cards.py $ARGUMENTS
   ```

2. ターミナル出力から以下を確認:
   - `[prep-races] done: <N> race cards + index.md` が出ていること
   - 警告 (`WARNING: stadium ... is closed`) があれば該当場は休場 (= 出力なし) と報告

3. 出力先の確認:
   ```bash
   ls artifacts/race_cards/<YYYY-MM-DD>/
   ```

4. 件数の整合性チェック:
   - 1 場 = 12R + index.md なので、N 場指定なら `12 * N + 1` ファイルを期待
   - 休場場があれば `12 * (N - 休場数) + 1` ファイル
   - サンプル 1 つを `Read` で開いて、出走表 6 艇 + 直近 10 走表 + 場特性が
     正しく入っていることを確認

5. ユーザーへの報告:
   - 生成したレース数、場ごとの内訳、休場場 (あれば)、出力ディレクトリ

---

## 注意

- **既存 LightGBM モデルには触らない** (P1 はレースカード基盤のみ).
- 過去日付指定 (バックテスト用) で history キャッシュが薄い場合は、
  「直近 N 走」が N 未満になることがある. これは正常動作.
- B ファイル DL は 1 日分 35〜80 KB なので軽量. 失敗時は CLI が WARNING を
  出して exit 1 する. その場合は日付指定が間違っていないか確認すること.

---

## P2 以降との関係 (このスキルでは扱わない)

- `/predict` (P2): このカードに直前情報 (展示・オッズ・気象) を追記して
  Claude が予想 JSON を出力する.
- `/eval-predictions` (P3): 予想 JSON と実績を突合して ROI を算出する.
- 詳細: `LLM_PREDICT_DESIGN.md`
