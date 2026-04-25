# 次セッション用プロンプト — フェーズ B-1 Step 1: 市場効率の歪み分析（着手前合意フェーズ）

以下を次セッションの最初のユーザープロンプトとして貼り付けてください。

---

## プロンプト本文

boatrace プロジェクトのフェーズ B-1「市場効率の歪み分析」の Step 1 に着手してほしい。
これは **2026-04-25/26 にフェーズ 6（モデル構造ループ）が完全撤退確定**となったあと、
方針転換として「モデル精度ではなくオッズ側の構造的バイアス」を狙う新フェーズ。

作業開始前に必ず以下を読むこと:

- `NEXT_PHASE_B1_PLAN.md`（B-1 全体計画、Step 1〜4 の流れ、採用基準、撤退条件）
- `LAMBDARANK_WALKFORWARD_RESULTS.md`（フェーズ 6 撤退結果、特に Step 7 の seed 反復確証）
- `CLAUDE.md`「現在の仕様」「現行の運用方針」（フェーズ 6 完全撤退、B-1 着手予定の記述）
- `BET_RULE_REVIEW_202509_202512.md` §28-32（オッズパースバグ修正後の実態、実運用再開条件）
- `ml/src/scripts/run_calibration.py`（モデル確率のキャリブレーション分析、参考にする実装）
- `ml/src/scripts/run_segment_analysis.py`（場・コース・オッズ帯別 ROI、参考になる集計）
- `data/odds/`（2025-05〜2026-04 の実オッズキャッシュ、既に揃っている）

### これまでの経緯（要約）

| フェーズ | 内容 | 結果 |
|---|---|---|
| 3 `/inner-loop` | 購入フィルタ探索 | out-of-sample 黒字化不能、凍結 |
| 6 `/model-loop` | モデル構造改善（13 trial + PoC + lambdarank Walk-Forward） | **完全撤退確定**（採用基準達成 0） |
| **B-1**（本タスク）| **市場効率の歪み分析** | **着手予定** |

### Step 1 で行うこと（最小スコープ）

**「オッズから逆算した暗黙確率」と「実勝率」を比較する分析スクリプトを作る**。
モデルは一切使わない。既存 odds キャッシュとレース結果のみで完結する。

#### 着手前合意ポイント（実装前にユーザー確認）

以下の設計判断について合意を取ってから着手する:

1. **対象期間**: 2025-05〜2026-04（実オッズが揃っている 12 ヶ月）で良いか
2. **対象券種**: 3 連単 trifecta から始める。trio / win は将来拡張
3. **暗黙確率の正規化**: `(1 / odds) / sum(1 / odds for all 120 combos)` で
   レース内 sum-to-1 にして比較する案で良いか
   - 別案: 控除率 0.25 を仮定して `(1 - 0.25) / odds` を独立確率として扱う
   - 別案: 正規化なし、生 implied_p のまま見る
4. **ビニング**: 暗黙確率帯を等幅 10 ビン（0-1%, 1-2%, ...）で良いか
   - 等頻度ビン（log scale）の方が高オッズ帯の解像度が出る可能性
5. **集計指標**: ビン内 n、平均 implied_p、平均 actual_p、lift = actual / implied、
   `EV(if all-buy) = 平均オッズ × 平均 actual_p` を出す案で良いか
6. **CI**: ブートストラップ 90% CI を lift に対して計算（B-1 PLAN §3 記載）。
   ブロック長 = 1 ヶ月、再サンプル数 2000 で良いか
7. **出力**: CSV + matplotlib プロット（キャリブレーションプロット）。出力先は
   `artifacts/market_efficiency_<period>_<bet>.{csv,png}` で良いか

これらが合意できたら新規スクリプト `ml/src/scripts/run_market_efficiency.py`
（仮）を実装する。実装は trainer.py / predictor.py / engine.py を一切触らない
**新規スクリプト 1 本に閉じ込める**方針（フェーズ 6 PoC と同じ流儀）。

#### Step 1 の終了条件

- スクリプトが動き、12 ヶ月分の集計が出る
- キャリブレーションプロットを目視確認
- ブートストラップ CI 付きで「lift = 1.0 を逸脱する暗黙確率帯」がいくつ見つかったかを報告
- `MARKET_EFFICIENCY_RESULTS.md`（仮）を作成

#### Step 1 の判定（B-1 PLAN §3 採用基準）

- **歪みあり判定**: ある暗黙確率帯（n ≥ 1,000 ベット相当）で
  `lift ≥ 1.10` または `≤ 0.85`、かつ 90% CI で 1.0 を含まず、
  かつ前半 6 ヶ月 / 後半 6 ヶ月で同方向 → **Step 2 へ進む**
- **歪みなし判定**: 全帯で lift が 0.95〜1.05、または CI に 1.0 を含む → **B-1 撤退**

### 厳守事項

- ❌ 既存モデル（trainer.py / predictor.py / engine.py）は**触らない**
- ❌ オッズ追加 DL は**しない**（既存キャッシュ `data/odds/` で完結）
- ❌ Step 1 の歪み確認前に Step 3 のバックテストを始めない
  （フェーズ 6 の教訓: 「精度改善 → ROI 改善」の素朴な期待は裏切られた）
- ❌ 着手前合意ポイント（上記 1〜7）を**スキップしない**。実装前にユーザーと
  仕様を固めてから 1 本のスクリプトを書く

### 成果物（Step 1 完了時）

1. `ml/src/scripts/run_market_efficiency.py`（新規、~150〜250 行想定）
2. `artifacts/market_efficiency_2025-05_2026-04_trifecta.csv`
3. `artifacts/market_efficiency_2025-05_2026-04_trifecta.png`
4. `MARKET_EFFICIENCY_RESULTS.md`（Step 1 結果、判定、Step 2 進行 / 撤退の提案）
5. `AUTO_LOOP_PLAN.md` フェーズ 7 タスク B-1 進捗更新

### 実行環境

- Python 3.12（`py -3.12`）
- ローカル（Windows）、DB 接続不要
- 必要キャッシュ: `data/odds/` (12 ヶ月分、揃い済み) + `data/history/` + `data/program/`
- 想定実行時間: 数分（120 万行程度の集計、モデル学習なし）

### 参照すべきドキュメント

- [NEXT_PHASE_B1_PLAN.md](NEXT_PHASE_B1_PLAN.md) — B-1 全体計画、本タスクの上位設計書
- [CLAUDE.md](CLAUDE.md) — 「現行の運用方針」「現在の仕様」
- [LAMBDARANK_WALKFORWARD_RESULTS.md](LAMBDARANK_WALKFORWARD_RESULTS.md) — フェーズ 6 撤退の確証
- [AUTO_LOOP_PLAN.md](AUTO_LOOP_PLAN.md) — フェーズ 7 セクション
- [BET_RULE_REVIEW_202509_202512.md](BET_RULE_REVIEW_202509_202512.md) — 実運用再開条件
- [ml/src/scripts/run_calibration.py](ml/src/scripts/run_calibration.py) — calibration 分析の参考
- [ml/src/scripts/run_segment_analysis.py](ml/src/scripts/run_segment_analysis.py) — セグメント集計の参考

以上。**着手前合意ポイント 1〜7 をユーザー合意してから実装に入ってほしい**。
