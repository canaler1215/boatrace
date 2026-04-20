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
