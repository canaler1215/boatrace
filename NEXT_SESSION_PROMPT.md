> # 🛑 凍結済み (2026-04-28、Q-B 合意 / (P-v) ハイブリッド採用)
>
> 本ファイルは凍結時点の参照記録として保持されている。**新規着手は不可**。
>
> 全 6 系統 (B-1 / B-3 win / 拡張 A / P-v condition / P4-α LLM / Model-loop) で採用基準未達。
> 後続作業は無し。詳細は [CLAUDE.md](CLAUDE.md)「現行の運用方針」冒頭参照。
>
> 手動でレース予想したくなった時は CLAUDE.md「手動レース予想の手順 (P-v 凍結後)」へ。

---

# 次セッション用プロンプト — フェーズ B-3 Step 2 集計: `run_market_efficiency.py --bet-type win` 拡張（着手前合意フェーズ）

以下を新セッションの最初のユーザープロンプトとして貼り付けてください。

---

## プロンプト本文

boatrace プロジェクトのフェーズ B-3「馬券種転換による市場効率分析（単勝）」の **Step 2 集計フェーズ** に着手してほしい。

### 前提（重要）

- **Step 1 完了済み**（2026-04-26）: 単勝オッズ DL 関数 (`fetch_win_odds` / `load_or_download_month_win_odds`) 実装 + 試行 DL（2025-12）成功
- **12 ヶ月本番 DL 完了済み**（2026-04-27 03:36）: 2025-05〜2026-04 で **54,299 races / 12 ヶ月 / 0 empty**（12.9 時間、エラーなし）
- 本セッションでは **`run_market_efficiency.py` に `--bet-type win` を追加し、12 ヶ月集計で lift / `ev_all_buy` / bootstrap CI を計算、採用判定（Step 3 進行 or B-3 撤退）** まで完了させる

作業開始前に必ず以下を読むこと:

- `MARKET_EFFICIENCY_WIN_RESULTS.md`（Step 1 結果 + 12 ヶ月 DL 結果、実勢 overround 1.36 の観察事項を含む）
- `NEXT_PHASE_B3_PLAN.md` §2 Step 2 / §3 採用判断基準
- `MARKET_EFFICIENCY_RESULTS.md`（B-1 trifecta 集計結果、流儀の参照元）
- `MARKET_EFFICIENCY_SEGMENT_RESULTS.md`（B-1 segment 結果、Step 3 流儀の参照元）
- `ml/src/scripts/run_market_efficiency.py`（trifecta 用の現行実装、`--bet-type win` 拡張対象）
- `ml/src/collector/odds_downloader.py`（`load_or_download_month_win_odds` 含む、Step 1 で追加済み）
- `CLAUDE.md`「現在の仕様」「現行の運用方針」（B-3 Step 1 + 12 ヶ月 DL 完了状態）
- `BET_RULE_REVIEW_202509_202512.md` §28-32（実運用再開条件）

### これまでの経緯（要約）

| フェーズ | 内容 | 結果 |
|---|---|---|
| 3 `/inner-loop` | 購入フィルタ探索 | 凍結 |
| 6 `/model-loop` | モデル構造改善 | 完全撤退 |
| 7 (B-1) | 3 連単市場効率分析（控除率 25%） | 完全撤退（最高 ev=0.98 / 蒲郡 × 1 コース） |
| **B-3** Step 1 | 単勝オッズ DL 関数 + 試行 DL（控除率 20%） | 完了 |
| **B-3** 12 ヶ月 DL | 2025-05〜2026-04 単勝 12 ヶ月分 | 完了（54,299 races / 0 empty） |
| **B-3 Step 2 集計**（本タスク）| **`--bet-type win` 拡張 + 12 ヶ月集計 + 採用判定** | **着手予定** |

### 開始前のチェック（必ず実行）

```bash
ls data/odds/win_odds_*.parquet | wc -l   # 12 を期待
```

12 ファイル揃っていない場合は DL 完了状態を再確認（ヘルパー: `load_or_download_month_win_odds(year, month, race_df)` を呼べば未取得月のみ DL）。

### Step 2 集計で行うこと（最小スコープ）

1. `run_market_efficiency.py` に `--bet-type {trifecta,win}` 引数追加（trifecta 既存挙動はデフォルトで維持）
2. 単勝の implied probability 計算（重要: Step 1 で実勢 overround 1.36 = 控除率 26% を観測。下記合意点 2 で扱い方を決める）
3. 単勝のヒット判定（1 着の艇番）
4. ビニング（合意点 1 参照）
5. 既存 segment 分析（B-1 で実装済み）の win 対応
6. bootstrap 90% CI（n_resamples=2000、レース単位 stratify）
7. 12 ヶ月集計を実行 → 採用判定 → 結果ドキュメントに追記

### 着手前合意ポイント（実装前にユーザー確認）

以下の設計判断について合意を取ってから着手する:

1. **ビニング方式**:
   - (a) 等幅 10 ビン `[0, 0.1, 0.2, ..., 1.0)` — `NEXT_PHASE_B3_PLAN.md §2 Step 2` の推奨
   - (b) 等密度 quantile（10 ビン）— サンプル数が均等になるが、可読性低下
   - 推奨: (a) 等幅 10 ビン
2. **overround 補正**:
   - Step 1 観察: 実勢 overround = 1.3556（控除率 26%、理論 20% より +6pp）
   - (a) リスケール `implied_p = (1/odds) / overround_per_race` で正規化（B-1 trifecta と同流儀）
   - (b) 未補正 `implied_p = 1/odds` のみ
   - (c) 両方 CSV カラムに出して比較
   - 推奨: (a) を主、(c) で両出し
3. **ヒット判定**:
   - 単勝は「1 着艇 = combination 完全一致」でシンプル
   - 欠場（B欠等）レース: 6 艇全揃いでないレースは集計から除外（Step 1 観察で 5.8% / 12 ヶ月で約 3,150 レース）
   - 推奨: 上記
4. **採用基準（NEXT_PHASE_B3_PLAN §3）**:
   - Step 2 合格条件: 「ある暗黙確率帯（n ≥ 1,000）で `lift ≥ 1.10` または `≤ 0.85`」「90% bootstrap CI で lift = 1.0 を含まない」「前半 6 ヶ月 / 後半 6 ヶ月で同方向」
   - **重要**: 「控除率破壊閾値 lift = 1.25」は実勢 overround 1.36 を踏まえると **lift = 1.36 / 1.0 = 1.36** が真の閾値の可能性。`ev_all_buy > 1.0` を主指標とし、lift は補助で使う方針でよいか
   - 推奨: `ev_all_buy > 1.0` を採用判定の主指標、lift は構造観察用
5. **segment 分析の対象**:
   - 場別（24 場）
   - 場 × 暗黙確率帯（B-1 と同じ）
   - 推奨: 上記 2 軸で開始、コース別は単勝には該当しない（艇番 = combination キーそのもの）ので除外
6. **出力ファイル名規約**:
   - `artifacts/market_efficiency_2025-05_2026-04_win.csv`
   - `artifacts/market_efficiency_2025-05_2026-04_win.png`
   - `artifacts/market_efficiency_segment_stadium_focus_<focus_band>_2025-05_2026-04_win.csv`
   - 推奨: 上記、`_trifecta.csv` と並列の命名
7. **欠場レースの扱い**:
   - 6 艇全揃い（94.2%、12 ヶ月で約 51,150 レース）のみ集計対象
   - 艇数 5 / 4 / 3（5.8%、約 3,150 レース）は除外
   - 推奨: 上記

これらが合意できたら Step 2 集計を実装する。

### Step 2 集計の終了条件

- `run_market_efficiency.py --bet-type win --start 2025-05 --end 2026-04` がエラーなく完走
- `artifacts/market_efficiency_2025-05_2026-04_win.csv` 出力
- 採用判定（lift / `ev_all_buy` / bootstrap CI）の集計レポートが `MARKET_EFFICIENCY_WIN_RESULTS.md` に追記され、Step 3 進行 / B-3 撤退の判定がつく

### Step 2 集計の判定（NEXT_PHASE_B3_PLAN §3 / §8）

- **Step 2 合格** → Step 3（サブセグメント分析）に進む
- **Step 2 不合格**（全 implied_p 帯にわたり lift が 0.95〜1.05）→ **B-3 撤退**（NEXT_PHASE_B3_PLAN §8）

### 厳守事項

- ❌ 既存モデル（trainer.py / predictor.py / engine.py）は触らない
- ❌ Step 4 のバックテスト前に Step 2-3 の歪み確認を完了する（フェーズ 6 + B-1 の教訓）
- ❌ 着手前合意ポイント（上記 1〜7）を**スキップしない**
- ❌ 既存 trifecta の集計コードを破壊しない（`--bet-type trifecta` のデフォルト互換は維持）
- ❌ 既存出力ファイル `artifacts/market_efficiency_2025-12_2025-12_trifecta.*` を上書きしない

### 成果物（Step 2 集計完了時）

1. `ml/src/scripts/run_market_efficiency.py` に `--bet-type {trifecta,win}` 引数追加（trifecta 既存挙動を維持）
2. 単勝集計用の helper 関数追加（implied probability 計算、ヒット判定、ビニング）
3. 12 ヶ月集計の実行結果:
   - `artifacts/market_efficiency_2025-05_2026-04_win.csv`
   - `artifacts/market_efficiency_2025-05_2026-04_win.png`
4. segment 分析の実行結果:
   - `artifacts/market_efficiency_segment_stadium_focus_*_2025-05_2026-04_win.csv`
   - `artifacts/market_efficiency_segment_stadiumXodds_band_focus_*_2025-05_2026-04_win.csv`
5. `MARKET_EFFICIENCY_WIN_RESULTS.md` に「§6 Step 2 集計結果」「§7 Step 2 判定」を追記
6. `AUTO_LOOP_PLAN.md` フェーズ 8 の Step 2 集計状態更新

### 実行環境

- Python 3.12（`py -3.12`）
- ローカル（Windows）、DB 接続不要
- 必要キャッシュ: `data/history/` + `data/program/` + `data/odds/win_odds_2025{05..12}.parquet` + `data/odds/win_odds_2026{01..04}.parquet`
- 想定実行時間: 集計 1〜2 分（B-1 trifecta と同等）+ 実装 4〜6 時間 + レポート作成 30 分

### 参照すべきドキュメント

- [MARKET_EFFICIENCY_WIN_RESULTS.md](MARKET_EFFICIENCY_WIN_RESULTS.md) — Step 1 結果 + 12 ヶ月 DL 結果、本タスクの起点
- [NEXT_PHASE_B3_PLAN.md](NEXT_PHASE_B3_PLAN.md) — B-3 全体計画
- [MARKET_EFFICIENCY_RESULTS.md](MARKET_EFFICIENCY_RESULTS.md) — B-1 trifecta 集計、流儀参照
- [MARKET_EFFICIENCY_SEGMENT_RESULTS.md](MARKET_EFFICIENCY_SEGMENT_RESULTS.md) — B-1 segment 結果、Step 3 準備
- [CLAUDE.md](CLAUDE.md) — 「現行の運用方針」「現在の仕様」
- [BET_RULE_REVIEW_202509_202512.md](BET_RULE_REVIEW_202509_202512.md) — 実運用再開条件
- [ml/src/scripts/run_market_efficiency.py](ml/src/scripts/run_market_efficiency.py) — 拡張対象
- [ml/src/collector/odds_downloader.py](ml/src/collector/odds_downloader.py) — `load_or_download_month_win_odds`

### B 完了後の関連プロンプト（参考）

| 次タスク | プロンプト | 前提 |
|---|---|---|
| **A**: 複勝 (place) DL 関数の実装 | [NEXT_SESSION_PROMPT_A.md](NEXT_SESSION_PROMPT_A.md) | 単勝 12 ヶ月 DL 完了済み（OK） |
| **C**: 2 連単 / 2 連複 / 拡連複 DL 関数の実装 | [NEXT_SESSION_PROMPT_C.md](NEXT_SESSION_PROMPT_C.md) | A の試行 DL 完了後 |

以上。**着手前合意ポイント 1〜7 をユーザー合意してから実装に入ってほしい**。
