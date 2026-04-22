# 日次予想リアルタイム化 改善計画

作成日: 2026-04-20

---

## 背景

`PREDICT_TIMING_INVESTIGATION.md` の中期対応として `predict.yml` に cron スケジュールと
predict 前 collect ステップを追加したが（2026-04-20 実施）、以下の根本課題が残っている。

1. **1レース1回限りの予測**：一度予測したレースは再予測されず、オッズ変動が EV に反映されない
2. **predict 内 collect による実行時間増大**：頻度を上げる際のボトルネックになる

---

## 現状の問題

### 問題① NOT EXISTS 制約による再予測不可

`ml/src/scripts/run_predict.py` のレース取得クエリ（L178–184）：

```sql
SELECT r.id
FROM races r
WHERE r.race_date = %s
  AND r.status != 'finished'
  AND NOT EXISTS (
        SELECT 1 FROM predictions p WHERE p.race_id = r.id
      )
```

- 一度でも `predictions` テーブルに記録されたレースは永久にスキップされる
- オッズはレース直前まで変動するが、EV は初回予測時の古いオッズに固定される
- `upsert_prediction` は ON CONFLICT UPDATE に対応済みのため、制約を外すだけで再予測が可能

### 問題② collect と predict の同一ジョブ化

現行 `predict.yml`（2026-04-20 変更後）の daily フロー：

```
GitHub Actions 起動（checkout + pip install + model download: ~2-3 分）
  └─ run_collect.py（全レース HTTP 取得: ~3-5 分）
  └─ run_predict.py（推論 + DB upsert: ~1-3 分）
```

- 1実行あたり合計 ~7-10 分かかる
- collect（HTTP 取得）が含まれるため predict 単体より重い
- 高頻度実行（30 分ごと）に対して起動オーバーヘッドの割合が大きい

---

## 推奨構成（役割分離）

### アーキテクチャ

```
collect.yml  毎 30 分 09:00-18:30 JST  DB にオッズを書き込み続ける
predict.yml  毎 30 分 09:15-18:45 JST  DB の最新オッズで全未終了レースを再予測
```

collect が DB を更新し続け、predict はその DB のみを参照する。
両者を 15 分オフセットすることで collect 完了後に predict が動くことを保証する。

### オッズ鮮度

| 指標 | 現状（10:30 / 13:00 の2回） | 改善後（30 分ごと） |
|------|----------------------------|-------------------|
| 最大オッズ遅延 | ~3 時間 | ~30 分 |
| 1日あたり予測更新回数 | 2 回 | ~18 回 |
| EV の鮮度 | 初回予測時のまま固定 | 常に最新オッズに追従 |

---

## 必要な変更

### 変更 1：`ml/src/scripts/run_predict.py`（コアロジック）

`NOT EXISTS predictions` 条件を削除し、未終了の全レースを毎回再予測する。

**変更前：**
```python
cur.execute(
    """
    SELECT r.id
    FROM races r
    WHERE r.race_date = %s
      AND r.status != 'finished'
      AND NOT EXISTS (
            SELECT 1 FROM predictions p WHERE p.race_id = r.id
          )
    """,
    (today_jst,),
)
```

**変更後：**
```python
cur.execute(
    """
    SELECT r.id
    FROM races r
    WHERE r.race_date = %s
      AND r.status != 'finished'
    """,
    (today_jst,),
)
```

`upsert_prediction` は既に `ON CONFLICT (race_id, combination) DO UPDATE SET predicted_at = now()` を
実装済みのため、同一 race_id + combination の再予測は安全に上書きされる。

### 変更 2：`collect.yml`

レース時間帯（09:00-18:30 JST = 00:00-09:30 UTC）に 30 分ごとの収集を追加する。

```yaml
schedule:
  - cron: '0,30 0-9 * * *'   # 毎 30 分 09:00-18:30 JST (00:00-09:30 UTC)
  - cron: '0 22 * * *'        # 毎日 07:00 JST (従来の朝収集)
  - cron: '30 12 * * *'       # 毎日 21:30 JST (従来の夜収集・着順取得)
  - cron: '0 18 * * 0'        # 毎週日曜 03:00 JST (racer_st_stats 更新)
```

### 変更 3：`predict.yml`

1. inline collect ステップを削除（collect.yml が担う）
2. 30 分ごとの cron スケジュールに変更

```yaml
schedule:
  - cron: '15,45 0-9 * * *'   # 毎 30 分 09:15-18:45 JST (collect から 15 分オフセット)
```

daily ジョブのステップから `Collect latest odds before prediction` ステップを削除。

---

## 実装優先順位

| 優先 | 変更箇所 | 効果 | 難易度 |
|------|---------|------|--------|
| **高** | `run_predict.py` NOT EXISTS 削除 | EV が常に最新オッズに追従 | 低（2行削除） |
| **高** | `collect.yml` 高頻度スケジュール追加 | オッズ鮮度 3h → 30 分 | 低（cron 追加） |
| **中** | `predict.yml` inline collect 削除 | predict の実行時間短縮 | 低（ステップ削除） |
| **中** | `predict.yml` 高頻度スケジュール変更 | 予測更新回数 2 → 18 回/日 | 低（cron 変更） |

---

## 懸念事項と対策

### GitHub Actions 並行実行の競合

collect と predict が同時刻に動いた場合、collect の DB 書き込み中に predict が読み込む可能性がある。
→ 15 分オフセットで回避。collect は ~5 分で完了するため、predict 開始時には書き込み済みになる。

### DB 負荷

30 分ごとに collect（全レース upsert）＋ predict（全未終了レース upsert）が走る。
1日のレース数は最大 ~300 程度（24 場 × 12 レース）。
Neon の接続プールと executemany バッチ処理で対応済みのため問題なし。

### collect.yml のジョブ並行数

`0,30 0-9 * * *` は 1 日 20 回のトリガーになり、従来の 2 回から大幅増加。
ただし 1 回の実行時間が ~5 分のため、30 分間隔では重複しない。

---

## 関連ファイル

| ファイル | 概要 |
|---------|------|
| `PREDICT_TIMING_INVESTIGATION.md` | 本改善の前提となった調査レポート |
| `.github/workflows/collect.yml` | データ収集スケジュール |
| `.github/workflows/predict.yml` | 日次予想ワークフロー |
| `ml/src/scripts/run_predict.py` | 予測スクリプト（NOT EXISTS が対象箇所） |
| `ml/src/scripts/run_collect.py` | 収集スクリプト |

---

## 補足検討：会場ごとの分割実行は現実的か（2026-04-22）

### 結論：**現実的ではない**

「collect → predict を会場ごとに並列化することで高頻度実行できるか」を検討したが、以下の理由により効果がない。

### ボトルネック分析

| 要因 | 内容 |
|------|------|
| **GitHub Actions cold start** | checkout + pip install だけで毎回 **1〜2分** の固定コスト。会場を分けても各インスタンスが同じ起動コストを払う |
| **boatrace.jp レスポンス** | 実測 ~9-10秒/リクエスト。1レース分（出走表 + 直前情報 + オッズ = 3リクエスト）で **~30秒** |
| **並列化の限界** | 現行 `MAX_WORKERS=10` の ThreadPoolExecutor はすでに全会場を並列処理している。会場単位で分割しても総リクエスト数は変わらない |

### 会場分割した場合の追加問題

- cron-job.org で会場数（最大6〜8）分のトリガーを管理する運用負荷
- boatrace.jp への同時リクエスト集中によるブロックリスク
- 複数ワークフローからの同時 DB 書き込みによる競合リスク

---

## 代替アプローチ：オッズのみ軽量再取得（推奨）

会場分割ではなく、**「オッズ取得だけを独立した軽量ワークフローに分離する」** ことでオッズ鮮度を改善する。

### 設計

```
collect.yml（現行・30分ごと）
  → 出走表・直前情報・オッズの全データを収集（重い処理）

refresh_ev.yml（10分ごと・軽量）
  → オッズのみ再取得（1レース1リクエスト）
  → predictions.expected_value / alert_flag を上書き更新
```

### なぜオッズ単体なら軽いか

`run_collect.py` の1レースあたり処理：
- `fetch_entry_info`（出走表）: 1リクエスト
- `fetch_before_info`（直前情報）: 1リクエスト
- `fetch_odds`（オッズ）: **1リクエスト** ← これだけ再取得

オッズ取得のみなら全未終了レース（最大 ~200件）を `MAX_WORKERS=10` で並列化すると **~2〜3分** で完了する。cold start 込みでも **1実行あたり ~4〜5分** に収まり、10分ごとの実行が現実的になる。

### オッズ再取得後の EV 再計算

`predictions` テーブルにはすでに `win_probability` が保存されている。
オッズ取得後は確率を再推論せずに、`EV = win_probability × new_odds` を DB 上で直接更新するだけでよい。

```python
# run_refresh_ev.py のコアロジック（イメージ）
for race_id in active_race_ids:
    new_odds = fetch_odds(stadium_id, today, race_no)   # HTTP 1リクエスト
    for combo, odds_val in new_odds.items():
        ev = stored_prob[combo] * odds_val
        update_prediction_ev(conn, race_id, combo, ev)  # DB UPDATE のみ
```

### 期待効果

| 指標 | 現行（collect 30分ごと） | refresh_ev 追加後（10分ごと） |
|------|------------------------|------------------------------|
| 最大オッズ遅延 | ~30分 | **~10分** |
| EV 再計算頻度 | 30分ごと | **10分ごと** |
| 追加 HTTP リクエスト数 | — | ~200件/回（オッズのみ） |
| 実装コスト | — | 低（新スクリプト1本 + yml1本） |

### 実装ステップ

1. `ml/src/scripts/run_refresh_ev.py` を新規作成（オッズ取得 + EV 上書き）
2. `.github/workflows/refresh_ev.yml` を新規作成（10分ごと、cron-job.org トリガー）
3. `predictions` テーブルに `odds_snapshot_at` 列を追加してオッズ鮮度を記録（任意）

---

## 実装状況の確認（2026-04-22）

### 完了済み変更

| 変更 | 対象ファイル | 状態 | 確認方法 |
|------|------------|------|---------|
| 変更1: NOT EXISTS 削除 | `ml/src/scripts/run_predict.py` L172-181 | **完了** | `status != 'finished'` のみで取得するクエリに変更済み |
| 変更2: collect.yml 高頻度化 | `.github/workflows/collect.yml` | **完了** | `repository_dispatch: collect-trigger` で cron-job.org からトリガー受け取り済み |
| 変更3: predict inline collect 削除 | `.github/workflows/predict.yml` | **完了** | predict.yml に collect ステップなし、predict のみ実行 |
| 変更4: predict.yml 高頻度化 | `.github/workflows/predict.yml` | **完了** | `repository_dispatch: predict-trigger` で cron-job.org からトリガー受け取り済み |
| `upsert_prediction` ON CONFLICT 対応 | `ml/src/collector/db_writer.py` L167-174 | **完了** | `win_probability`・`expected_value`・`alert_flag`・`predicted_at` を UPDATE |
| `expected_value` NULL 許容 | `migrations/0004_predictions_ev_nullable.sql` | **完了** | オッズなし時に確率のみ先行保存できる |

### 未実装（次フェーズ）

| 変更 | 対象ファイル | 優先度 | 効果 |
|------|------------|--------|------|
| `run_refresh_ev.py` 新規作成 | `ml/src/scripts/run_refresh_ev.py` | **中** | predict（~3分）より軽量なオッズのみ再取得 + DB上でEV直接更新 |
| `refresh_ev.yml` 新規作成 | `.github/workflows/refresh_ev.yml` | **中** | 10分ごとの EV 再計算ワークフロー |
| `predictions.odds_snapshot_at` 追加 | `migrations/0005_odds_snapshot_at.sql` | **低** | オッズ鮮度の可視化（任意） |

### cron-job.org 側の設定確認

`collect.yml` と `predict.yml` は `repository_dispatch` トリガーに切り替え済みだが、
**cron-job.org 側で実際に 30 分ごとに HTTP POST しているかを確認する必要がある。**

```
collect-trigger: 毎 30 分 09:00-18:30 JST
predict-trigger: 毎 30 分 09:15-18:45 JST（collect から 15 分オフセット）
```

cron-job.org の管理画面で上記 2 ジョブが設定済みであれば、変更1〜4 はすべて稼働中。

---

## 対応の流れ（実装ロードマップ）

### Phase 1: 現行構成の稼働確認（即時）

1. cron-job.org ダッシュボードで `collect-trigger` / `predict-trigger` ジョブを確認
   - 実行間隔: 30 分
   - エンドポイント: `https://api.github.com/repos/{owner}/boatrace/dispatches`
   - タイムゾーン: 09:00-18:45 JST の範囲
2. GitHub Actions の実行ログを確認（`collect.yml` と `predict.yml` が 30 分ごとに動いているか）
3. DB の `predictions.predicted_at` を確認し、当日レースが繰り返し上書きされているか検証

### Phase 2: run_refresh_ev.py 実装（任意・中期）

現行の `predict.yml` は LightGBM 推論も含む（~3 分）。
推論不要のオッズ再取得のみに絞った軽量スクリプトを追加することで、10 分間隔の EV 追従が可能になる。

**実装方針：**

```python
# run_refresh_ev.py のコアロジック
def main():
    with get_connection() as conn:
        # 1. 当日の未終了レース（かつ predictions に確率が保存済み）を取得
        active_races = fetch_active_races_with_predictions(conn, today_jst)
        
        for race in active_races:
            # 2. オッズのみ取得（1リクエスト / レース）
            new_odds = fetch_odds(race["stadium_id"], today_jst, race["race_no"])
            if not new_odds:
                continue
            
            # 3. DB 上で EV を直接更新（推論不要）
            #    EV = win_probability × new_odds
            update_ev_from_odds(conn, race["id"], new_odds)
        
        conn.commit()
```

`update_ev_from_odds` は `predictions` テーブルの `win_probability` を読んで
`expected_value = win_probability * odds_value` を計算し、`alert_flag` も再評価する UPDATE 文。

**スクリプト追加時の必要ファイル：**
- `ml/src/scripts/run_refresh_ev.py`（新規）
- `.github/workflows/refresh_ev.yml`（新規、`repository_dispatch: refresh-ev-trigger`）
- cron-job.org に `refresh-ev-trigger` ジョブを追加（10 分ごと）

### Phase 3: odds_snapshot_at 列追加（任意）

EV の鮮度を Web UI に表示したい場合のみ実施。

```sql
-- migrations/0005_odds_snapshot_at.sql
ALTER TABLE "predictions" ADD COLUMN "odds_snapshot_at" timestamp;
```

`run_refresh_ev.py` の UPDATE 時に `odds_snapshot_at = now()` を同時に書き込む。
