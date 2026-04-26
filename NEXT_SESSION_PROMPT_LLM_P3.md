# 次セッション用プロンプト — Claude Code 競艇予想システム P3（`/eval-predictions` スキル）

以下を次セッションの最初のユーザープロンプトとして貼り付けてください。

---

## プロンプト本文

boatrace プロジェクトの新フェーズ「Claude Code 競艇予想システム」の **P3 = `/eval-predictions` スキル実装** に着手してほしい。

これは **2026-04-26 に P1 + P2 完了** した状態からの続き。
P2 で出力した予想 JSON（`artifacts/predictions/<日付>/<場ID>_<R>.json`）を、
**実際のレース結果（K ファイル + 過去オッズキャッシュ）と突合し ROI を算出する**スキルを作る。
**Anthropic API は使わず、Max プラン内（Claude Code 対話セッション）で完結する設計**。

作業開始前に必ず以下を読むこと:

- `LLM_PREDICT_DESIGN.md`（**本フェーズの設計書**、特に §3.3「`/eval-predictions` 仕様」 / §8「P1/P2 完了メモ」 / §11「評価指標」）
- `CLAUDE.md`「現在の仕様」「現行の運用方針」（全 ML 改善ループ撤退状態 + LLM フェーズ P1/P2 完了済み）
- `ml/src/predict_llm/prediction_schema.py`（P2 で実装した予想 JSON スキーマ）
- `ml/src/predict_llm/pre_race_fetcher.py`（P2 の直前情報取得、K ファイル気象抽出ロジックは流用候補）
- `ml/src/collector/odds_downloader.py`（過去 3 連単オッズキャッシュの読み込みパターン）
- `ml/src/collector/history_downloader.py`（K ファイルの parse_result_file、着順・払戻情報）
- `ml/src/backtest/engine.py`（既存 ROI 集計ロジック、流用検討）
- `artifacts/predictions/2025-12-01/index.json`（P2 で生成した動作確認サンプル）
- `artifacts/predictions/2025-12-01/01_01.json`（個別予想 JSON の実物）

### これまでの経緯（要約）

| フェーズ | 内容 | 結果 |
|---|---|---|
| 3 `/inner-loop` | 購入フィルタ探索 | out-of-sample 黒字化不能、凍結 |
| 6 `/model-loop` | モデル構造改善 | 完全撤退（採用基準達成 0） |
| 7 (B-1) | 3 連単市場効率分析 | 完全撤退（控除率 25% を破れず） |
| B-3 | 単勝市場効率分析 | 別セッションで進行中 |
| LLM P1 | `/prep-races` 基盤 | **2026-04-26 完了** |
| LLM P2 | `/predict` スキル | **2026-04-26 完了**（2025-12-01 桐生 12R 動作確認済） |
| **LLM P3**（本タスク）| **`/eval-predictions` スキル** | **着手** |

### P2 完了状況（前提）

- `ml/src/predict_llm/pre_race_fetcher.py` 実装済（直前情報取得：live + past 両モード）
- `ml/src/predict_llm/prediction_schema.py` 実装済（予想 JSON dataclass + validate）
- `ml/src/scripts/fetch_pre_race_info.py` 実装済（CLI、race card MD 上書き）
- `ml/src/scripts/build_predictions_index.py` 実装済（index.json 集約 + スキーマ検証）
- `.claude/commands/predict.md` スキル登録済
- 動作確認サンプル: `artifacts/predictions/2025-12-01/` 配下に
  - `01_01.json` 〜 `01_12.json`（12 件、全部 verdict=bet）
  - `01_01_pre.json` 〜 `01_12_pre.json`（直前情報の生データ）
  - `index.json`（集約結果、total=12 valid=12 bet=12）
- **設計時の pydantic は dataclass + 自前 validate に変更**（依存追加回避）

P3 はこの予想 JSON 群を実績と突合する。

### P3 で行うこと（最小スコープ）

`LLM_PREDICT_DESIGN.md` §3.3「`/eval-predictions` 仕様」に従い、以下を実装する:

1. **`evaluate_predictions.py`**: 予想 JSON × 実績（K ファイル着順 + 払戻金）で ROI 集計
2. **`.claude/commands/eval-predictions.md`**: スキル定義

#### 着手前合意ポイント（実装前にユーザー確認）

以下の設計判断について合意を取ってから着手する:

1. **実績データの取得方法**:
   - **着順**: K ファイルから `finish_position` を引く（既存 `history_downloader.parse_result_file`）。
     ただし K ファイルには「3 連単の組合せ」しか入らず「払戻金」が無いことに注意
   - **払戻金（オッズ）**: 過去日キャッシュ `data/odds/odds_YYYYMM.parquet` から該当
     `race_id` の `combination` のオッズを読む。**オッズ × 100 円 = 払戻金**で代用
   - **当日（K ファイルがまだ無い）**: boatrace.jp の `raceresult` ページを使う
     （既存 `openapi_client.fetch_race_result_full` がトリフェクタ組合せ + 払戻金を返す）
   - **推奨**: 過去日 = K + parquet キャッシュ、当日 = `fetch_race_result_full`

2. **`/eval-predictions` の引数仕様（§3.3 通り）**:
   ```
   /eval-predictions <YYYY-MM-DD>                  # その日の予想 JSON 全部
   /eval-predictions <YYYY-MM-DD> <会場>            # 1 会場
   /eval-predictions --from <date> --to <date>     # 期間累積（後フェーズ /eval-summary）
   ```
   **推奨**: 単日 + 単会場までを P3、累積は P3.5 として後送り。

3. **的中判定ロジック**:
   - 各 bet の `trifecta` 文字列（"1-4-3" 等）と実績着順から計算した文字列を一致比較
   - 的中なら `payout = current_odds × stake`、外れなら `payout = 0`
   - **推奨**: シンプルな文字列一致だけで OK。3 連単はソート不要

4. **集計指標**:
   - 必須: 的中率（per bet）、ROI（payout_total / stake_total - 1）、見送り率
   - 任意: confidence 帯別 ROI、primary_axis 別ヒット率、verdict=skip の場合の "もし bet していたら" の参考 ROI（過大学習防止のため出すかどうか議論）
   - **推奨**: 必須指標 + confidence 帯別だけ。skip の if-bet 集計は P3.5 以降

5. **出力形式**:
   - サマリー JSON: `artifacts/eval/<日付>.json`（race_id ごと + 全体集計）
   - ターミナル表示: 簡潔なテーブル（場別・confidence 帯別・全体）
   - **推奨**: 設計書 §3.3 通り

6. **会場休場 / レース欠番への対応**:
   - K ファイルに該当レースが無い場合は予想を「実績取得不能」マークして集計から除外
   - **推奨**: skip 扱いと区別する（`status: "no_result"`）

7. **既存 backtest/engine.py との関係**:
   - 既存 engine.py は LightGBM 予測 → EV → bet → ROI のフルパイプ
   - P3 は「Claude が事前に書いた bets だけを評価」なので engine.py のフルパイプ不要
   - **推奨**: engine.py の ROI 集計関数（あれば）を流用、なければ独自実装で完結

8. **当日 live モード対応**:
   - 当日締切後、結果が確定したら `raceresult` ページが見える
   - K ファイルは翌朝アップロード
   - **推奨**: 当日は `fetch_race_result_full` を試行、失敗なら "結果未確定" マーク

9. **P3 の打ち切り条件**:
   - K ファイルから的中組合せが取れない → 該当レース skip
   - 過去日 parquet キャッシュにオッズが無い（休場場・欠番）→ 該当レース skip
   - 連続 5 レースで結果取得失敗 → 実装に問題あり、ユーザー報告

これらが合意できたら P3 を実装する。

#### P3 の終了条件

- `ml/src/scripts/evaluate_predictions.py` CLI 実装完了
- `.claude/commands/eval-predictions.md` スキル定義完了
- 動作確認:
  - `/eval-predictions 2025-12-01 桐生` で 12 レース分の集計が出る
  - ROI / 的中率 / 見送り率がターミナル表示される
  - `artifacts/eval/2025-12-01.json` が pydantic 相当のスキーマで出力される
  - 1 件以上の的中 / 不的中が判定として妥当（手計算で検証）
- 累積評価（複数日）は P3.5 以降に持ち越し

### 厳守事項

- ❌ **Anthropic API（API キー）を使用しない**（Max プラン内完結）
- ❌ 既存モデル（`trainer.py` / `predictor.py` / `engine.py`）は**触らない**
  （ROI 集計関数のみ参照可、書き換えない）
- ❌ 既存 `ml/src/collector/` のコードを書き換えない（呼び出すだけ）
- ❌ P1/P2 で実装した `predict_llm/` のモジュールは原則触らない
  （バグ発見時のみ最小修正、その場合はユーザー確認）
- ❌ 着手前合意ポイント（上記 1〜9）を**スキップしない**
- ❌ 動作確認なしに完了報告しない（実際に ROI を算出して中身を Read で確認）
- ✅ 過去日付（バックテスト用）対応は P3 から組み込む
- ✅ 実運用購入には **使わない**（あくまで Claude の予想精度検証フェーズ、設計書 §12）
- ✅ ROI が悪い結果でも **後付けフィルタを足してチューニングしない**
  （フェーズ 3〜6 の教訓）

### 成果物（P3 完了時）

1. `ml/src/scripts/evaluate_predictions.py`（CLI、ROI 集計）
2. `.claude/commands/eval-predictions.md`（スキル定義）
3. `artifacts/eval/2025-12-01.json`（動作確認の集計結果）
4. CLAUDE.md / LLM_PREDICT_DESIGN.md の P3 完了反映
5. （任意）P3.5 用次セッションプロンプト `NEXT_SESSION_PROMPT_LLM_P3_5.md`
   または P4 用 `NEXT_SESSION_PROMPT_LLM_P4.md`

### 実行環境

- Python 3.12（`py -3.12`）
- ローカル（Windows）、DB 接続不要
- 必要キャッシュ:
  - `data/history/` — K ファイル（既存、4/26 まで揃い済み）
  - `data/odds/` — 3 連単実オッズ（過去日突合用、2025-05〜2026-04 揃い済み）
- 想定実行時間: P3 全体で 2〜4 時間程度

### 参照すべきドキュメント

- [LLM_PREDICT_DESIGN.md](LLM_PREDICT_DESIGN.md) — **本フェーズの設計書（必読）**
- [CLAUDE.md](CLAUDE.md) — 「現行の運用方針」「現在の仕様」（LLM フェーズ P1/P2 完了反映済み）
- [.claude/commands/predict.md](.claude/commands/predict.md) — P2 スキル定義（フォーマット参考）
- [ml/src/predict_llm/prediction_schema.py](ml/src/predict_llm/prediction_schema.py) — 予想 JSON のロード
- [ml/src/predict_llm/pre_race_fetcher.py](ml/src/predict_llm/pre_race_fetcher.py) —
  K ファイル気象抽出 / parquet キャッシュ読み込みパターン（流用候補）
- [ml/src/collector/openapi_client.py](ml/src/collector/openapi_client.py) — `fetch_race_result_full` 当日結果取得
- [ml/src/collector/history_downloader.py](ml/src/collector/history_downloader.py) — K ファイル parse_result_file
- [artifacts/predictions/2025-12-01/](artifacts/predictions/2025-12-01/) — P2 動作確認サンプル

### 次フェーズ（P4 以降、本セッションでは扱わない）

- **P3.5**: `/eval-summary` 累積複数日集計
- **P4**: 複数会場対応の運用検証（P1 で前倒し実装済み、P4 は実走運用テスト）
- **P5**: `/schedule` 連携で夜間自動 prep + 朝の自動 eval

P3 完了後、ユーザーに動作報告し、次フェーズ着手の合意を取る。

以上。**着手前合意ポイント 1〜9 をユーザー合意してから実装に入ってほしい**。
