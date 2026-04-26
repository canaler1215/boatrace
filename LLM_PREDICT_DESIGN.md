# Claude Code 競艇予想システム — スキル設計書

**作成日**: 2026-04-26
**目的**: Claude Code（Max プラン内）で毎レース予想する仕組みを構築する
**前提**: API 課金は使わない（Max プラン内で完結）。実用可能性が見えた段階で API バッチ化を検討

---

## 0. 背景

`CLAUDE.md`「現行の運用方針」の通り、

- フェーズ 3 `/inner-loop`（フィルタ探索）凍結
- フェーズ 6 `/model-loop`（モデル構造ループ）完全撤退
- フェーズ 7 (B-1) 3 連単市場効率分析 完全撤退
- フェーズ B-3（単勝市場効率分析）は別セッションで着手予定

ML 系の改善ループはすべて停止状態にあり、「アルゴリズム的な確率推定 → EV 判定」の枠組みでは
out-of-sample 黒字化に到達できないと判断された。次の打ち手として **判断アルゴリズムごと
LLM（Claude）に置き換える** 方針を採用する。

評価インフラ（`run_walkforward.py` / `engine.py` / `evaluate_predictions`）と
データ収集層（`collector/`）は流用可能なため、再利用する。

---

## 1. 全体像

```
[夜間 22:00 頃]               [当日 締切 30 分前]            [翌日 朝]
/prep-races              →    /predict              →    /eval-predictions
レースカード生成              展示+オッズ追加→予想         結果突合・ROI集計
program / history DL          直前情報 DL                  K ファイル DL
   ↓                            ↓                            ↓
artifacts/race_cards/       artifacts/predictions/      artifacts/eval/
  2026-04-27/                 2026-04-27/                 2026-04-27.json
    01_05.md                    01_05.json
    01_06.md                    ...
    index.md
```

3 段階に分ける理由は、**直前オッズと展示タイムは締切直前にしか確定しない**ため。
夜間に「下準備」、当日に「予想本番」、翌朝に「答え合わせ」の運用。

---

## 2. 運用形態

`CLAUDE.md` 記載の運用案より:

- **B. 注目レースに絞る（SG/G1/特定場）**: 1 日 ~10〜20 レース
- **D. 夜間自動実行**: 翌日のレースカードを準備（複数会場指定可能）

### 想定タイムライン

| 時刻 | 操作 | スキル |
|---|---|---|
| 前日 22:00 頃 | 翌日の対象会場を指定して下準備 | `/prep-races` |
| 当日 各レース 30 分前 | 展示・オッズ取得 → 予想出力 | `/predict` |
| 当日 各レース後 | （任意）結果確認 | `/eval-predictions` |
| 翌朝 | 全レース結果集計 | `/eval-predictions` |

---

## 3. スキル一覧

### 3.1 `/prep-races` — 夜間レースカード準備

**用途**: 翌日の指定会場のレースカード（program + history 集計まで）を生成

**引数**:
```
/prep-races <YYYY-MM-DD> <会場1> [会場2] [会場3] ...
```

**例**:
```
/prep-races 2026-04-27 桐生 平和島 住之江
/prep-races 2026-04-27 01 04 12              # 場 ID でも可
/prep-races 2026-04-27 蒲郡                  # 単会場
```

**動作**:
1. `program_downloader` で指定会場・指定日の出走表を DL（未取得分のみ）
2. 各レーサーの過去 history（直近 10 走 + 当地直近 6 走）を集計
3. レースカード Markdown を `artifacts/race_cards/<YYYY-MM-DD>/<場ID>_<R>.md` に書き出し
4. `index.md` にその日の全レース一覧を生成（場ごとに 12R）

**この時点では取得しない**: 直前オッズ、展示タイム、直前気象（締切直前にしか出ないため）

---

### 3.2 `/predict` — 予想本番

**用途**: 用意済みレースカードに直前情報を追加して、Claude が予想を出す

**引数（3 形態）**:
```
/predict <YYYY-MM-DD>                      # その日の prep 済み全レース
/predict <YYYY-MM-DD> <会場>                # 1 会場の 12R
/predict <YYYY-MM-DD> <会場> <R>            # 単発
```

**例**:
```
/predict 2026-04-27
/predict 2026-04-27 桐生
/predict 2026-04-27 桐生 5
```

**動作**:
1. レースカード読み込み（なければ「`/prep-races` を先に実行してください」とエラー）
2. **直前情報の追加 DL**: 展示タイム、進入予想、オッズ（3 連単/単勝）、直前気象
3. レースカードに直前情報を追記
4. Claude が分析 → 予想 JSON 出力
5. `artifacts/predictions/<日付>/<場ID>_<R>.json` に保存
6. ターミナルに買い目サマリーを表示

**Claude の出力 JSON スキーマ**:
```json
{
  "race_id": "2026-04-27_01_05",
  "predicted_at": "2026-04-27T10:55:00+09:00",
  "model": "claude-opus-4-7",
  "analysis": "1号艇山田は当地67%、モーター32%で平均以上。2号艇佐藤の平均ST 0.13 がイン威圧。3コース以下は弱い。本線 1-2、ヒモ 3-4-6...",
  "primary_axis": [1, 2],
  "verdict": "bet",
  "skip_reason": null,
  "bets": [
    {
      "trifecta": "1-2-3",
      "stake": 100,
      "current_odds": 8.2,
      "expected_prob": 0.18,
      "ev": 1.48,
      "confidence": 0.7
    }
  ]
}
```

**買い目決定ルール（初期版）**:
- 1 レース最大 5 点、最大 500 円
- `verdict: "skip"` で見送り可（自信ない / オッズ妙味なし）
- ステークは初期 100 円固定
- `expected_prob` × `current_odds` ≥ 1.0 を Claude に意識させる（厳密な閾値判定はしない）

---

### 3.3 `/eval-predictions` — 結果評価

**用途**: 確定後の K ファイルを使って、予想 vs 結果を突合

**引数**:
```
/eval-predictions <YYYY-MM-DD>
```

**動作**:
1. `history_downloader` でその日の K ファイル DL
2. `artifacts/predictions/<日付>/*.json` を全部読む
3. 各買い目の的中可否・払戻を計算
4. サマリー JSON を `artifacts/eval/<日付>.json` に書き出し
5. ターミナルに ROI / 的中率 / 会場別成績を表示

**累積評価**: 別途 `/eval-summary [--from YYYY-MM-DD] [--to YYYY-MM-DD]` で複数日合算（後フェーズ）

---

## 4. レースカード仕様（Markdown）

`artifacts/race_cards/2026-04-27/01_05.md` の例:

```markdown
# 2026-04-27 桐生 5R

## レース情報
- レース名: 一般戦
- 距離: 1800m
- 締切時刻: 11:23

## 出走表

### 1号艇（白）山田太郎 (4567)
- A1級 / 35歳 / 52.0kg / 香川支部
- 全国: 勝率 6.85 / 2連 50.2% / 3連 70.1%
- 当地: 勝率 7.20 / 2連 55.0% / 3連 75.3%
- F0 / L0 / 平均ST 0.15
- モーター 12 号: 勝率 32.4% / 2連 45.1%
- ボート 34 号: 勝率 5.50

#### 直近 10 走（全国）
| 日付 | 場 | R | 着順 | コース | ST |
|---|---|---|---|---|---|
| 04-25 | 桐生 | 12 | 1 | 1 | 0.14 |
| 04-24 | 桐生 | 9 | 2 | 1 | 0.16 |
| ...

#### 当地直近 6 走（桐生）
| 日付 | R | 着順 | コース | ST |
|---|---|---|---|---|
| ...

### 2号艇（黒）...
（以下 6 艇）

## 場特性
- 桐生: 1コース勝率 49.2%（全国平均 53.1% より弱インコース傾向）
- まくり / まくり差しが決まりやすい

---

## ▼ 直前情報（/predict 実行時に追記）
- 風向 / 風速 / 波高 / 気温 / 水温
- 展示タイム（6 艇）
- スタート展示の進入コース・ST
- オッズ（3連単 上位 20 / 単勝 6 艇）
```

**サイズ目安**: 1 レース ~3〜5 KB。1 ターンで 6 レース程度（~30 KB）まで現実的。

---

## 5. ディレクトリ構造

```
.claude/commands/
  prep-races.md            ← 新規
  predict.md               ← 新規
  eval-predictions.md      ← 新規

ml/src/scripts/
  build_race_cards.py      ← 新規（prep-races の本体）
  fetch_pre_race_info.py   ← 新規（predict 用、展示・直前オッズ取得）
  evaluate_predictions.py  ← 新規（eval-predictions の本体）

ml/src/predict_llm/        ← 新規ディレクトリ（既存 model/ と分離）
  __init__.py
  race_card_builder.py     ← レースカード Markdown 生成
  history_summarizer.py    ← 直近 N 走の集計
  prediction_schema.py     ← 予想 JSON のバリデーション (pydantic)
  stadium_resolver.py      ← 場名⇔ID 解決

artifacts/
  race_cards/<date>/       ← prep-races 出力
  predictions/<date>/      ← predict 出力
  eval/<date>.json         ← eval-predictions 出力
```

既存 `ml/src/collector/` `ml/src/features/` `ml/src/backtest/` には触らない（流用のみ）。
既存 `ml/src/model/`（LightGBM 系）も触らない。

---

## 6. 会場指定の解決方法

`stadium_resolver.py` ヘルパで以下を双方向解決:

| ID | 名称 | 別名 |
|---|---|---|
| 01 | 桐生 | きりゅう |
| 02 | 戸田 | とだ |
| 03 | 江戸川 | えどがわ |
| 04 | 平和島 | へいわじま |
| 05 | 多摩川 | たまがわ |
| 06 | 浜名湖 | はまなこ |
| 07 | 蒲郡 | がまごおり |
| 08 | 常滑 | とこなめ |
| 09 | 津 | つ |
| 10 | 三国 | みくに |
| 11 | びわこ | びわこ |
| 12 | 住之江 | すみのえ |
| 13 | 尼崎 | あまがさき |
| 14 | 鳴門 | なると |
| 15 | 丸亀 | まるがめ |
| 16 | 児島 | こじま |
| 17 | 宮島 | みやじま |
| 18 | 徳山 | とくやま |
| 19 | 下関 | しものせき |
| 20 | 若松 | わかまつ |
| 21 | 芦屋 | あしや |
| 22 | 福岡 | ふくおか |
| 23 | 唐津 | からつ |
| 24 | 大村 | おおむら |

入力は **日本語名 / ID（数字 1〜24）/ ゼロ埋め ID（"01"〜"24"）** いずれも受け付ける。

---

## 7. 自動化（夜間バッチ）— 後付けで OK

実装当初は手動 `/prep-races` で運用。慣れてきたら以下で自動化:

```
/schedule create "0 22 * * *" "/prep-races $(date -d tomorrow +%Y-%m-%d) 桐生 平和島"
```

会場リストはセッションごとにユーザーが書き換える運用（G1 開催に応じて）。

---

## 8. 実装フェーズ

| フェーズ | 内容 | 完了基準 | 状態 |
|---|---|---|---|
| **P1 基盤** | `race_card_builder.py` + `/prep-races` skill | 1 会場 1 日のカード生成成功 | ✅ **2026-04-26 完了** |
| **P2 予想** | `fetch_pre_race_info.py` + `/predict` skill | 1 レース予想 JSON 出力成功 | ✅ **2026-04-26 完了** |
| **P3 評価** | `evaluate_predictions.py` + `/eval-predictions` skill | 1 日分の ROI 算出成功 | ✅ **2026-04-27 完了** |
| **P4 運用** | 複数会場対応、index.md、会場名解決 | `/prep-races 2026-04-27 桐生 平和島 住之江` 成功 | （P1 で前倒し実装済み） |
| **P5 自動化** | `/schedule` 連携（任意） | 夜間自動 prep | — |

P1〜P3 を最小スコープで動かして、ユーザーが実際に使ってフィードバックをもらう想定。

### P1 完了メモ（2026-04-26）

実装ファイル:

- [ml/src/predict_llm/__init__.py](ml/src/predict_llm/__init__.py)
- [ml/src/predict_llm/stadium_resolver.py](ml/src/predict_llm/stadium_resolver.py)
- [ml/src/predict_llm/program_parser.py](ml/src/predict_llm/program_parser.py) — **独自 B ファイルパーサ**（既存 `collector/program_downloader.py:parse_program_file` は LightGBM 用最小列のみのため、年齢・支部・体重・全国2連率・当地勝率/2連率・モーター/ボート NO・レース名・距離・締切時刻まで取得する独自実装を新設）
- [ml/src/predict_llm/history_summarizer.py](ml/src/predict_llm/history_summarizer.py) — 既存 K ファイルキャッシュを `parse_result_file` で読み、racer_id ごとに直近走を集計（DL は呼ばない）
- [ml/src/predict_llm/race_card_builder.py](ml/src/predict_llm/race_card_builder.py) — Markdown 生成 + index.md
- [ml/src/scripts/build_race_cards.py](ml/src/scripts/build_race_cards.py) — CLI
- [.claude/commands/prep-races.md](.claude/commands/prep-races.md) — スキル定義

動作確認パス（成果物 = `artifacts/race_cards/<日付>/`）:

| 呼び出し | 結果 |
|---|---|
| `/prep-races 2026-04-25 桐生` | 12 ファイル + index.md |
| `/prep-races 2026-04-27 桐生 平和島`（**桐生休場**） | 平和島 12 + index = 13 ファイル + 桐生休場警告 |
| `/prep-races 2025-12-01 桐生 平和島 多摩川`（過去日 + **平和島休場**） | 桐生 12 + 多摩川 12 + index = 25 ファイル + 平和島休場警告 |

実装中の発見と対応:

1. **R10〜R12 のレースヘッダー行は先頭の全角スペースが無い**（既存 collector 側
   `_B_RACE_HDR_RE = ^[\s　]+([１-９][０-９]?)Ｒ` でも同問題。本パーサは
   `^[\s　]*` に変更して回避）。
2. **福岡（場 22）でボート NO が 3 桁になると `25.00161` のようにモーター 2 率と連結する**
   （`\d+\.\d+` greedy が `25.00161` 全体を食う）。各率の小数部を **2 桁固定** `\d+\.\d{2}`
   にして解消。
3. **「コース」（進入）は既存 K ファイルパーサが抽出していない**ため、レースカードでは
   「艇番」で代用（妥協、後フェーズで `predict_llm/` 内に独自 K ファイルパーサを
   追加すれば解消可能）。
4. **節間着順 / F 数 / L 数 / 平均 ST（B ファイル末尾連結フィールド）は意味推定が必要**
   なため P1 では非表示。代わりに history （直近 N 走）の `start_timing` 平均を
   「平均 ST」として算出表示。
5. **休場会場は警告 + skip**（強制エラーにしない）。`/prep-races 2026-04-27 桐生 平和島`
   のように当日休場場を含む呼び出しでも、開催場分は出力される。

サイズ実績: 1 レース MD = ~7 KB（打ち切り基準 10 KB 内）。1 日 24 場 × 12R 全部生成しても
ディスク ~1.7 MB 程度で運用上問題なし。

### P1 のスコープ（最小）

- `predict_llm/stadium_resolver.py`: 場名⇔ID 解決ヘルパ
- `predict_llm/history_summarizer.py`: 直近 N 走 / 当地直近 N 走の集計
- `predict_llm/race_card_builder.py`: program + history → Markdown 生成
- `scripts/build_race_cards.py`: CLI エントリポイント
- `.claude/commands/prep-races.md`: スキル定義
- 動作確認: `/prep-races 2026-04-27 桐生` で 12 レース分の MD 生成

### P2 のスコープ

- `scripts/fetch_pre_race_info.py`: 展示・直前オッズ・直前気象 DL
- `predict_llm/prediction_schema.py`: 予想 JSON のバリデーション (pydantic)
- `.claude/commands/predict.md`: スキル定義（Claude 自身が race card を読んで予想 JSON 出力）
- 動作確認: `/predict 2026-04-27 桐生 5` で 1 レース予想 JSON 出力

### P2 完了メモ（2026-04-26）

実装ファイル:

- [ml/src/predict_llm/pre_race_fetcher.py](ml/src/predict_llm/pre_race_fetcher.py) — 直前情報取得 (live: boatrace.jp / past: cache + K)
- [ml/src/predict_llm/prediction_schema.py](ml/src/predict_llm/prediction_schema.py) — 予想 JSON のバリデーション
  （**設計時の `pydantic` から `dataclass + 自前 validate` に変更**: pydantic 未インストール、Max プラン内完結の趣旨に沿って軽量化）
- [ml/src/scripts/fetch_pre_race_info.py](ml/src/scripts/fetch_pre_race_info.py) — CLI（race card MD に直前情報追記、過去日対応、`*_pre.json` ダンプ）
- [ml/src/scripts/build_predictions_index.py](ml/src/scripts/build_predictions_index.py) — index.json 集約 CLI（スキーマ検証込み）
- [.claude/commands/predict.md](.claude/commands/predict.md) — スキル定義

実装上の判断（合意済み）:

1. **直前情報取得方式**: 既存 `openapi_client.py` の `fetch_before_info` / `fetch_odds` /
   `fetch_win_odds` を流用、気象（波高・気温・水温）のみ独自スクレイプ追加
2. **過去日ドライラン優先**: `data/odds/odds_YYYYMM.parquet` キャッシュ + K ファイル気象。
   展示・進入は欠損（"過去日のため取得不能" 注記）
3. **race card MD は上書き**: `## ▼ 直前情報 (...)` プレースホルダを実データセクションに置換、冪等
4. **方式 A**: Claude が race card MD を Read → 分析 → Write で JSON
5. **ガードレールゼロ**: skip 判定は Claude の自由判断、後付けフィルタなし
6. **index.json は CLI 責務**: 末尾で `build_predictions_index.py` が集約

動作確認パス（成果物 = `artifacts/predictions/<日付>/`）:

| 呼び出し | 結果 |
|---|---|
| `fetch_pre_race_info.py 2025-12-01 桐生 1` | 1 レース更新、3 連単 120/単勝 6/気象 K ファイル取得 OK |
| `fetch_pre_race_info.py 2025-12-01 桐生` | 12 レース更新（mode=past 全成功） |
| Claude が `01_01.json` 〜 `01_12.json` を Write | 12 件すべて pydantic 相当バリデーション pass |
| `build_predictions_index.py 2025-12-01 --strict` | total=12 valid=12 bet=12 skip=0 invalid=0 |

実装中の発見と対応:

1. **pydantic 未インストール**: 設計書 §3.2 では pydantic だが、新規依存追加を避け
   `dataclass + 手書き validate` に変更。スキーマ検証は十分機能（race_id 形式・trifecta 重複・
   verdict と bets/skip_reason の整合性まで検査）
2. **boatrace.jp `beforeinfo` の気象パース**: HTML 構造観察ベースで実装。風向は
   `is-windN` クラス、気温/水温/波高は文字列正規表現 (`気温\s*([\d.]+)`) で抽出
3. **過去日では `beforeinfo` を呼ばない**: K ファイル `weather`/`wind_direction`/`wind_speed`
   のみで代用、波高・気温・水温は欠損 (None)
4. **race card 上書きの冪等性**: `## ▼ 直前情報 (/predict 実行時に追記)` プレースホルダが
   消えていても、既存 `## ▼ 直前情報` ヘッダから末尾を再生成して冪等

サイズ実績: 直前情報セクションは 1 レース ~30 行追加（~1.5 KB）。1 レース MD =
~7 KB → ~8.5 KB と打ち切り基準 10 KB 内で収まる。

### P3 のスコープ

- `scripts/evaluate_predictions.py`: 予想 vs 実績の突合
- `.claude/commands/eval-predictions.md`: スキル定義
- 動作確認: `/eval-predictions 2026-04-27` で日次 ROI 算出

### P3 完了メモ（2026-04-27）

実装ファイル:

- [ml/src/scripts/evaluate_predictions.py](ml/src/scripts/evaluate_predictions.py) — CLI（K ファイル + parquet キャッシュ + 当日 raceresult 突合 → ROI 集計）
- [.claude/commands/eval-predictions.md](.claude/commands/eval-predictions.md) — スキル定義

実装上の判断（着手前合意済み）:

1. **実績データ取得**: 過去日 = K ファイル `parse_result_file` の `finish_position`
   + `data/odds/odds_YYYYMM.parquet` のオッズ。当日 = `fetch_race_result_full`
   （`trifecta_combination` + `trifecta_payout / 100` を `actual_odds` として使用）
2. **引数仕様**: P3 は単日 + 単会場まで。`--from`/`--to` の累積は P3.5 で別実装
3. **的中判定**: 単純な文字列一致（`bet.trifecta == actual_combination`）。
   3 連単はソート不要
4. **集計指標**: 必須指標（的中率/ROI/見送り率/平均 confidence） +
   confidence 帯別 ROI（`[0.0-0.3, 0.3-0.5, 0.5-0.7, 0.7-1.0]`） + 場別 ROI。
   skip の if-bet 参考集計は P3.5 以降
5. **ステータス分類**: `settled` / `skipped_by_claude` / `no_result` の 3 種で
   見送り率と no_result を区別
6. **engine.py 流用しない**: 既存の `_is_trio_hit` は 3 連複用、本件は文字列一致で
   足りるので独自実装で完結（約 500 行）
7. **K ファイル不在時**: `download_day_data` で自動 DL を試行（既存呼び出すだけ）
8. **payout 計算**: 過去日 = parquet オッズ × stake、当日 = `payout_yen / 100 × stake`、
   どちらも取れない場合は Claude の `current_odds` × stake にフォールバック
   （`payout_source` で記録）
9. **odds_drift_pct**: Claude の `current_odds` と実 actual_odds の乖離を JSON に
   保存（集計には影響しない、後解析用）
10. **連続 5 レース失敗で警告**: ログのみ。途中で止めない

動作確認パス（成果物 = `artifacts/eval/<日付>.json` / `<日付>_<場ID>.json`）:

| 呼び出し | 結果 |
|---|---|
| `evaluate_predictions.py 2025-12-01 桐生` | 12 races settled, 17 bets, 1 hit (7R `1-3-5` @ 7.2x), ROI -57.6%, hit_rate/bet 5.88% |

手計算検証（`artifacts/eval/2025-12-01_01.json`）:

- 7R: actual=`1-3-5`, bet=`1-3-5` → `is_hit=true`, `payout = 100 × 7.2 = 720` ✓
- 1R: actual=`3-1-4`, bet=`1-4-3` → `is_hit=false`, `payout=0` ✓
- 集計: 720 / 1700 - 1 = -0.5765 ≈ -57.6% ✓
- confidence 0.5-0.7 帯（lo ≤ x < hi）: 6 bets, 1 hit, ROI +20.0% ✓
- `odds_drift_pct=0.0` 全件 → Claude が race card の parquet オッズをそのまま
  コピーしているため一致、設計通り

実装中の発見と対応:

1. **race_id 形式の不一致**: 予想 JSON は `YYYY-MM-DD_NN_RR`（P2 形式、12 桁ではない）
   なのに対し、K ファイル / parquet は `NNYYYYMMDDRR`（12 桁）。
   `_make_kfile_race_id()` で変換。
2. **K ファイル race_id は finish 全 6 艇分が必要**: `_finish_to_combo` は
   1〜3 着のキーが揃わないと None を返す（DNF/失格レースの安全側処理）
3. **当日モードでの bet 別 actual_odds**: `fetch_race_result_full` は的中組合せの
   payout しか返さないので、外れベットの actual_odds は None。
   過去日 parquet モードでは全組合せ取れるのでベットごとに記録可能
4. **見送り率の分母**: `n_decided = n_bet_races + n_skipped_by_claude` とし、
   `no_result` は分母から除外（実績取得不能を見送り率に算入すると Claude の
   判断とインフラ側問題が混ざるため）

サイズ実績: 1 日 12 レースで eval JSON ~20 KB、1 ヶ月（~700 レース想定）でも
~1.2 MB に収まる。

### P3.5 完了メモ（2026-04-27）

実装ファイル:

- [ml/src/scripts/eval_summary.py](ml/src/scripts/eval_summary.py) — CLI（期間内の `<日付>.json` を集約 → 月次・場別・confidence 帯別 ROI + 判定ステータス）
- [.claude/commands/eval-summary.md](.claude/commands/eval-summary.md) — スキル定義

実装上の判断（着手前合意済み・1〜10）:

1. **入力選別**: `<日付>.json`（場フィルタなし版）のみ採用。`<日付>_<NN>.json`
   は二重計上回避のため除外（P4 で別途）
2. **引数仕様**: `--from`/`--to` 必須 + `--month YYYY-MM` 糖衣構文。
   単日ショートカットは P3 で済むので無し
3. **必須指標**: 期間 ROI / 月次トレンド / 場別累積 + 場×月クロス /
   confidence 帯別（P3 と同境界 `[lo, hi)`）/ 全体 hit_rate / avg_conf /
   日次・月次 ROI 統計（min/median/mean/max/stddev + worst/best）
4. **任意指標**: bootstrap CI のみ採用（N=1000、bet 単位リサンプル、
   `--no-bootstrap` で無効化）。Spearman 相関 / primary_axis 別は P4 以降
5. **判定ステータス**: `production_ready` (ROI ≥ +10% & worst > -50% & CI下限 ≥ 0)
   / `breakeven` (ROI ≥ 0% & worst > -50%) / `fail`。
   後付けフィルタチューニング厳禁（フェーズ 3〜6 教訓）を JSON `verdict.note` と
   ターミナル表示で明文化
6. **出力**: `artifacts/eval/summary_<from>_<to>.json` + ターミナル
7. **データ不足挙動**: 1 件も `<日付>.json` 無 → エラー終了（コード 2）/
   部分欠損 → warning + 取得済みのみ集計 / `n_bet_races < 30` → 信頼性 warning /
   `n_days_with_data < 5` → 早期判定 warning
8. **既存 P3 CLI を書き換えない**: `evaluate_predictions.py` の出力スキーマだけ依存、
   独立した集約レイヤとして実装
9. **複数日サンプル拡張は別作業**: P3.5 着手時点では `2025-12-01` 1 日のみ。
   退化テスト（単日集計が P3 出力と完全一致）で実装の正しさを担保
10. **打ち切り条件**: スキーマ違反検出 → エラーログ + skip / サンプル不足は
    集計はするが warning レベル

動作確認パス（成果物 = `artifacts/eval/summary_2025-12-01_2025-12-01.json`）:

| 呼び出し | 結果 |
|---|---|
| `eval_summary.py --from 2025-12-01 --to 2025-12-01` | 1 day, 12 races settled, 17 bets, 1 hit, ROI -57.6%, hit_rate/bet 5.88%, hit_rate/race 8.33% |
| `eval_summary.py --month 2025-12` | 31 day window, 1 day with data, 30 missing dates warning + 上記と同等の集計 |
| `eval_summary.py --from 2025-09-01 --to 2025-09-03` | FileNotFoundError（コード 2 で終了） |
| `eval_summary.py --from 2025-12-05 --to 2025-12-01` | ValueError（コード 2 で終了） |

退化テスト検証（`summary_2025-12-01_2025-12-01.json` vs `2025-12-01.json`）:

- `roi`: -0.5765 ✓ (両者一致)
- `hit_rate_per_bet`: 5.88% ✓ / `hit_rate_per_race`: 8.33% ✓
- `total_stake`: 1700 ✓ / `total_payout`: 720.0 ✓
- `avg_confidence`: 0.4118 ✓
- `by_stadium[桐生]`: races=12, bets=17, hits=1, ROI -57.6% ✓
- `by_confidence_band[0.3-0.5]`: 11 bets, 0 hits, ROI -100% ✓
- `by_confidence_band[0.5-0.7]`: 6 bets, 1 hit, ROI +20.0% ✓
- `verdict.status`: `fail` ✓（ROI -57.6% < 0% かつ worst_month -57.6% < -50%）
- `bootstrap_ci`: lower=-1.0, upper=+27.1%（N=17 bets / 1 day なので CI 幅は広いのが正常）

実装中の発見と対応:

1. **Windows コンソール (cp932) で ✓✗△⚠ がエンコード不能**: `main()` 冒頭で
   `sys.stdout.reconfigure(encoding="utf-8")` を呼んで UTF-8 化（Python 3.7+）。
   `--quiet` 指定時は表示しないので影響なし
2. **bootstrap の対象**: `status == "settled"` かつ `verdict == "bet"` の bets のみ
   flatten。skip / no_result は除外（P3 `_build_summary` の集計対象と整合）
3. **confidence 帯境界**: `0.7-1.0` の hi=`1.000001` で `lo ≤ x < hi`、
   `confidence=1.0` も含む。P3 と完全一致

サイズ実績: summary JSON は 1 ヶ月分でも数十 KB。30 日全データでも < 200 KB と軽量。

---

## 9. 設計上の方針

### 9.1 Max プラン内完結

- API 課金は使わない（`anthropic` SDK / API キー不使用）
- Claude Code セッション内の対話で完結
- バッチ的な処理は Python スクリプト + Claude による各レース判断の組合せ

### 9.2 既存資産の流用

| 資産 | 流用方針 |
|---|---|
| `collector/program_downloader.py` | そのまま使用 |
| `collector/history_downloader.py` | そのまま使用 |
| `collector/odds_downloader.py` | そのまま使用（3連単）+ 単勝拡張は B-3 と統合検討 |
| `collector/openapi_client.py` | そのまま使用 |
| `features/stadium_features.py` | 場特性をレースカードに埋め込む形で利用 |
| `features/tidal_features.py` | 潮位情報をレースカードに埋め込む |
| `model/trainer.py`, `predictor.py` | 使用しない（LLM が判断する） |
| `backtest/engine.py` | 評価フェーズで参照（買い目シミュレーション） |

### 9.3 出力形式

- レースカード: Markdown（人間も Claude も読める）
- 予想結果: JSON（機械処理しやすく、`/eval-predictions` で突合）
- 評価結果: JSON + ターミナル表示

### 9.4 過去日付対応

`/prep-races` も `/predict` も過去日付を受け付ける（バックテスト・ドライラン用）。
過去のレースカードに対して `/predict` を実行 → `/eval-predictions` で実績と突合 →
LLM 予想の有効性を検証できる。

---

## 10. 残論点（実装中に決定）

1. **直前情報の取得元**:
   - 展示タイム・進入予想・直前気象は boatrace.jp の直前情報ページから取得
   - 既存 `openapi_client.py` で取得可能か確認 → 不可なら scrape する
   - **P2 着手時に確認**

2. **ステーク戦略**: 初期は 100 円固定。Kelly や信頼度連動は P5 以降

3. **見送り条件**: Claude の判断に委ねる（`verdict: "skip"`）。
   ただし最低限のガードレール（`current_odds < 1.5` で skip 強制 など）は `/predict` skill 側で持つ

4. **ドライラン用の過去日対応**:
   - `/prep-races 2025-12-01 桐生` のような過去日も受け付ける
   - history は当然取得済み、program も DL 可能、オッズも `data/odds/` に存在
   - これにより 2025-12 全 12 レース × 24 場で LLM 予想を回し ROI を検証できる
   - **ただしこれは API 課金なしでは Claude Code 対話セッションでしか実行不能**
     （バッチ実行はしない）

---

## 11. 評価指標

P3 完了時点で以下を出力:

- **的中率**: 買い目数に対する的中数（per bet）
- **ROI**: 払戻 / 投資 - 1（per day, per stadium, cumulative）
- **見送り率**: skip 判定数 / 全レース数
- **平均 confidence**: Claude の自信度の傾向
- **confidence vs ROI 相関**: 高 confidence 帯のほうが ROI 高いか

実用可能性の判断基準:

- 30 日以上の実走で **通算 ROI ≥ 0%（収支トントン以上）**
- かつ **最悪日 > -50%**

`CLAUDE.md` の実運用再開条件（通算 ROI ≥ +10% かつ最悪月 > -50%）に到達できれば、
API バッチ化（毎日全レース判定）の検討に進む。

---

## 12. 厳守事項

- ❌ Anthropic API（API キー）は使用しない（Max プラン内完結）
- ❌ 既存の LightGBM モデル（`trainer.py` / `predictor.py` / `engine.py`）には触らない
- ❌ 実運用購入は **しない**。あくまで Claude の予想精度検証フェーズ
- ❌ ROI が悪い結果でも、根拠なくフィルタを足してチューニングしない
  （フェーズ 3 〜 6 の教訓: 後付けフィルタは out-of-sample で必ず崩れる）
- ✅ ドライラン（過去日でのバックテスト）を最優先。実走に進むのは
  ドライランで方向性が見えてから

---

## 13. 参照ドキュメント

- [CLAUDE.md](CLAUDE.md) — プロジェクト全体ガイド、現行運用方針
- [BET_RULE_REVIEW_202509_202512.md](BET_RULE_REVIEW_202509_202512.md) — 実運用再開条件、過去経緯
- [DESIGN.md](DESIGN.md) — 既存 ML パイプラインの設計
- [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) — 既存改善計画
- [ml/src/collector/](ml/src/collector/) — 流用するデータ収集レイヤ
- [ml/src/features/](ml/src/features/) — 流用する特徴量レイヤ（一部）
- [ml/src/backtest/engine.py](ml/src/backtest/engine.py) — 評価フェーズで参照

---

以上。
