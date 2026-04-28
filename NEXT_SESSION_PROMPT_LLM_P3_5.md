> # 🛑 凍結済み (2026-04-28、Q-B 合意 / (P-v) ハイブリッド採用)
>
> 本ファイルは凍結時点の参照記録として保持されている。**新規着手は不可**。
>
> 全 6 系統 (B-1 / B-3 win / 拡張 A / P-v condition / P4-α LLM / Model-loop) で採用基準未達。
> 後続作業は無し。詳細は [CLAUDE.md](CLAUDE.md)「現行の運用方針」冒頭参照。
>
> 手動でレース予想したくなった時は CLAUDE.md「手動レース予想の手順 (P-v 凍結後)」へ。

---

boatrace プロジェクトの新フェーズ「Claude Code 競艇予想システム」の **P3.5 = `/eval-summary` スキル実装** に着手してほしい。

これは **2026-04-27 に P3 完了** した状態からの続き。
P3 で出力した日次評価 JSON（`artifacts/eval/<日付>.json` / `<日付>_<場ID>.json`）を、
**期間指定で複数日合算し、月次 ROI トレンド・confidence 相関・場別累積 ROI を集計する**スキルを作る。
**Anthropic API は使わず、Max プラン内（Claude Code 対話セッション）で完結する設計**。

作業開始前に必ず以下を読むこと:

- `LLM_PREDICT_DESIGN.md`（**本フェーズの設計書**、特に §3.3「累積評価」 / §8「P3 完了メモ」 / §11「評価指標」）
- `CLAUDE.md`「現在の仕様」「現行の運用方針」（全 ML 改善ループ撤退状態 + LLM フェーズ P1/P2/P3 完了済み）
- `ml/src/scripts/evaluate_predictions.py`（P3 で実装した日次評価 CLI、出力スキーマと完全に整合させる）
- `.claude/commands/eval-predictions.md`（P3 スキル定義、フォーマット参考）
- `artifacts/eval/2025-12-01_01.json`（P3 動作確認サンプル、入力フォーマット実物）

### これまでの経緯（要約）

| フェーズ | 内容 | 結果 |
|---|---|---|
| 3 `/inner-loop` | 購入フィルタ探索 | out-of-sample 黒字化不能、凍結 |
| 6 `/model-loop` | モデル構造改善 | 完全撤退（採用基準達成 0） |
| 7 (B-1) | 3 連単市場効率分析 | 完全撤退（控除率 25% を破れず） |
| B-3 | 単勝市場効率分析 | 別セッションで進行中 |
| LLM P1 | `/prep-races` 基盤 | **2026-04-26 完了** |
| LLM P2 | `/predict` スキル | **2026-04-26 完了**（2025-12-01 桐生 12R 動作確認済） |
| LLM P3 | `/eval-predictions` スキル | **2026-04-27 完了**（17 bets / 1 hit / ROI -57.6%、手計算検証 pass）|
| **LLM P3.5**（本タスク）| **`/eval-summary` スキル** | **着手** |

### P3 完了状況（前提）

- `ml/src/scripts/evaluate_predictions.py` 実装済（K ファイル + parquet キャッシュ + 当日 raceresult 突合）
- `.claude/commands/eval-predictions.md` スキル登録済
- 動作確認サンプル: `artifacts/eval/2025-12-01.json`（全場、桐生のみ 1 件） /
  `artifacts/eval/2025-12-01_01.json`（桐生フィルタ、12 races / 17 bets / 1 hit / ROI -57.6%）
- 出力 JSON スキーマ確定:
  - top-level: `date`, `stadium_filter`, `stadium_filter_name`, `evaluated_at`, `is_past`, `summary`, `races`, `invalid_predictions`
  - `summary`: `n_races` / `n_settled` / `n_skipped_by_claude` / `n_no_result` /
    `n_bet_races` / `n_hit_races` / `n_bets` / `n_hits` / `total_stake` / `total_payout` /
    `roi` / `hit_rate_per_bet` / `hit_rate_per_race` / `skip_rate` / `avg_confidence` /
    `by_stadium[]` / `by_confidence_band[]`
  - `races[]`: 各レースの `BetEval[]` を保持（`is_hit` / `payout` / `confidence` / `current_odds` / `actual_odds` / `payout_source` / `odds_drift_pct`）

P3.5 はこの日次 JSON 群を期間横断で再集計する。

### P3.5 で行うこと（最小スコープ）

`LLM_PREDICT_DESIGN.md` §3.3「累積評価」に従い、以下を実装する:

1. **`eval_summary.py`**: 期間指定（`--from` / `--to`）で `artifacts/eval/*.json` を読み、累積集計
2. **`.claude/commands/eval-summary.md`**: スキル定義

#### 着手前合意ポイント（実装前にユーザー確認）

以下の設計判断について合意を取ってから着手する:

1. **入力ファイル選別**:
   - `artifacts/eval/YYYY-MM-DD.json`（場フィルタなし）と
     `artifacts/eval/YYYY-MM-DD_NN.json`（場フィルタあり）が混在する
   - **推奨**: 期間内で `<日付>.json`（場フィルタなし）を優先採用、無ければ `<日付>_<場ID>.json` を全部マージ
   - ただし片方だけ存在 / 重複日が混在するとややこしい → P3.5 では `<日付>.json` のみ対象、フィルタ付きは P4 で別途対応
   - **推奨**: シンプルに「期間内の `<日付>.json` を全部読む」とし、不在日は無視（warning）

2. **`/eval-summary` の引数仕様**:
   ```
   /eval-summary --from <YYYY-MM-DD> --to <YYYY-MM-DD>     # 期間指定
   /eval-summary --month <YYYY-MM>                          # 月単位ショートカット
   /eval-summary <YYYY-MM-DD>                                # 単日（P3 と同じ動作で代替可能、利便性のみ）
   ```
   - **推奨**: `--from`/`--to` 必須、`--month` を糖衣構文として追加。単日ショートカットは不要（P3 で済む）

3. **集計指標（必須）**:
   - 期間 ROI（payout / stake - 1）
   - 月次 ROI トレンド（YYYY-MM ごとの ROI / 投資 / 払戻 / hit_rate）
   - 場別 ROI トレンド（cumulative + 月次クロス表）
   - confidence 帯別 ROI（[0.0–0.3, 0.3–0.5, 0.5–0.7, 0.7–1.0]、P3 と同じ境界）
   - 全体 hit_rate_per_bet / hit_rate_per_race / 平均 confidence / 見送り率
   - **推奨**: 上記 5 指標 + 日次 ROI ヒストグラム（min/median/mean/max + 標準偏差）

4. **集計指標（任意）**:
   - bootstrap CI（ROI の 95% 信頼区間下限、N=1000 リサンプル）
   - confidence vs ROI 相関係数（spearman）
   - primary_axis 別累積ヒット率
   - **推奨**: bootstrap CI 下限のみ採用（実運用再開条件「通算 ROI ≥ +10%」の判定に直結）。
     相関と primary_axis は P4 以降に後送り

5. **判定基準の出力**:
   - **推奨**: 集計時に「実用可能性ステータス」を計算してターミナルに表示
     - `ROI ≥ +10% かつ 最悪月 > -50% かつ bootstrap CI 下限 ≥ 0%` → ✓ **実運用再開条件達成**
     - `ROI ≥ 0% かつ 最悪月 > -50%` → △ **トントン以上**（P4 実走テスト候補）
     - 上記未達 → ✗ **未達**（プロンプト改善 / サンプル拡張 / 撤退検討）
   - 後付けフィルタ追加には絶対使わない（フェーズ 3〜6 の教訓）

6. **出力形式**:
   - サマリー JSON: `artifacts/eval/summary_<from>_<to>.json`
   - ターミナル表示: 月次テーブル + 場別テーブル + confidence 帯別テーブル + 判定ステータス
   - **推奨**: 設計書 §3.3 通り

7. **データ不足時の挙動**:
   - 期間内に 1 日も `<日付>.json` が無い → エラー終了
   - 期間内に部分的に欠損 → warning + 取得済みのみで集計
   - 期間内 `n_bet_races < 30`（サンプル不足）→ warning「統計的信頼性低い、N≥100 を推奨」
   - **推奨**: 上記通り

8. **既存 `evaluate_predictions.py` との関係**:
   - 既存 `evaluate_predictions.py` は **触らない**（出力スキーマだけ依存）
   - `eval_summary.py` は `<日付>.json` を読むだけの集約レイヤ
   - **推奨**: 流用せず独立した CLI として実装（評価ロジックは P3 で完結）

9. **複数日サンプル生成のフロー**:
   - P3.5 を意味あるレベルで動かすには **複数日の eval JSON が必要**
   - 推奨サンプル選定: 2025-09 〜 2025-12 の各月から **ランダムに 3 日 × 4 ヶ月 = 12 日** 抽出
     - 月次トレンド評価のため各月 ≥ 2 日確保
     - 場は混在 OK（全場対応 = `<日付>.json` を出力）
   - 1 日 24 場 × 12R = 最大 288 レースだが、実際は休場考慮で ~150〜200 レース
   - 12 日分なら 1,800〜2,400 レース → 統計的信頼性そこそこ確保可能
   - サンプル生成は **P3.5 の前** にユーザーが手作業で `/prep-races` →
     `/predict` → `/eval-predictions` を回す必要あり
   - **推奨**: P3.5 着手時点でサンプル日数の方針を確認（人間ユーザーがどこまで予想 JSON を書く意思があるか）

10. **P3.5 の打ち切り条件**:
    - サンプル不足（< 5 日）→ 集計はするが警告レベル「P3.5 完了は 30 日相当待ち」
    - 既存 `<日付>.json` のスキーマ違反検出 → エラーログ + skip
    - **推奨**: 上記通り

これらが合意できたら P3.5 を実装する。

#### P3.5 の終了条件

- `ml/src/scripts/eval_summary.py` CLI 実装完了
- `.claude/commands/eval-summary.md` スキル定義完了
- 動作確認:
  - `/eval-summary --from 2025-12-01 --to 2025-12-01` で 1 日分の集計が出る
    （手元にある `2025-12-01.json` のみで `evaluate_predictions.py` の出力と
    数値が一致することを確認、退化テスト）
  - `artifacts/eval/summary_2025-12-01_2025-12-01.json` がスキーマで出力される
- 累積評価（複数日サンプル）は別ステップ（**サンプル生成 → 集計 → 解釈**の順、ユーザー手動の予想生成が必要）

### 厳守事項

- ❌ **Anthropic API（API キー）を使用しない**（Max プラン内完結）
- ❌ 既存の `evaluate_predictions.py` を**書き換えない**（読むだけ）
- ❌ 既存 `predict_llm/` のモジュールは**触らない**
- ❌ 既存 `collector/` のコードは**呼び出さない**（P3.5 はファイル集約のみで I/O 不要）
- ❌ 着手前合意ポイント（上記 1〜10）を**スキップしない**
- ❌ 動作確認なしに完了報告しない
- ❌ ROI が悪い結果でも**後付けフィルタを足してチューニングしない**
  （フェーズ 3〜6 の教訓）
- ✅ 退化テスト: P3.5 の単日集計と P3 の同日 evaluate_predictions 出力が
  ROI / hit_rate / total_stake で完全一致することを必ず確認
- ✅ サンプル不足時は明示的に警告
- ✅ 実運用購入には **使わない**（あくまで Claude の予想精度検証フェーズ）

### 成果物（P3.5 完了時）

1. `ml/src/scripts/eval_summary.py`（CLI、期間集計）
2. `.claude/commands/eval-summary.md`（スキル定義）
3. `artifacts/eval/summary_2025-12-01_2025-12-01.json`（動作確認の集計結果、退化テスト用）
4. CLAUDE.md / LLM_PREDICT_DESIGN.md の P3.5 完了反映
5. （任意）P4 用次セッションプロンプト `NEXT_SESSION_PROMPT_LLM_P4.md`

### 実行環境

- Python 3.12（`py -3.12`）
- ローカル（Windows）、DB 接続不要
- 必要キャッシュ:
  - `artifacts/eval/*.json`（P3 で生成済み + ユーザーが追加生成した分）
- 想定実行時間: P3.5 全体で 1〜3 時間程度（集計ロジック単体は 1 時間以内、
  着手前合意 + 動作確認込み）

### 参照すべきドキュメント

- [LLM_PREDICT_DESIGN.md](LLM_PREDICT_DESIGN.md) — **本フェーズの設計書（必読）**
- [CLAUDE.md](CLAUDE.md) — 「現行の運用方針」「現在の仕様」（LLM フェーズ P1/P2/P3 完了反映済み）
- [.claude/commands/eval-predictions.md](.claude/commands/eval-predictions.md) — P3 スキル定義（フォーマット参考）
- [ml/src/scripts/evaluate_predictions.py](ml/src/scripts/evaluate_predictions.py) — P3 CLI 実装、出力スキーマ
- [artifacts/eval/2025-12-01.json](artifacts/eval/2025-12-01.json) — 入力 JSON 実物（全場）
- [artifacts/eval/2025-12-01_01.json](artifacts/eval/2025-12-01_01.json) — 入力 JSON 実物（場フィルタ）

### 次フェーズ（P4 以降、本セッションでは扱わない）

- **P4**: 実走運用テスト（複数会場 / 当日 live モード / `/prep-races` → `/predict` → `/eval-predictions` → `/eval-summary` の 1 サイクル）
- **P5**: `/schedule` 連携で夜間自動 prep + 朝の自動 eval

P3.5 完了後、ユーザーに動作報告し、次フェーズ着手の合意を取る。

以上。**着手前合意ポイント 1〜10 をユーザー合意してから実装に入ってほしい**。
