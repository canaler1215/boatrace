# 3連複 追加実装計画

## 背景・目的

現行システムは3連単（120通り、平均的中オッズ586x）のみを対象とする高オッズ宝くじ戦略。
3連複（20通り、平均オッズ推定60-80x）を追加することで、同一モデルから以下を期待する。

- 3連単と同等の絞り込み戦略が通用するか検証
- 3連単非的中でも3連複的中となる「順番外れ」をリカバリー
- ベット点数の増加なしに的中機会を増やす（3連単との相互補完）

## 調査結果サマリー（2026-04-19）

| 指標 | 3連単（現行） | 3連複（追加候補） |
|------|------------|--------------|
| 組合せ数 | 120通り | 20通り |
| 理論的中率 | 0.83% | 5.0% |
| 典型オッズ | 50-1,000x | 10-200x |
| S6-3 実績ROI | +794.9% | 未検証 |
| モデルエッジ | 確認済み（24ヶ月全月プラス） | 要バックテスト |
| 払戻率 | 74.8% | 74.8% |

### 優先度判定

| 賭式 | 優先度 | 理由 |
|------|--------|------|
| **3連複** | **高** | Plackett-Luce流用可、オッズ構造が現行戦略と適合 |
| 単勝 | 中 | top1_accuracy 31.2% のエッジあり、低オッズが課題 |
| 複勝 | 低 | オッズ1-5xでは構造的に高ROIが困難 |

---

## 詳細設計（2026-04-19 確定）

### T1: `calc_trio_probs()` — `ml/src/model/predictor.py`

既存の `calc_trifecta_probs` の直後に追加する。

```python
def calc_trio_probs(win_probs: np.ndarray) -> dict[str, float]:
    """3連複確率をPlackett-Luceで計算。キーはソート済み艇番文字列 "1-2-3"。"""
    p = win_probs / win_probs.sum()
    boats = list(range(1, 7))
    result = {}
    for combo in itertools.combinations(boats, 3):
        key = "-".join(map(str, combo))
        prob = 0.0
        for perm in itertools.permutations(combo):
            a, b, c = perm[0]-1, perm[1]-1, perm[2]-1
            denom_b = 1.0 - p[a]
            denom_c = 1.0 - p[a] - p[b]
            if denom_b > 0 and denom_c > 0:
                prob += p[a] * (p[b] / denom_b) * (p[c] / denom_c)
        result[key] = prob
    return result  # 20エントリ、合計≒1.0
```

- 出力形式: `{"1-2-3": 0.045, ...}`（キー: ソート済み艇番、20通り）
- `calc_expected_values()` は汎用関数のためそのまま流用可能

### T2: `fetch_trio_odds()` — `ml/src/collector/openapi_client.py`

既存の `fetch_odds`（`/odds3t`）と対称的に実装する。

- エンドポイント: `/odds3f`（3連複オッズページ、boatrace.jp）
- HTMLパース: `data-combination` 属性優先、fallback は順列ベース
- 返却形式: `{"1-2-3": 15.2, ...}` 全20通り
- **注意**: `odds3f` ページの `data-combination` がソート済みか未確認。ソートされていない場合は `"-".join(sorted(combo.split("-")))` で正規化する

### T3: `load_or_download_month_trio_odds()` — `ml/src/collector/odds_downloader.py`

既存の `load_or_download_month_odds` と並行して追加する。

- キャッシュパス: `data/odds/trio_odds_YYYYMM.parquet`
- ダウンロード: `fetch_trio_odds()` を ThreadPoolExecutor（max_workers=10）で並列呼び出し
- チェックポイント保存・再開ロジックは既存実装を流用

### T4: `bet_type` パラメータ — `ml/src/backtest/engine.py`

`run_race` と `run_backtest_batch` に `bet_type: str = "trifecta"` を追加する。

| 処理 | `trifecta`（現行） | `trio`（追加） |
|------|-----------------|-------------|
| 確率計算 | `calc_trifecta_probs()` | `calc_trio_probs()` |
| EV計算 | `calc_expected_values()` | 同じ関数（trio probs/odds で） |
| オッズ入力 | `race_odds`（120通り） | `trio_race_odds`（20通り） |
| 的中判定 | `actual_combo == combo` | `frozenset(actual.split("-")) == frozenset(combo.split("-"))` |
| 組合せ数 | 120 | 20 |

的中判定ロジック（trio 用）:

```python
def _is_trio_hit(actual_combo: str | None, trio_combo: str) -> bool:
    if actual_combo is None:
        return False
    return frozenset(actual_combo.split("-")) == frozenset(trio_combo.split("-"))
```

`combo_records` には `bet_type` フィールドを追加し、3連単/3連複を区別する。

### T5: `--bet-type` オプション — `ml/src/scripts/run_backtest.py` / `run_walkforward.py`

```
--bet-type {trifecta,trio,both}  デフォルト: trifecta
```

- `both` 指定時は同一レースで両方計算し、結果を別々に集計・表示する
- `run_walkforward.py` も同様に対応

### EV・購入フィルタ方針

3連複は理論的中率が5%（3連単の6倍）のため閾値を調整する。

| パラメータ | 3連単（現行） | 3連複（提案初期値） |
|-----------|------------|----------------|
| `--prob-threshold` | 7% | **10〜15%** |
| `--ev-threshold` | 2.0 | **2.0 維持** |
| `--min-odds` | 100x | **10x（新設）** |
| コース除外 | 2/4/5 | パイロット後に検討 |

---

## バックテスト計画

### Step 1: 最小実装でのパイロット検証

- 期間: 2025-10〜12（3ヶ月、S6-3の短期比較区間と同一）
- モデル: 現行 S6 モデル（softmax_calibrators）
- 目標指標: ROI > 0%、的中率 > 5%（理論値）

### Step 2: 長期 Walk-Forward

- 期間: 2024-01〜2025-12（S6-3 と同一の24ヶ月）
- 比較: 3連単単独 vs 3連複単独 vs 両方の組み合わせ
- 追加確認: 月次ROIの安定性（3連単より分散が小さいか）

### Step 3: 組み合わせ戦略の検討

- 3連単ヒット → 3連複も自動的にヒット（相関関係の確認）
- 3連複のみヒット（3連単は外れ）の件数と払戻額の分析
- 両賭式を同時に購入する場合の資金配分

---

## 実装タスク・実装順序

T1〜T5 は順次依存のため直列実装。T6 以降はコード変更なし（実行のみ）。

```
T1 predictor.py
  ↓
T2 openapi_client.py
  ↓
T3 odds_downloader.py
  ↓
T4 engine.py
  ↓
T5 run_backtest.py / run_walkforward.py
  ↓
T6 パイロットバックテスト（2025-10〜12）
  ↓
T7 長期Walk-Forward（2024-01〜2025-12）
  ↓
T8 CLAUDE.md 更新
```

### チェックリスト

- [x] T1: `calc_trio_probs()` を `ml/src/model/predictor.py` に追加
- [x] T2: `fetch_trio_odds()` を `ml/src/collector/openapi_client.py` に追加（`odds3f` パース確認含む）
- [x] T3: `load_or_download_month_trio_odds()` を `ml/src/collector/odds_downloader.py` に追加
- [ ] T4: `ml/src/backtest/engine.py` に `bet_type` パラメータ・3連複的中判定を追加
- [ ] T5: `ml/src/scripts/run_backtest.py` / `run_walkforward.py` に `--bet-type` オプション追加
- [ ] T6: パイロットバックテスト実行（2025-10〜12、`--bet-type trio --prob-threshold 0.10`）
- [ ] T7: 長期Walk-Forward実行（2024-01〜2025-12）
- [ ] T8: 結果をCLAUDE.mdに反映

---

## 懸念事項・リスク

| リスク | 内容 | 対策 |
|--------|------|------|
| モデルエッジ不足 | 1着識別がランダムなら top-3 識別も弱い可能性 | Step 1で早期検証 |
| オッズ重複 | 3連複オッズの解析方法がboatrace.jpで変更されている可能性 | Step 2以前に `fetch_trio_odds` のHTMLパースを確認 |
| 購入ルール未調整 | prob閾値/EV閾値が3連複に不適切な可能性 | グリッドサーチで最適化 |
| 3連複の排除対象 | コース除外・場除外が3連複に適用可能か未確認 | Step 1の分析時に検討 |
