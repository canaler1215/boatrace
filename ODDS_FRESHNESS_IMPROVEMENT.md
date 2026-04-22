# オッズ鮮度改善計画（EV 信憑性向上）

作成日: 2026-04-22

---

## 背景

ダッシュボードに表示される EV（期待値）が実際のオッズと大きく乖離しており、購入判断の信頼性が低下している。
`ODDS_FETCH_FIX.md` と `PREDICT_REALTIME_IMPROVEMENT.md` で個別の修正は済んでいるが、
**「予測時オッズ vs 実走時オッズの乖離」** という根本課題は解消できていない。

本ドキュメントでは、現状の定期実行構造とオッズ取得タイミングを分析し、
EV の信憑性を高めるための改善ポイントを整理する。

---

## 現状の定期実行フロー

### GitHub Actions ワークフロー構成

| ワークフロー | トリガー | 処理時間 | 役割 |
|-------------|---------|---------|------|
| `collect.yml` | `repository_dispatch: collect-trigger`（cron-job.org 30分ごと） | ~5-7 分 | 出走表 + 直前情報 + 3連単オッズ の全取得（boatrace.jp HTML スクレイピング） |
| `predict.yml` (daily) | `repository_dispatch: predict-trigger`（cron-job.org 30分ごと、collect から 15 分オフセット） | ~3-5 分 | DB の最新オッズで全未終了レースを再予測（LightGBM 推論 + EV 計算） |
| `refresh_ev.yml` | `repository_dispatch: refresh-ev-trigger`（10分ごと想定） | ~1-2 分 | オッズのみ再取得 → 既存 `win_probability` × 新オッズ で EV を直接 UPDATE（LightGBM 推論なし） |

### 理論上のオッズ鮮度

| 実行系統 | 最大オッズ遅延 | 更新回数/日 |
|---------|--------------|------------|
| collect + predict のみ（30 分間隔） | **~30 分** | ~20 回 |
| refresh_ev（10 分間隔）追加時 | **~10 分** | ~60 回 |

---

## 問題① 実走時オッズとの乖離が大きい

### boatrace.jp のオッズ公開パターン

- 発売開始（レース ~2 時間前）: 序盤は変動が激しい
- 発売締切（レース ~1-2 分前）: **確定オッズ**。本番投票結果に最も近い
- レース後: 確定オッズ（払戻額の基準）

### 現状の取得タイミングのズレ

cron-job.org の 10/30 分ごとのトリガーは **レースの発走時刻とは非同期**。
最悪ケース：

1. 10:29 JST に `refresh_ev` が実行 → 10:31 発走レースの「2 分前オッズ」を取得
2. 10:39 JST に次の `refresh_ev` が実行 → 同レースはすでに発走・締切済み
3. → **「発走 2 分前オッズ」と「実際の確定オッズ」の差が EV に残り続ける**

発走直前の数分間はオッズ変動が最も激しく、人気馬（本命）のオッズは数倍〜十数倍単位で動くことがある。
この時間帯のスナップショット欠落は EV 乖離の主因となる。

### 定量的には

- 予測時 `odds_snapshot_at` ≈ 発走 10-30 分前（現状運用）
- 実際の払戻基準 ≈ 発走時刻
- **乖離時間: 10-30 分、オッズ変動率: 10-50% 程度**

→ EV = prob × odds の odds 項に 10-50% の誤差。prob 項のキャリブレーション改善
（Session 6 の Isotonic Regression）より EV 誤差の寄与が大きい可能性がある。

---

## 問題② `collect.yml` の重複取得によるレート制限リスク

### 現行 `collect.yml` の処理

`run_collect.py` は毎回 **全未終了レース** に対して：

1. `fetch_entry_info`（出走表）: 1 リクエスト × N レース
2. `fetch_before_info`（直前情報）: 1 リクエスト × N レース
3. `fetch_odds`（3 連単オッズ）: 1 リクエスト × N レース

1 日最大 ~300 レース × 3 = **900 リクエスト/回** × 20 回実行 = **~18,000 リクエスト/日**

boatrace.jp の実測レスポンスは 9-10 秒/リクエスト。`MAX_WORKERS=10` の並列でも 5-7 分かかる。
加えて `refresh_ev.yml` が 10 分ごとに最大 200 リクエスト/回追加。

### 出走表・直前情報は毎 30 分取得する必要がない

- `fetch_entry_info`（出走表・モーター/ボート 2 連率）: **発売開始時に確定**、以降変化しない
- `fetch_before_info`（展示タイム・ST）: **発走 ~40 分前に確定**、以降変化しない
- `fetch_odds`（3 連単オッズ）: **発走まで秒単位で変動**

現状は 3 つを同時に毎 30 分取得している。オッズ以外は 1 日 1 回で十分。
→ **出走表・直前情報とオッズの収集サイクルを分離すべき**。

---

## 問題③ 発走直前オッズを狙い撃ちできる機構がない

### cron-job.org の制約

- 任意の時刻に単発トリガーを投げられるが、「発走 2 分前にトリガー」のような
  レース時刻連動はサポートしない
- 全会場 ~12 レース/日 × 24 会場 = ~300 レース/日、発走時刻は会場ごとに異なる
- 現状は固定間隔で「平均的にそこそこ新しい」オッズしか取れない

### あるべき姿

```
発走 30 分前: オッズ取得（序盤）
発走 10 分前: オッズ取得（中盤）
発走 3 分前:  オッズ取得（終盤、ほぼ確定）
発走後:      レース結果取得
```

現行構成では「発走 3 分前オッズ」は 10 分間隔 refresh_ev でも取得できない可能性が 30% ある
（ジョブ間隔 10 分 ÷ 30 分の取得チャンス）。

---

## 問題④ オッズ履歴が残らない（上書きのみ）

### 現在の `odds` テーブル構造

```sql
CREATE TABLE odds (
  race_id     TEXT,
  combination TEXT,
  odds_value  NUMERIC,
  snapshot_at TIMESTAMP,
  PRIMARY KEY (race_id, combination)  -- 一意制約
);
```

`ON CONFLICT (race_id, combination) DO UPDATE` で**常に最新のみを保持**。
過去のオッズ履歴はすべて失われる。

### 影響

- 「発走 30 分前 → 10 分前 → 1 分前」のオッズ推移が分析できない
- バックテストで「発走 X 分前のオッズを使った場合の ROI」を検証できない
- 発売締切直前のオッズがいつ確定したか追跡できない

---

## 問題⑤ 確定オッズとの突き合わせ未実装

### 現状

- `run_predict.py` / `refresh_ev.py` は最後に取得したオッズで EV を確定
- レース結果（`fetch_race_result`）は取得するが、**当該レースの確定オッズ**は再取得していない
- → 予測時オッズと実払戻の差分がモニタリングできない

### 理想

レース終了後に boatrace.jp の確定オッズを 1 回取得し、`predictions.final_odds` に保存。
`EV_predicted / EV_actual` 比率で予測精度を継続モニタリング。

---

## 問題⑥ `odds_snapshot_at` 情報がフロントエンドに出ていない可能性

`predictions.odds_snapshot_at` は Phase 3 で追加済み（`migrations/0005_odds_snapshot_at.sql`）。
ただし実際に UI に表示されているかは未確認。ユーザー（ベット判断者）が
**「この EV は何分前のオッズで算出されたか」**を見られないと誤判断を招く。

---

## 改善ロードマップ

### 優先度A：発走直前オッズの捕捉

#### A-1. `refresh_ev.yml` の実行間隔短縮（10 分 → 5 分）

- cron-job.org のジョブを 5 分間隔に変更
- 1 日あたりの追加リクエスト: ~200 × 12 = ~2,400 リクエスト増
- boatrace.jp 側の負荷: 現状 ~18,000/日 → ~20,400/日（+13%）。許容範囲
- **発走 3 分前オッズのキャプチャ率**: 30% → 60% に改善

#### A-2. 発走時刻を DB に保持し、発走 5 分前のレースのみ狙う

`races.race_date` だけでなく `races.deadline_at`（発売締切時刻）も DB に保存し、
`run_refresh_ev.py` で `WHERE deadline_at BETWEEN now() AND now() + interval '15 min'` に絞る。

- 対象レースが 1 リクエスト時点で ~5-20 件に絞れる
- 1 回の実行が ~20 秒で完了 → 1 分ごとの実行も視野

現状の `races` テーブルに締切時刻列がない場合はスキーマ追加が必要（後述）。

#### A-3. 発走直後の確定オッズ取得ステップを追加 ✅ 2026-04-22 実装済み

`run_collect.py` の「終了済みレース処理」で `fetch_odds` を最後にもう 1 回呼び、
`predictions.final_odds`（新列）に保存。

**実装内容**:
- `migrations/0006_predictions_final_odds.sql`: `final_odds` と `final_odds_recorded_at` 列追加
- `db_writer.update_predictions_final_odds_batch`: `WHERE final_odds IS NULL` ガード付きで初回のみ書き込み
- `run_collect.py`: `status == "finished"` のレースのオッズを `predictions.final_odds` にも転記
- `tests/test_final_odds_writer.py`: SQL ガードと引数バインド順の検証（5/5 PASS）

---

### 優先度B：出走表・直前情報とオッズの分離

#### B-1. `collect.yml` を 3 本に分割

| ワークフロー | 実行頻度 | 取得対象 |
|-------------|---------|---------|
| `collect_entries.yml` | 1 日 1-2 回（07:00 / 13:00 JST） | 出走表・モーター/ボート 2 連率 |
| `collect_beforeinfo.yml` | 発走 40-5 分前 | 直前情報（展示タイム・ST） |
| `refresh_ev.yml` | 1-5 分ごと | 3 連単オッズのみ（既存） |

**効果**:
- boatrace.jp への日次リクエスト数: ~18,000 → ~5,000（-72%）
- オッズ取得頻度を現状比 2-10 倍に上げても負荷は同等以下
- レート制限ブロックのリスク低減

#### B-2. `run_refresh_ev.py` の軽量化

現状の `run_refresh_ev.py` は「全未終了レースのオッズを取得」するが、
既に発売締切済みのレースにはオッズ再取得が不要（確定済み）。
`races.status` に `deadline_passed` のような中間ステータスを導入して絞り込む。

---

### 優先度C：オッズ履歴の保存

#### C-1. `odds_history` テーブル新設

```sql
CREATE TABLE odds_history (
  id           BIGSERIAL PRIMARY KEY,
  race_id      TEXT NOT NULL,
  combination  TEXT NOT NULL,
  odds_value   NUMERIC NOT NULL,
  snapshot_at  TIMESTAMP NOT NULL,
  INDEX (race_id, snapshot_at)
);
```

既存の `odds` テーブルは「最新値キャッシュ」として残し、`odds_history` に
`INSERT ONLY` で時系列データを蓄積する。

**容量試算**: 300 レース × 120 組 × 1 日 60 スナップショット = 2.16M 行/日
→ 年 788M 行。Neon の無料枠では厳しい。履歴保存は最新 30 日分に limit するか、
選抜組み合わせ（EV ≥ 2.0 のもの）のみを保存する。

#### C-2. バックテスト用の発走直前オッズ取得

既存の K/B ファイル（バックテスト用）には確定オッズしかない。
「発走 X 分前のオッズ」でバックテストしたい場合、`odds_history` を参照することで
モデル検証の精度を上げられる。

---

### 優先度D：UI/可視化

#### D-1. ダッシュボードに `odds_snapshot_at` 表示

`predictions.odds_snapshot_at`（Phase 3 で追加済み）をフロントエンドに表示。
「このオッズは X 分前のものです」バッジでユーザーに鮮度を認識させる。

#### D-2. 予測時オッズ vs 確定オッズのサマリー

日次バッチで前日分の `predictions.expected_value`（予測時 EV）と
`final_odds × win_probability`（確定 EV）の差分を集計し、
「当日の EV 乖離分布」を可視化。

---

### 優先度E：モデル側の対応

#### E-1. オッズ変動を特徴量化

発走 30 分前から 5 分前までのオッズ変動率（人気の変化）を特徴量に追加することで、
「締切直前に人気を落とした本命」などの情報を予測に活用できる。
ただし C-1 のオッズ履歴が先に必要。

---

## 実装優先順位と工数見積もり

| 優先 | タスク | 対象ファイル | 効果 | 工数 |
|------|-------|------------|------|------|
| **A-1** | `refresh_ev` を 5 分間隔に短縮 | cron-job.org 設定のみ | 発走直前オッズ捕捉率 30% → 60% | 10 分 |
| **A-2** | 発売締切時刻を DB に保存、近接レースだけ絞る | `run_collect.py`, migrations, `run_refresh_ev.py` | 1 実行 ~20 秒化、1 分間隔実行が可能に | 1-2 日 |
| **A-3** | 確定オッズ取得を `run_collect.py` に追加 | `run_collect.py`, `predictions` スキーマ | 予測精度モニタリング可能に | 0.5 日 |
| **B-1** | 出走表・直前情報・オッズのワークフロー分離 | `.github/workflows/` x3, 新スクリプト | boatrace.jp 負荷 -72%、ブロックリスク低減 | 2-3 日 |
| **B-2** | `run_refresh_ev.py` のレース絞り込み | `run_refresh_ev.py`, `races` スキーマ | 1 実行の処理時間短縮 | 0.5 日 |
| **C-1** | `odds_history` テーブル追加 | migrations, `run_refresh_ev.py` | オッズ推移の分析基盤 | 1 日 |
| **C-2** | 発走直前オッズでのバックテスト検証 | `run_backtest.py`, `odds_simulator.py` | モデル検証精度向上 | 2-3 日 |
| **D-1** | ダッシュボードに `odds_snapshot_at` 表示 | `apps/web/` | ユーザー誤判断防止 | 0.5 日 |
| **D-2** | 予測 EV vs 確定 EV の乖離ダッシュボード | `apps/web/`, 集計バッチ | 運用品質の継続監視 | 2-3 日 |
| **E-1** | オッズ変動を特徴量化 | `feature_builder.py`, 学習データ生成 | 予測精度向上（仮説） | 1 週間 |

---

## 推奨する初期アクション

即効性と工数のバランスから、以下 3 つを最初に実施することを推奨する：

1. **A-1**（cron-job.org 設定変更のみ・10 分）: 発走直前オッズ捕捉率を 2 倍に
2. **A-3**（確定オッズ保存・0.5 日）: 予測精度の定量モニタリングを可能に
3. **D-1**（UI 表示・0.5 日）: ユーザーに鮮度情報を届ける

A-1 と A-3 で乖離実態の定量化ができたうえで、A-2 / B-1 などの本格的な
アーキテクチャ変更の要否を判断する流れが合理的。

---

## 関連ファイル

| ファイル | 概要 |
|---------|------|
| `.github/workflows/collect.yml` | 出走表・直前情報・オッズの全取得（30 分ごと） |
| `.github/workflows/predict.yml` | 日次予測（30 分ごと） |
| `.github/workflows/refresh_ev.yml` | オッズのみ再取得 + EV UPDATE（10 分ごと想定） |
| `ml/src/scripts/run_collect.py` | データ収集スクリプト |
| `ml/src/scripts/run_predict.py` | 予測スクリプト |
| `ml/src/scripts/run_refresh_ev.py` | EV 再計算スクリプト |
| `ml/src/collector/openapi_client.py` | boatrace.jp スクレイピング |
| `ml/src/collector/db_writer.py` | DB upsert |
| `apps/web/lib/db/migrations/0005_odds_snapshot_at.sql` | `predictions.odds_snapshot_at` 列追加済み |
| `PREDICT_REALTIME_IMPROVEMENT.md` | 先行する改善（30 分ごと再予測化） |
| `PREDICT_TIMING_INVESTIGATION.md` | ベット対象数乖離の原因調査 |
| `ODDS_FETCH_FIX.md` | `oddsPoint` パターンのバグ修正（2026-04-22） |
