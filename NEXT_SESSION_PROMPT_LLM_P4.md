# 次セッション着手プロンプト — LLM フェーズ P4（運用テスト）

このファイルの中身をそのまま新しい Claude Code セッションに貼り付ければ、
P4 の合意フェーズ → 実装/運用フェーズに入れる。

---

boatrace プロジェクトの新フェーズ「Claude Code 競艇予想システム」の
**P4 = 運用テストフェーズ** に着手してほしい。

これは **2026-04-27 に P3.5 完了** した状態からの続き。
P3 で日次評価 (`/eval-predictions`)、P3.5 で期間横断ロールアップ (`/eval-summary`)
が揃ったので、P4 では **複数日 dry-run でサンプルを積み、`/eval-summary` で
判定ステータスが `breakeven` 以上に到達するかを検証する**。

**Anthropic API は使わず、Max プラン内（Claude Code 対話セッション）で完結する設計**。

作業開始前に必ず以下を読むこと:

- [LLM_PREDICT_DESIGN.md](LLM_PREDICT_DESIGN.md)（**本フェーズの設計書**、特に §3.3「累積評価」 / §8 P3+P3.5 完了メモ / §11「評価指標」 / §12「厳守事項」）
- [CLAUDE.md](CLAUDE.md)「現在の仕様」「現行の運用方針」（全 ML 改善ループ撤退状態 + LLM フェーズ P1/P2/P3/P3.5 完了済み）
- [.claude/commands/prep-races.md](.claude/commands/prep-races.md)（P1）
- [.claude/commands/predict.md](.claude/commands/predict.md)（P2）
- [.claude/commands/eval-predictions.md](.claude/commands/eval-predictions.md)（P3）
- [.claude/commands/eval-summary.md](.claude/commands/eval-summary.md)（P3.5）
- [artifacts/eval/2025-12-01_01.json](artifacts/eval/2025-12-01_01.json)（P3 動作確認サンプル）

---

## これまでの経緯（要約）

| フェーズ | 内容 | 結果 |
|---|---|---|
| 3 `/inner-loop` | 購入フィルタ探索 | out-of-sample 黒字化不能、凍結 |
| 6 `/model-loop` | モデル構造改善 | 完全撤退（採用基準達成 0） |
| 7 (B-1) | 3 連単市場効率分析 | 完全撤退（控除率 25% を破れず） |
| B-3 | 単勝市場効率分析 | 別セッションで進行中 |
| LLM P1 | `/prep-races` 基盤 | 2026-04-26 完了 |
| LLM P2 | `/predict` スキル | 2026-04-26 完了 |
| LLM P3 | `/eval-predictions` スキル | 2026-04-27 完了（17 bets / 1 hit / ROI -57.6%、手計算検証 pass） |
| LLM P3.5 | `/eval-summary` スキル | 2026-04-27 完了（退化テスト pass、bootstrap CI / 判定ステータス装備） |
| **LLM P4**（本タスク）| **運用テスト** | **着手** |

---

## P3.5 完了状況（前提）

- `ml/src/scripts/eval_summary.py` 実装済（期間集計 + bootstrap CI + 判定ステータス）
- `.claude/commands/eval-summary.md` スキル登録済
- 単日退化テスト pass（`2025-12-01.json` の数値と完全一致）
- 判定ステータス: `production_ready` (ROI ≥ +10% & worst > -50% & CI下限 ≥ 0) /
  `breakeven` (ROI ≥ 0% & worst > -50%) / `fail`
- 警告ルール: `n_bet_races < 30` / `n_days_with_data < 5` / 期間内ファイル不在で warning
- **重大な制約**: 現サンプルは `2025-12-01` の **1 日のみ**。
  P4 はサンプル拡張から始まる

---

## P4 で行うこと（最小スコープ）

### スコープ全体像

P4 は**実装より運用がメイン**。Claude が手動で複数日の dry-run を回すフェーズ。

```
複数日サンプル拡張 (4 ヶ月 × 数日 = 12 日目標)
       ↓
/eval-summary --month で月次ロールアップ
       ↓
判定ステータス確認 (production_ready / breakeven / fail)
       ↓
結果に応じて次アクション決定 (P5 / プロンプト改善 / 撤退)
```

### サブフェーズ

#### P4-α: dry-run サンプル拡張（手動・反復）

ユーザー（人間）と Claude が交互に実行する想定:

1. ユーザーが日付を指定（例: `2025-09-15`）
2. Claude が `/prep-races 2025-09-15` でレースカードを生成（過去日ドライランモード）
3. Claude が `/predict 2025-09-15` で予想 JSON を出力
   - 全場 24 場 × 12R = 最大 288 レースだが、休場があるので実数 ~150〜200 レース
   - **1 セッションで 1 日分は重い**ので、`/predict 2025-09-15 桐生` のように
     場を絞るか、夜間のセッションで複数日を回すか方針相談する
4. Claude が `/eval-predictions 2025-09-15` で日次評価 JSON 出力
5. 上記を **2025-09 / 10 / 11 / 12 から各 3 日 = 計 12 日**目標で繰り返す

#### P4-β: ロールアップ評価

12 日分の `<日付>.json` が揃ったら:

1. `/eval-summary --from 2025-09-01 --to 2025-12-31` で 4 ヶ月通算
2. `/eval-summary --month 2025-09` (10/11/12 も) で月次比較
3. 判定ステータス + 月次トレンド + 場別累積 + confidence 帯別を確認

#### P4-γ: 解釈と次アクション

- **production_ready** 達成 → P5（実走テスト、少額自動購入）の合意プロセスへ
- **breakeven** 達成 → サンプル拡張継続 + プロンプト改善の余地検討
- **fail**（worst_month < -50% / CI下限 < -50pp など） → 撤退検討、ML 系統と同じく
  Claude (LLM) も競艇 3 連単では勝てない可能性を表面化

---

## 着手前合意ポイント（実装/運用前にユーザー確認）

以下の判断をまとめて確認してから着手する:

### 1. dry-run の対象日選定

**推奨**:
- 期間: 2025-09-01 〜 2025-12-31（4 ヶ月、過去オッズ DL 済範囲内）
- 各月から 3 日 × 4 ヶ月 = 計 12 日
- 月内は等間隔に近い日（例: 月初 / 月中 / 月末）
- 場は全場対応（`/prep-races YYYY-MM-DD` で全場のレースカード生成）

代替案:
- (a) 同一場（例: 桐生）4 ヶ月通しで場依存性を排除して評価
- (b) 12 日と言わず 7 日（各月 1〜2 日）に絞って早く判定する
- (c) 30 日以上目標（信頼性確保、ただし時間コスト大）

### 2. 1 セッションあたりの作業量

1 日分の `/predict` を全場（~150 レース）で実行すると Claude のターン数が
膨大になる（1 レース = 1 Read + 1 Write）。

**推奨**: 1 セッション 1 日分に固定。`/predict YYYY-MM-DD` を Claude が
順番に処理（途中でセッション分割可）

代替案:
- (a) 1 セッション複数日。途中で context 圧縮されるので分析品質は落ちる可能性
- (b) `/predict YYYY-MM-DD STADIUM` で場を絞って 1 セッション 1 場 (~12 レース)。
  ただし `/eval-summary` は `<日付>.json` のみ参照なので、最終的に
  全場版 `<日付>.json` が必要。`/eval-predictions YYYY-MM-DD`（場なし）で集約

### 3. プロンプト改善の許容範囲

P4 中に Claude の予想スタイル（confidence 付け方、買い目数、見送り基準）を
変えるかどうか:

**推奨**: P4-α 完了時点では **predict.md を変更しない**。データを集めて
判定が出るまでは変数固定。判定が `breakeven` ぎりぎりなら、P5 着手前に
プロンプト改善ループを別フェーズとして導入する判断

代替案:
- (a) サンプル積みながら逐次改善。ただし out-of-sample 評価が
  汚れるので非推奨（フェーズ 3〜6 の教訓と同根）

### 4. 当日 live モードの試運転タイミング

過去日 dry-run と並行して当日 live モードも回すか:

**推奨**: P4-α 中は dry-run 専念。当日 live モードは P5 で初めて試す
（live モードはオッズ取得タイミング・締切時刻の制約が増えるため、
別変数を一度に動かさない）

### 5. 判定が `fail` だった場合の撤退条件

**推奨**: 以下のすべてを満たしたら撤退判断 (≒ ML 系統と同じく Claude も
競艇 3 連単では勝てないと判断):
- 12 日サンプル時点の通算 ROI < -20%
- 4 ヶ月のうち 3 ヶ月以上で月次 ROI < -10%
- bootstrap CI 上限すら 0% 未満

撤退時は CLAUDE.md に「LLM フェーズも撤退」を明記し、競艇予測プロジェクト
全体の終了を検討する。

代替案:
- (a) 撤退前にプロンプト改善 + サンプル拡張で再挑戦（合計 30 日まで）

### 6. 成果物（P4 完了時）

**P4-α 完了**:
- `artifacts/predictions/<日付>/*.json` × 12 日 × 全場
- `artifacts/eval/<日付>.json` × 12 日

**P4-β 完了**:
- `artifacts/eval/summary_2025-09-01_2025-12-31.json`（4 ヶ月通算）
- `artifacts/eval/summary_2025-09.json` 等（月次）

**P4-γ 完了（判定）**:
- CLAUDE.md / LLM_PREDICT_DESIGN.md に判定結果反映
- 次フェーズ（P5 or 撤退 or プロンプト改善）の合意プロンプト

### 7. P4 セッション分割の方針

**推奨**: P4-α は 12 セッションに分割（1 セッション 1 日分）。
P4-β / P4-γ は別セッションで一気に。

### 8. P4 中に追加実装が必要になる可能性

現状 CLI は揃っている (`/prep-races`, `/predict`, `/eval-predictions`,
`/eval-summary`) ので、追加実装は基本不要。ただし運用中に発見した
不具合・不便はその場で修正する（プロンプト改善以外の修正は許容）。

---

## P4 の終了条件

- 12 日分の `<日付>.json` が揃う
- `/eval-summary --from 2025-09-01 --to 2025-12-31` で集計
- 判定ステータスを確認
- CLAUDE.md / LLM_PREDICT_DESIGN.md に結果反映
- 次フェーズ着手プロンプト（P5 / 撤退 / 改善のいずれか）を作成

---

## 厳守事項

- ❌ **Anthropic API（API キー）を使用しない**（Max プラン内完結）
- ❌ 既存の `evaluate_predictions.py` / `eval_summary.py` を**書き換えない**
  （バグ修正以外）
- ❌ 既存 `predict_llm/` のモジュールは**触らない**（`predict.md` プロンプト改善は
  P4 中はしない）
- ❌ 着手前合意ポイント（上記 1〜8）を**スキップしない**
- ❌ 動作確認なしに完了報告しない
- ❌ ROI が悪い結果でも**後付けフィルタを足してチューニングしない**
  （フェーズ 3〜6 の教訓）
- ❌ **実運用購入はしない**（あくまで dry-run + 評価フェーズ）
- ✅ サンプル不足時は明示的に警告
- ✅ 各日の `/predict` 完了時には Claude 自身が `/eval-predictions` まで
  自動的に走らせて、その日のうちに ROI 数値を確認
- ✅ 判定が出た後の意思決定はユーザーに委ねる

---

## 実行環境

- Python 3.12（`py -3.12`）
- ローカル（Windows）、DB 接続不要
- 必要キャッシュ:
  - `data/history/` — 2025-09〜2025-12 の K ファイル（不足時は P3 CLI が自動 DL）
  - `data/odds/` — 2025-09〜2025-12 の `odds_YYYYMM.parquet`（既に DL 済のはず）
  - `data/program/` — 出走表（不足時は P1 CLI が自動 DL）
- 想定実行時間:
  - P4-α: 1 セッション = 1 日分 = ~150 レース × Claude 1 ターン ≈ 数時間
  - P4-β / γ: 各 30 分以内

---

## 参照ドキュメント

- [LLM_PREDICT_DESIGN.md](LLM_PREDICT_DESIGN.md) — **本フェーズの設計書（必読）**、
  §3.3 / §8 P3+P3.5 完了メモ / §11 評価指標 / §12 厳守事項
- [CLAUDE.md](CLAUDE.md) — 「現行の運用方針」「現在の仕様」（LLM フェーズ
  P1/P2/P3/P3.5 完了反映済み）
- [.claude/commands/](. claude/commands/) — 全 4 スキル定義
- [ml/src/scripts/](ml/src/scripts/) — `build_race_cards.py` /
  `fetch_pre_race_info.py` / `evaluate_predictions.py` / `eval_summary.py`
- [ml/src/predict_llm/](ml/src/predict_llm/) — P1/P2 で実装したモジュール群

---

## 次フェーズ（P5 以降、本セッションでは扱わない）

- **P5**: 実走運用テスト（当日 live モード + 少額自動購入、ただし production_ready 判定後）
- **P6**: `/schedule` 連携で夜間自動 prep + 朝の自動 eval

P4 完了後、判定結果に応じて次フェーズ着手の合意を取る。

以上。**着手前合意ポイント 1〜8 をユーザー合意してから運用に入ってほしい**。
