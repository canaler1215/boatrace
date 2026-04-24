---
description: モデル構造自律改善ループを実行する（ローカルで学習ハイパラ・学習窓・sample_weight を探索）
argument-hint: [trial_id | all]
---

# /model-loop — モデル構造自律改善ループ

引数: `$ARGUMENTS`（例: `T00_baseline` / `all` / 省略時は all 扱い）

`/inner-loop`（フィルタ探索、GitHub Actions 経由）とは**別系統**のループ。
こちらは**学習側**（LightGBM ハイパラ・学習窓・sample_weight）を探索する。

- 変更対象: `ml/configs/strategy_default.yaml` は**触らない**。代わりに `trials/pending/*.yaml` を使用
- 実行場所: **ローカル**（Windows / Python 3.12）。GitHub Actions は使わない
- 1 trial の時間: 15〜25 分（再学習 3 回 × 〜3 分 + Walk-Forward 12 ヶ月 × 〜1 分）
- 判定基準: 通算 ROI ≥ 0% かつ 最悪月 ≥ -50% かつ プラス月 ≥ 60%（`verdict=pass`）

設計の全体像は [MODEL_LOOP_PLAN.md](../../MODEL_LOOP_PLAN.md) を参照。

---

## 前提チェック

実行前に以下を確認。欠けていれば**即座にユーザーに質問**して止まる。

```bash
# 1. Python 3.12 が使えるか
py -3.12 --version

# 2. 依存パッケージが入っているか（lightgbm / pyyaml / pandas / scikit-learn）
py -3.12 -c "import lightgbm, yaml, pandas, sklearn; print('ok')"

# 3. データキャッシュが揃っているか（2023-01〜2026-04 の K/B/odds）
ls data/history/ | head -3
ls data/program/ | head -3
ls data/odds/ | head -3
```

依存欠落なら以下を案内:

> `pip install -r ml/requirements.txt` を実行してください（Python 3.12 環境で）。

データキャッシュ欠落なら:

> `data/history/` / `data/program/` / `data/odds/` に 2023-01〜2026-04 の K/B/オッズファイルが必要です。
> `ml/src/scripts/run_collect.py` で取得できますが、オッズは数時間かかります。

---

## 実行手順

### Step 1: 引数パース

`$ARGUMENTS` を解釈:
- 空 or `all` → pending の全 trial を順次実行
- それ以外（例: `T01_window_2024`）→ 該当 trial 1 本だけ実行

### Step 2: pending に YAML があるか確認

```bash
ls trials/pending/*.yaml 2>/dev/null
```

**YAML が無い場合**（= 既存 trial が全て completed 済み）:

1. `trials/results.jsonl` を読む
2. `primary_score` でソートし上位 trial のパラメータ近傍を探る
3. **設計フェーズに移行**:
   - 新しい trial YAML を `trials/pending/` に作成
   - スキーマは [MODEL_LOOP_PLAN.md §3-2](../../MODEL_LOOP_PLAN.md) に準拠
   - `strategy` セクションは全 trial で**統一**すること（比較可能性を保証）
4. 設計内容をユーザーに報告してから Step 3 に進む

**YAML がある場合**: そのまま Step 3 へ。

### Step 3: 実行開始をユーザーに通知

連続実行が長時間に及ぶため、開始時に以下を明示:
- 実行対象 trial 数と trial_id 一覧
- 見積もり時間（trial 数 × 20 分程度）
- 途中経過の報告はしない方針（設計書 §1-3 合意事項）

```
これから以下の trial を順次実行します。
完了まで約 N 時間、途中経過報告は最小限にとどめます。
対象: T00_baseline, T01_window_2024, ...
```

### Step 4: run_model_loop.py を実行

**全 trial 実行**:
```bash
py -3.12 ml/src/scripts/run_model_loop.py
```

**特定 trial のみ**:
```bash
py -3.12 ml/src/scripts/run_model_loop.py --trial <TRIAL_ID>
```

長時間実行になるのでバックグラウンド実行＋進捗モニタリング推奨:
- `run_in_background: true` で Bash を起動
- 定期的に `BashOutput` で標準出力の末尾を確認
- 各 trial 完了ごとに `trials/results.jsonl` が 1 行追記される

**絶対にやってはいけないこと**:
- 途中でキャンセルしない（失敗 trial は pending に残り再実行可能なので、自然完走させる）
- 並列化しない（メモリ・学習の再現性の問題）

### Step 5: 結果のまとめ読み

全 trial 完了後、`trials/results.jsonl` を読んで以下を整理:

```bash
# 最新の N 行だけ読む例（pandas 経由）
py -3.12 -c "
import json
from pathlib import Path
rows = [json.loads(l) for l in Path('trials/results.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
for r in rows[-10:]:
    kpi = r.get('kpi') or {}
    print(f\"{r['trial_id']:35s} verdict={r.get('verdict','?'):8s} \"
          f\"score={r.get('primary_score','?'):>7} \"
          f\"roi={kpi.get('roi_total','?'):>7} \"
          f\"worst={kpi.get('worst_month_roi','?'):>7} \"
          f\"plus_ratio={kpi.get('plus_month_ratio','?'):>5}\")
"
```

### Step 6: ユーザーへの報告

以下のテーブル形式で報告:

| trial_id | verdict | primary_score | roi_total | worst_month | plus_ratio | ECE(cal) |
|---|---|---|---|---|---|---|
| T00_baseline | fail | -48.3 | -13.4% | -79.5% | 50.0% | 0.1337 |
| T01_window_2024 | marginal | 2.1 | 2.1% | -45.0% | 58.3% | 0.1302 |
| ... | ... | ... | ... | ... | ... | ... |

追加情報:
- 上位 3 trial の `hypothesis` と結果の整合/不整合
- `verdict=pass` が出たか、出なかったか
- 次に探るべき方向（上位 trial の近傍 / 構造変更）

### Step 7: 次アクションの提案

判定ルール（設計書 §5 準拠）:

- **`verdict=pass` が出た** → 近傍 2〜3 本を追加設計し、確証サイクルを提案
- **上位 trial が `marginal`** → primary_score 上位の近傍を 3 本追加設計
- **5 trial 連続で baseline 比 非改善 or 10 trial 到達** → 構造変更（LambdaRank 等）フェーズへの移行を提案して一旦停止

提案は YAML として `trials/pending/` に置くだけで、すぐに実行はしない。ユーザーの GO サインを待つ。

---

## エラーハンドリング

- 1 trial が失敗しても `run_model_loop.py` は次 trial へ進む（`status=error` で `results.jsonl` に記録）
- 失敗 trial の YAML は `trials/pending/` に残るので、原因調査後に再実行可能
- traceback は `artifacts/model_loop_<trial_id>_error.log` に保存されるので Read で確認

---

## 絶対にやってはいけないこと

- ❌ `ml/configs/strategy_default.yaml` を変更する（フィルタは全 trial で統一するのが本ループの主旨）
- ❌ 複数パラメータを同時に変えた YAML を作る（原因切り分け不能。1 trial 1 仮説）
- ❌ `strategy` セクションを trial ごとに変える（モデルの効果を測れなくなる）
- ❌ GitHub Actions で実行する（本ループはローカル専用。DB 接続不要・データキャッシュ再利用のため）
- ❌ 途中で trial をキャンセルして手動再開する（pending 残存 + results.jsonl で自動再開できる設計）
- ❌ `ml/src/collector/` や `ml/src/features/` を触る（本ループの変更禁止パス、設計書 §6-4）

## 撤退条件

- 10 trial 回しても `verdict=pass` が 0 本 → モデル構造変更フェーズ（LambdaRank, 特徴量追加等）への移行を提案
- 5 trial 連続で baseline 比 `primary_score` が非改善 → 探索方向を変えるかユーザーに確認
- 実行時間が想定（1 trial 25 分）を大幅に超える → 環境問題（メモリ・データ破損）の可能性ありユーザーに報告
