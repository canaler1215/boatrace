# Claude Code Agent ブリーフ（内ループ用）

このファイルは `.github/workflows/claude_fix.yml` によって起動される自律修正 Agent への指示書です。
人間がレビューする前提で、慎重かつ限定的な変更のみ行ってください。

---

## あなたの役割

`auto-loop` ラベル付き Issue（ROI 警戒・危険ゾーン検知）を受け取り、以下を実行する:

1. 原因分析（診断コマンドを実行して問題箇所を特定）
2. 戦略パラメータの調整案を立案（`ml/configs/strategy_default.yaml` のみ変更）
3. 修正 PR を作成して人間のレビューを待つ

---

## 分析ステップ（この順番で実行すること）

### Step 1: セグメント分析

```bash
# 直近月の combo CSV が存在する場合
python ml/src/scripts/run_segment_analysis.py \
  --combos-csv artifacts/combos_YYYYMM.csv

# 存在しない場合はバックテストから再生成
python ml/src/scripts/run_backtest.py \
  --year YYYY --month MM --real-odds \
  --prob-threshold 0.07 --ev-threshold 2.0 \
  --exclude-courses 2 --min-odds 100 --exclude-stadiums 11
```

注目すべき出力:
- コース別 ROI（特定コースが著しく低い → `exclude_courses` 追加候補）
- 場別 ROI（特定場が著しく低い → `exclude_stadiums` 追加候補）
- 確率帯別 ROI（低確率帯が足を引っ張っている → `prob_threshold` 引き上げ候補）
- EV 帯別 ROI（低 EV 帯が悪い → `ev_threshold` 引き上げ候補）

### Step 2: キャリブレーション確認

```bash
python ml/src/scripts/run_calibration.py \
  --year YYYY --month MM
```

注目すべき出力:
- ECE（Expected Calibration Error）が直近より大幅悪化 → モデル再学習を推奨
- 1着実際的中率が確率ビンと大きく乖離 → prob_threshold 見直し

### Step 3: KPI 履歴の確認

```bash
cat artifacts/kpi_history.jsonl | python -c "
import sys, json
rows = [json.loads(l) for l in sys.stdin if l.strip()]
for r in rows[-6:]:
    print(f\"{r['period']} zone={r['zone']} ROI={r['roi_pct']:+.1f}%\")
"
```

---

## 変更してよい場所

| ファイル | 変更内容 |
|---------|---------|
| `ml/configs/strategy_default.yaml` | 購入フィルタ・賭け金管理パラメータ |
| `ml/configs/strategy_*.yaml` | 新しい戦略バリエーション（新規作成可） |

## 変更してはいけない場所

| パス | 理由 |
|------|------|
| `ml/src/collector/` | データ取得ロジック — 変更は本番データに影響 |
| `ml/src/features/` | 特徴量定義 — モデルの入力形式が変わる |
| `ml/src/model/trainer.py` | 学習コード — 意図しない学習崩壊のリスク |
| `ml/src/model/predictor.py` | 推論コード — 確率の意味が変わる |
| `ml/migrations/` | DB スキーマ — 本番 DB を破壊するリスク |
| `.github/workflows/` | CI/CD — 無限ループや権限昇格のリスク |
| `CLAUDE.md`, `AUTO_LOOP_PLAN.md` | ドキュメント — 人間が管理 |

---

## パラメータ調整ガイドライン

### `prob_threshold`（確率閾値）

- 現在値: `0.07`（7%）
- 調整範囲: `0.05` 〜 `0.12`
- 上げると: ベット数減少、平均的中率向上、ROI 向上期待（ただしサンプル数減）
- 下げると: ベット数増加、統計的安定性向上

### `ev_threshold`（期待値閾値）

- 現在値: `2.0`
- 調整範囲: `1.5` 〜 `3.0`
- 上げると: 高 EV ベットのみ残る（ベット数大幅減）
- 下げると: ベット数増加（低 EV ノイズも含まれる）

### `exclude_courses`（除外コース）

- 現在値: `[2]`
- 変更根拠: セグメント分析でコース別 ROI が他コースより著しく低い場合
- 注意: `BET_RULE_REVIEW_202509_202512.md` によるとコース4/5除外は逆効果の検証結果あり。単純に除外しないこと

### `exclude_stadiums`（除外場）

- 現在値: `[11]`（びわこ）
- 変更根拠: 場別 ROI が −50% 以下かつ 100 ベット以上のサンプルがある場合のみ追加

### `min_odds`（最低オッズ）

- 現在値: `100.0`
- 調整範囲: `50` 〜 `200`
- 高オッズ戦略（宝くじ型）を維持するため、この値を大幅に下げないこと

---

## PR 作成ルール

1. ブランチ名: `auto-loop/fix-YYYYMM-<brief-description>`
2. PR タイトル: `[auto-loop] YYYY-MM ROI 改善案: <変更内容の要約>`
3. PR 本文に必ず含めること:
   - 変更前後のパラメータ比較表
   - 分析根拠（どの指標が悪かったか）
   - 想定される効果（定量的に）
   - 懸念事項・副作用
4. ラベル: `auto-loop-candidate`
5. レビュアー: リポジトリオーナーにアサイン

---

## 撤退条件

以下の場合は PR を作成せず、Issue にコメントして終了する:

- セグメント分析で特定できる問題が見つからない（全セグメントが悪い）
- キャリブレーション ECE が直近比 +20% 以上悪化している（→ モデル再学習が必要）
- 3 イテレーション経過してもROI が改善しない
- 変更すべきパラメータが「変更してはいけない場所」に属する

撤退時のコメント例:
```
原因分析の結果、戦略パラメータの調整では改善できない問題が見つかりました。
推奨アクション: `run_retrain.py` によるモデル再学習
詳細: [分析結果の要約]
```

---

## 最大イテレーション数

**3回**（Issue での往復を含む）。3回試行して改善しない場合は `wontfix` ラベルを付けてクローズする。
