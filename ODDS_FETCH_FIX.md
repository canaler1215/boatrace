# オッズ取得バグ修正（2026-04-22）

## 問題

ダッシュボードに表示されるオッズが実際のオッズと大きく乖離していた。

- 表示値: 徳山4R `2-1-3` → **325倍**
- 実際値: boatrace.jp → **7.7倍**

## 原因調査

### データフロー

```
boatrace.jp (odds3t ページ)
  ↓ fetch_odds() [openapi_client.py]
odds テーブル (race_id, combination, odds_value)
  ↓ run_predict.py
predictions テーブル (win_probability, expected_value)
  ↓ ダッシュボード
odds = expected_value / win_probability （逆算表示）
```

ダッシュボードは `predictions` テーブルに保存された `expected_value ÷ win_probability` でオッズを逆算表示している。そのため、DBに保存されているオッズが誤っていると表示値も誤った値になる。

### DBの実態

```sql
SELECT combination, odds_value, snapshot_at
FROM odds WHERE race_id = '182026042204' AND combination = '2-1-3';
-- → odds_value: 324.9, snapshot_at: 2026-04-22 00:42:48
```

- 全12レースのオッズが `00:42` の1スナップショットのみ
- `collect.yml` が9:03/9:33にも実行されていたが、オッズは更新されていなかった
- GitHub Actions ログに `WARNING: Could not parse odds table` が大量出力されていた

### コードの問題

`fetch_odds()` のパターン2（`oddsPoint` クラスベース）:

```python
# 修正前
float_values: list[float] = []
for td in odds_cells:
    v = _parse_float(td.get_text(strip=True))
    if v is not None and v > 0:
        float_values.append(v)

if len(float_values) == 120:  # ← ここが問題
    ...
```

boatrace.jp では発売中にオッズが未確定の組み合わせが `---` で表示される。
`---` は数値としてパースできないため `float_values` に追加されず、
結果として `len(float_values) < 120` となり条件を満たせずスキップされていた。

実測: 徳山4R発売中の時点で75通りのみ数値あり、残り45通りが `---`。

## 修正内容

`ml/src/collector/openapi_client.py`

```python
# 修正後: 数値セルではなく全120セルで位置チェック
if len(odds_cells) == 120:
    idx = 0
    for first in range(1, 7):
        for second in range(1, 7):
            if first == second:
                continue
            for third in range(1, 7):
                if third == first or third == second:
                    continue
                v = _parse_float(odds_cells[idx].get_text(strip=True))
                if v is not None and v > 0:
                    odds_map[f"{first}-{second}-{third}"] = v
                idx += 1
```

全120セルを位置ベースで組み合わせに割り当て、`---` のセルは `None` として読み飛ばす。
これにより発売中（一部未確定）でも確定済みの組み合わせのオッズを正しく取得できる。

## 影響範囲

- 発売締切前のオッズ取得が正常化
- `run_predict.py` が正しいオッズでEVを計算できるようになる
- ダッシュボードの表示オッズが実際の値に近くなる

## 残課題

- `predictions` テーブルにオッズ値そのものが保存されていないため、ダッシュボードは逆算表示のまま
- 発売締切後の確定オッズで `run_predict.py` を再実行する仕組みがない（現状は当日未終了レースを対象に随時実行）
