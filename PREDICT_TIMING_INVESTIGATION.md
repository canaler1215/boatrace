# 日次予想ベット対象レース数差異の調査レポート

作成日: 2026-04-20

---

## 背景

2026年3月バックテスト（monthly_check）では1日あたり10レース以上がベット対象となる一方、
2026-04-19の日次予想（daily predict）ではベット対象が5レースしか出力されなかった。
この差異の原因を調査し、対応策をまとめた。

---

## 2026年3月 バックテスト分析

### 基本統計

| 指標 | 値 |
|------|----|
| ベット数 | **2,747点** |
| 期間 | 2026-03-01 〜 2026-03-31（31日間）|
| 投資額合計 | **274,700円** |
| 1日平均ベット数 | **88.6点/日** |
| オッズソース | 100% 実オッズ |

適用フィルタ: `prob≥7%`, `EV≥2.0`, コース2/4/5除外, オッズ≥100x, びわこ（ID=11）除外

### 的中サンプル（確認分）

| 日付 | 会場 | R | 組み合わせ | オッズ | 払戻 |
|------|------|---|-----------|-------|------|
| 3/1 | 下関 | 9 | 1-2-6 | 176x | 17,600円 |
| 3/1 | 若松 | 5 | 1-5-4 | 443.8x | 44,380円 |
| 3/6 | 若松 | 1 | 1-5-6 | 830.6x | **83,060円** |
| 3/6 | 若松 | 2 | 3-1-4 | 683.1x | **68,310円** |
| 3/6 | 芦屋 | 4 | 1-4-5 | 1782x | **178,200円** |
| 3/6 | 芦屋 | 9 | 1-4-5 | 202.4x | 20,240円 |
| 3/6 | 芦屋 | 12 | 1-4-3 | 124.4x | 12,440円 |

3/6だけで払戻362,250円。特定日に集中して的中が出る「宝くじ構造」はS6-3の傾向と一致。

### 月間ROIの計算方法

Pythonが使用可能な環境で下記を実行すること：

```bash
python analyze_202603.py
```

（`analyze_202603.py` はリポジトリルートに配置済み）

---

## 5レース vs 10レース以上の差異 — 根本原因

### monthly_check と daily predict のデータソースの違い

| 項目 | monthly_check | daily predict |
|------|--------------|--------------|
| データソース | K/Bファイル（過去完全データ） | DBの `odds` テーブル |
| オッズ | 全レース・全120通りが揃った状態 | 収集時点でboatrace.jpに公開済みのものだけ |
| 実行タイミング | 月終了後に一括処理 | 手動dispatch（リアルタイム）|

### collect.yml のスケジュールとオッズ公開タイミングのミスマッチ

```
07:00 JST  run_collect.py（レース前収集）← ここが問題
21:30 JST  run_collect.py（レース後収集・着順取得）
```

boatrace.jpのオッズは各レース開始の**約30分前**に公開される。
07:00 JSTの収集時点では10:00〜16:30スタートの大多数のレースオッズは**未公開**。

### run_predict.py のスキップロジック

```python
# ml/src/scripts/run_predict.py L226-229
odds_dict = fetch_odds(conn, race_id)
if not odds_dict:
    logger.warning("Race %s: no odds data, skipping.", race_id)
    continue
```

- DBの `odds` テーブルが空のレースはスキップされる
- スキップされたレースは `predictions` テーブルに記録されない
- → 次回 daily predict 実行時も「未予測」として再検出される

### predict.yml にdailyモードのcronが存在しない

`predict.yml` は `workflow_dispatch`（手動実行）のみ。
cronスケジュールがないため、実行タイミングがユーザー依存となり、
オッズ公開前に実行した場合に大多数のレースがスキップされる。

### 2026-04-19 に5レースしか出力されなかった経緯

1. 07:00 JST に `run_collect.py` が実行 → レース情報・出走表は収集済み、**オッズはほぼ未取得**
2. 午前中（オッズ公開前）に daily predict を手動実行
3. `odds` テーブルにデータがあった5レースだけ予測が完了
4. 残り60+レースはオッズなし → スキップ → `predictions` に未記録のまま

### openapi_client.py の変更について

git diff を確認した結果、変更内容は **`fetch_trio_odds()` の追加と `import itertools` の追加のみ**。
既存のレース収集・3連単オッズ取得ロジックへの影響はなく、今回の問題とは無関係。

---

## 推奨対応

### 短期対応（即効）

日次予想を **14:00 JST 以降（全レースのオッズ公開後）** に実行する。
その際、predictの直前に collect を手動実行するとDBのオッズが更新され、
ほぼ全レースを対象にできる。

```
手順:
1. GitHub Actions → Collect Race Data → Run workflow（手動）
2. 完了後 → Predict & Calculate EV → daily → Run workflow（手動）
```

### 中期対応（恒久）

`predict.yml` にdailyモード用のcronトリガーを追加する。

```yaml
# predict.yml の on: セクションに追加
schedule:
  - cron: '30 1 * * *'   # 毎日 10:30 JST（最初のレース前・早時間帯オッズ公開後）
  - cron: '0 4 * * *'    # 毎日 13:00 JST（中間レース・オッズ公開後）
```

または、daily predictワークフロー内に collect ステップを組み込む：

```yaml
- name: Collect latest odds before prediction
  run: python ml/src/scripts/run_collect.py
  env:
    DATABASE_URL: ${{ secrets.DATABASE_URL }}

- name: Run daily prediction
  run: python ml/src/scripts/run_predict.py
  env:
    DATABASE_URL: ${{ secrets.DATABASE_URL }}
```

これにより predict 実行直前に最新オッズが収集され、タイミング依存の問題が解消される。

---

## 関連ファイル

| ファイル | 概要 |
|---------|------|
| `.github/workflows/collect.yml` | データ収集スケジュール（07:00 / 21:30 JST）|
| `.github/workflows/predict.yml` | 日次予想・月次検証ワークフロー |
| `ml/src/scripts/run_predict.py` | 日次予想スクリプト（DBからレース取得）|
| `ml/src/scripts/run_collect.py` | データ収集スクリプト（boatrace.jpスクレイピング）|
| `ml/src/scripts/run_predict_check.py` | 月次バックテストスクリプト（K/Bファイル使用）|
| `ml/artifacts/predict_check_202603.csv` | 2026年3月バックテスト結果（2,747行）|
