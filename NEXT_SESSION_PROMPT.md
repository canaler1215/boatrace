# 次セッション用プロンプト — フェーズ B-3 Step 1: 単勝オッズ DL + 市場効率分析（着手前合意フェーズ）

以下を次セッションの最初のユーザープロンプトとして貼り付けてください。

---

## プロンプト本文

boatrace プロジェクトのフェーズ B-3「馬券種転換による市場効率分析（単勝）」の Step 1 に着手してほしい。
これは **2026-04-26 にフェーズ B-1（3 連単市場効率分析）が完全撤退確定**となったあと、
方針転換として「控除率の異なる券種（単勝、控除率 20%）で同じ歪み分析を試す」新フェーズ。

作業開始前に必ず以下を読むこと:

- `NEXT_PHASE_B3_PLAN.md`（B-3 全体計画、Step 1〜5 の流れ、採用基準、撤退条件）
- `NEXT_PHASE_B1_PLAN.md` §9「B-1 撤退結果」（直前フェーズの撤退結論、本フェーズの起点）
- `MARKET_EFFICIENCY_RESULTS.md`（B-1 Step 1、3 連単で観測された favorite-longshot bias）
- `MARKET_EFFICIENCY_SEGMENT_RESULTS.md`（B-1 Step 2、控除率 25% を破れなかった結論）
- `CLAUDE.md`「現在の仕様」「現行の運用方針」（全フェーズ撤退状態、B-3 着手予定の記述）
- `BET_RULE_REVIEW_202509_202512.md` §28-32（オッズパースバグ修正後の実態、実運用再開条件）
- `ml/src/collector/odds_downloader.py`（既存 trifecta / trio DL の流用ベース）
- `ml/src/collector/openapi_client.py`（既存 `fetch_odds` / `fetch_trio_odds`、新規 `fetch_win_odds` を追加する基盤）
- `ml/src/scripts/run_market_efficiency.py`（B-1 で実装したスクリプト、`--bet-type win` 拡張対象）

### これまでの経緯（要約）

| フェーズ | 内容 | 結果 |
|---|---|---|
| 3 `/inner-loop` | 購入フィルタ探索 | out-of-sample 黒字化不能、凍結 |
| 6 `/model-loop` | モデル構造改善 | 完全撤退（採用基準達成 0） |
| 7 (B-1) | 3 連単市場効率分析 | **完全撤退**（lift 1.10〜1.27 観測も控除率 25% を破れず、最高 ev=0.98） |
| **B-3**（本タスク）| **単勝市場効率分析（控除率 20%）** | **着手予定** |

### B-3 を選んだ理由

- 単勝は控除率 20%（3 連単 25% より 5pp 低い）
- 黒字化に必要な lift は 1.25（3 連単 1.33 より 8pp 低い）
- B-1 で観測した「人気組合せの lift 1.20〜1.27」が単勝でも観測されれば、**控除率破壊閾値クリアの可能性**
- 単勝は 6 通りのみで分析がシンプル、サンプル分散が安定

### Step 1 で行うこと（最小スコープ）

**単勝オッズ取得関数 + DL コード + 1 ヶ月だけ試行 DL で API 動作確認**。
12 ヶ月本格 DL（推定 12〜24 時間）に入る前に、API スキーマと動作を確認する。

#### 着手前合意ポイント（実装前にユーザー確認）

以下の設計判断について合意を取ってから着手する:

1. **対象券種**: 単勝（win, 6 通り、控除率 20%）から開始でよいか? 複勝 / 2 連単 / 2 連複は将来拡張
2. **対象期間**: 2025-05〜2026-04（B-1 と同じ 12 ヶ月）でよいか
3. **オッズ DL 方法**:
   - (a) `openapi_client.fetch_odds` と同じ `boatraceopenapi.github.io` の `oddstf` API のスキーマを確認し、単勝相当エンドポイント（`oddssin` or `odds3t` の win 部分）を `fetch_win_odds` として追加
   - (b) 既存 `fetch_odds` のレスポンスに win オッズが含まれていれば抽出のみ（追加 API 呼び出し不要）
   - (c) boatrace.jp スクレイピング（API がない場合）
   - 上記いずれかを Step 1 の最初に判定（試行 1 ヶ月 DL で確認）
4. **キャッシュ形式**: `data/odds/win_odds_YYYYMM.parquet`（カラム: race_id, boat_no, odds）でよいか
5. **Step 1 の打ち切り条件**: 1 ヶ月試行 DL でデータが取れなかった / API スキーマが想定と違う場合、その時点で B-3 撤退（NEXT_PHASE_B3_PLAN §8 撤退基準）
6. **Step 1 完了後**: ユーザーに 12 ヶ月本番 DL の実行確認を取る（バックグラウンド実行、12〜24 時間）
7. **Step 1 のコード差分**: `openapi_client.py` + `odds_downloader.py` への追加のみ。`run_market_efficiency.py` は触らない（Step 2 で拡張）

これらが合意できたら Step 1 を実装する。

#### Step 1 の終了条件

- `fetch_win_odds(stadium_id, race_date, race_no) -> dict[str, float]` が実装され、1 レース分の動作確認 OK
- `load_or_download_month_win_odds(year, month, race_df)` が実装され、1 ヶ月（2025-12 推奨）試行 DL で `data/odds/win_odds_202512.parquet` が出る
- parquet の中身を読んで `race_id × 6 通り × odds` の形式と件数妥当性を確認
- ユーザーへ 12 ヶ月本番 DL 実行可否を確認

#### Step 1 の判定（NEXT_PHASE_B3_PLAN §8）

- **取得 OK**: 1 ヶ月試行 DL でデータが期待通り取れた → Step 2 (12 ヶ月本番 DL + 市場効率分析) へ
- **取得 NG**: API がない / 認証エラー継続等 → **B-3 撤退**

### 厳守事項

- ❌ 既存モデル（trainer.py / predictor.py / engine.py）は**触らない**
- ❌ Step 1 完了前に 12 ヶ月本番 DL を始めない（試行 1 ヶ月で API 確認が先）
- ❌ Step 2-3 の歪み確認前に Step 4 のバックテストを始めない
  （フェーズ 6 + B-1 の教訓: 「精度改善 → ROI 改善」「歪み発見 → ROI プラス」の素朴な期待は何度も裏切られた）
- ❌ 着手前合意ポイント（上記 1〜7）を**スキップしない**。実装前にユーザーと仕様を固めてから 1 本のスクリプトを書く
- ❌ 既存 `data/odds/odds_*.parquet`（trifecta）を上書きしない。**`win_odds_*.parquet` 別ファイル**で管理

### 成果物（Step 1 完了時）

1. `ml/src/collector/openapi_client.py` に `fetch_win_odds` 追加
2. `ml/src/collector/odds_downloader.py` に `load_or_download_month_win_odds` 追加
3. `data/odds/win_odds_202512.parquet`（試行 DL の結果、1 ヶ月分）
4. `MARKET_EFFICIENCY_WIN_RESULTS.md`（仮、Step 1 結果と Step 2 進行 / 撤退の判定。NEXT_PHASE_B3_PLAN §8 を参照）
5. `AUTO_LOOP_PLAN.md` フェーズ 8 タスク B-3 進捗更新

### 実行環境

- Python 3.12（`py -3.12`）
- ローカル（Windows）、DB 接続不要
- 必要キャッシュ: `data/history/` + `data/program/`（K/B ファイル、揃い済み）
- 想定実行時間: Step 1（試行 1 ヶ月 DL）= 5〜10 分、Step 2（12 ヶ月本番 DL）= 12〜24 時間（バックグラウンド）

### 参照すべきドキュメント

- [NEXT_PHASE_B3_PLAN.md](NEXT_PHASE_B3_PLAN.md) — B-3 全体計画、本タスクの上位設計書
- [NEXT_PHASE_B1_PLAN.md](NEXT_PHASE_B1_PLAN.md) §9 — B-1 撤退結果、本フェーズの起点
- [MARKET_EFFICIENCY_RESULTS.md](MARKET_EFFICIENCY_RESULTS.md) — B-1 Step 1（3 連単）結果
- [MARKET_EFFICIENCY_SEGMENT_RESULTS.md](MARKET_EFFICIENCY_SEGMENT_RESULTS.md) — B-1 Step 2（3 連単）結果
- [CLAUDE.md](CLAUDE.md) — 「現行の運用方針」「現在の仕様」
- [LAMBDARANK_WALKFORWARD_RESULTS.md](LAMBDARANK_WALKFORWARD_RESULTS.md) — フェーズ 6 撤退の確証（参考流儀）
- [AUTO_LOOP_PLAN.md](AUTO_LOOP_PLAN.md) — フェーズ 8 セクション
- [BET_RULE_REVIEW_202509_202512.md](BET_RULE_REVIEW_202509_202512.md) — 実運用再開条件
- [ml/src/collector/odds_downloader.py](ml/src/collector/odds_downloader.py) — 既存 trifecta / trio DL（流用ベース）
- [ml/src/collector/openapi_client.py](ml/src/collector/openapi_client.py) — `fetch_win_odds` 追加対象
- [ml/src/scripts/run_market_efficiency.py](ml/src/scripts/run_market_efficiency.py) — Step 2 で `--bet-type win` 拡張対象

以上。**着手前合意ポイント 1〜7 をユーザー合意してから実装に入ってほしい**。
