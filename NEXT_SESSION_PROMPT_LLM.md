> # 🛑 凍結済み (2026-04-28、Q-B 合意 / (P-v) ハイブリッド採用)
>
> 本ファイルは凍結時点の参照記録として保持されている。**新規着手は不可**。
>
> 全 6 系統 (B-1 / B-3 win / 拡張 A / P-v condition / P4-α LLM / Model-loop) で採用基準未達。
> 後続作業は無し。詳細は [CLAUDE.md](CLAUDE.md)「現行の運用方針」冒頭参照。
>
> 手動でレース予想したくなった時は CLAUDE.md「手動レース予想の手順 (P-v 凍結後)」へ。

---

# 次セッション用プロンプト — Claude Code 競艇予想システム P1（基盤実装）

以下を次セッションの最初のユーザープロンプトとして貼り付けてください。

---

## プロンプト本文

boatrace プロジェクトの新フェーズ「Claude Code 競艇予想システム」の **P1 基盤実装** に着手してほしい。
これは **2026-04-26 に全 ML 改善ループ（フェーズ 3 / 6 / B-1）が撤退状態**となったあと、
方針転換として「判断アルゴリズムごと Claude（LLM）に置き換える」新方針。
**Anthropic API は使わず、Max プラン内（Claude Code 対話セッション）で完結する設計**。

作業開始前に必ず以下を読むこと:

- `LLM_PREDICT_DESIGN.md`（**本フェーズの設計書**、スキル全体像 / レースカード仕様 / 実装フェーズ P1〜P5）
- `CLAUDE.md`「現在の仕様」「現行の運用方針」（全フェーズ撤退状態、既存資産の構造）
- `ml/src/collector/program_downloader.py`（流用ベース、出走表 DL）
- `ml/src/collector/history_downloader.py`（流用ベース、K ファイル DL）
- `ml/src/features/stadium_features.py`（場特性、レースカードに埋め込む）

### これまでの経緯（要約）

| フェーズ | 内容 | 結果 |
|---|---|---|
| 3 `/inner-loop` | 購入フィルタ探索 | out-of-sample 黒字化不能、凍結 |
| 6 `/model-loop` | モデル構造改善 | 完全撤退（採用基準達成 0） |
| 7 (B-1) | 3 連単市場効率分析 | 完全撤退（控除率 25% を破れず） |
| B-3 | 単勝市場効率分析 | 別セッションで進行中（着手予定） |
| **LLM 予想**（本タスク）| **Claude が毎レース予想する** | **P1 基盤実装着手** |

### LLM 予想方針を選んだ理由

- 既存 ML 系（LightGBM）は seed ノイズ床に埋もれて +10% 達成不能
- T16 Perfect-Oracle で「strategy 上限は +29,186%」と判明、strategy 自体に天井はない
- 「特徴量を変えても LightGBM の判断アルゴリズムでは突破できない」と確定
- → **判断器ごと LLM に置き換える** ことで、現行モデル系統の限界を回避

### P1 で行うこと（最小スコープ）

`LLM_PREDICT_DESIGN.md` §8「P1 のスコープ」に従い、
**`/prep-races` スキル + レースカード生成基盤**を実装する。

#### 着手前合意ポイント（実装前にユーザー確認）

以下の設計判断について合意を取ってから着手する:

1. **Python パッケージ構成**: `ml/src/predict_llm/` という新規ディレクトリを作る
   - `stadium_resolver.py`（場名⇔ID 解決）
   - `history_summarizer.py`（直近 N 走の集計）
   - `race_card_builder.py`（Markdown 生成）
   - これでよいか? 既存 `model/` と分離する設計
2. **`/prep-races` の引数仕様**: `LLM_PREDICT_DESIGN.md` §3.1 通り:
   ```
   /prep-races <YYYY-MM-DD> <会場1> [会場2] [会場3] ...
   ```
   会場は **日本語名 / ID（数字 1〜24）/ ゼロ埋め ID（"01"〜"24"）** を受け付ける
3. **レースカードの形式・サイズ**: `LLM_PREDICT_DESIGN.md` §4 Markdown 形式、1 レース ~3〜5 KB
4. **出力先**: `artifacts/race_cards/<YYYY-MM-DD>/<場ID>_<R>.md`、
   `artifacts/race_cards/<YYYY-MM-DD>/index.md`（一覧）
5. **直近 N 走の N**:
   - 全国直近 = 10 走
   - 当地直近 = 6 走
   - これでよいか?
6. **過去日付対応**: 過去日付（例: 2025-12-01）も受け付ける（バックテスト・ドライラン用）。
   その場合 history は既存キャッシュを使う、program は未取得なら DL を試みる
7. **動作確認の対象**:
   - `/prep-races 2026-04-27 桐生` で 12 レース分の MD 生成成功を確認
   - 過去日 `/prep-races 2025-12-01 桐生` でも生成成功を確認
8. **P1 の打ち切り条件**:
   - program / history のキャッシュから情報を抽出できない（スキーマ変更等）→ 設計見直し
   - 1 レース MD のサイズが 10 KB 超になる → フォーマット見直し

これらが合意できたら P1 を実装する。

#### P1 の終了条件

- `ml/src/predict_llm/{stadium_resolver,history_summarizer,race_card_builder}.py` 実装完了
- `ml/src/scripts/build_race_cards.py` CLI 実装完了
- `.claude/commands/prep-races.md` スキル定義完了
- `/prep-races 2026-04-27 桐生` で `artifacts/race_cards/2026-04-27/01_*.md` × 12 ファイル + `index.md` が生成される
- `/prep-races 2025-12-01 桐生 平和島` で複数会場対応も確認
- `LLM_PREDICT_DESIGN.md` の §4 仕様を満たす Markdown が出力されている

### 厳守事項

- ❌ **Anthropic API（API キー）を使用しない**（Max プラン内完結）
- ❌ 既存モデル（`trainer.py` / `predictor.py` / `engine.py`）は**触らない**
- ❌ P1 完了前に P2（`/predict`）に手を付けない
- ❌ 着手前合意ポイント（上記 1〜8）を**スキップしない**
- ❌ 既存 `ml/src/collector/` `ml/src/features/` のコードを書き換えない（呼び出すだけ）
- ❌ 動作確認なしに完了報告しない（実際に MD を出力して中身を Read で確認）
- ✅ 過去日付（バックテスト用）対応は P1 から組み込む

### 成果物（P1 完了時）

1. `ml/src/predict_llm/__init__.py`
2. `ml/src/predict_llm/stadium_resolver.py`（場名⇔ID 解決ヘルパ）
3. `ml/src/predict_llm/history_summarizer.py`（直近 N 走の集計）
4. `ml/src/predict_llm/race_card_builder.py`（Markdown 生成）
5. `ml/src/scripts/build_race_cards.py`（CLI エントリポイント）
6. `.claude/commands/prep-races.md`（スキル定義）
7. `artifacts/race_cards/2026-04-27/`（動作確認ファイル群、桐生 12R 分 + index.md）
8. `artifacts/race_cards/2025-12-01/`（過去日付動作確認、複数会場）

### 実行環境

- Python 3.12（`py -3.12`）
- ローカル（Windows）、DB 接続不要
- 必要キャッシュ:
  - `data/program/` — 出走表（B ファイル、未取得分は DL）
  - `data/history/` — 過去成績（K ファイル、揃い済み）
- 想定実行時間: P1 全体で 2〜4 時間程度

### 参照すべきドキュメント

- [LLM_PREDICT_DESIGN.md](LLM_PREDICT_DESIGN.md) — **本フェーズの設計書（必読）**
- [CLAUDE.md](CLAUDE.md) — 「現行の運用方針」「現在の仕様」
- [DESIGN.md](DESIGN.md) — 既存 ML パイプラインの設計
- [BET_RULE_REVIEW_202509_202512.md](BET_RULE_REVIEW_202509_202512.md) — 実運用再開条件
- [ml/src/collector/program_downloader.py](ml/src/collector/program_downloader.py) — 出走表 DL（流用）
- [ml/src/collector/history_downloader.py](ml/src/collector/history_downloader.py) — K ファイル DL（流用）
- [ml/src/features/stadium_features.py](ml/src/features/stadium_features.py) — 場特性（流用）
- [ml/src/features/feature_builder.py](ml/src/features/feature_builder.py) — 既存特徴量ロジック（参照のみ）

### 次フェーズ（P2 以降、本セッションでは扱わない）

- **P2**: `/predict` スキル — 直前情報追加 + Claude が予想 JSON 出力
- **P3**: `/eval-predictions` スキル — 予想 vs 実績の突合
- **P4**: 複数会場対応の運用検証
- **P5**: `/schedule` 連携で夜間自動 prep

P1 完了後、ユーザーに動作報告し、P2 着手の合意を取る。

以上。**着手前合意ポイント 1〜8 をユーザー合意してから実装に入ってほしい**。
