# NEXT_PHASE_B3_PLAN — フェーズ B-3: 馬券種転換による市場効率分析（単勝）

最終更新: 2026-04-26
ステータス: **着手予定として保留**（フェーズ B-1 完全撤退後の次フェーズ候補）
位置付け: 案 A（フェーズ 6 凍結 + B-1 撤退）の出口戦略 = 案 B-3（馬券種転換）

## 1. 動機 — なぜ単勝（win）か

### B-1 で確定した負の知見

[NEXT_PHASE_B1_PLAN.md](NEXT_PHASE_B1_PLAN.md) §9 の通り、3 連単市場には:
- 統計的に有意な favorite-longshot bias が存在（lift 1.10〜1.27）
- 全 9 ビンで前半・後半同方向（一過性ではない）
- ただし `ev_all_buy` 最高でも 0.98（蒲郡 × 1 コース）で控除率 25% を破れない

**「3 連単では市場効率の歪みは控除率の壁を超えるほど大きくない」**。

### 方針: 控除率の異なる券種で同じ歪みを狙う

公営競技の券種別控除率:

| 券種 | 控除率 | 組合せ数 | 黒字化に必要な lift |
|---|---:|---:|---:|
| 単勝 (win) | **20%** | 6 | **≥ 1.25** |
| 複勝 | 20% | 6 | ≥ 1.25 |
| 2 連複 | 25% | 15 | ≥ 1.33 |
| 2 連単 | 25% | 30 | ≥ 1.33 |
| 拡連複 | 25% | 15 | ≥ 1.33 |
| 3 連複 | 25% | 20 | ≥ 1.33 |
| 3 連単 | 25% | 120 | ≥ 1.33 |

**単勝 / 複勝は控除率 20% で最も低い**。B-1 で見つけた「lift 1.10〜1.27」が単勝の人気組合せでも観測されれば、**控除率破壊の閾値 1.25 をクリアする可能性**がある。

### 期待値の根拠と注意

- 単勝は 6 通りしかなく、市場参加者の予測精度が高い → 歪みは小さい可能性
- ただし「人気艇への過小オッズ」は競馬・競艇で繰り返し報告される普遍バイアス
- B-1 で「3 連単 implied 0.10〜0.20 で lift=1.10、0.20〜0.50 で lift=1.20」を観測 → 単勝でも同程度の歪みは期待できる
- 単勝オッズは 1.0〜10.0 程度に収まるため、サンプル分散が安定しやすい
- **仮説検証ベース**で進める。歪みが控除率を破れなければ B-3 でも撤退、案 A 完全凍結に戻る

### なぜ単勝から始めるか（複勝でなく）

- 複勝は「3 着以内」判定で hit 確率が単勝の 3 倍程度になり、payout も低い → 構造的な期待値分析が複雑（複勝は 2 / 3 着の確率分布も必要）
- 単勝は「1 着のみ」で判定がシンプル → B-1 の 3 連単分析と完全に同じフレームワーク再利用可能
- 単勝で歪みが見つかった場合、複勝拡張は容易（次フェーズ）

## 2. スコープ（最小着手単位）

### Step 1: 単勝オッズダウンロード

`data/odds/` には現在 trifecta のみ。**12 ヶ月分の単勝最終オッズを新規 DL する必要あり**。

#### 実装

- `ml/src/collector/openapi_client.py` に `fetch_win_odds(stadium_id, race_date, race_no) -> dict[str, float]` を追加
- `ml/src/collector/odds_downloader.py` に `load_or_download_month_win_odds(year, month, race_df)` を追加（既存 trifecta / trio パターンの流用）
- キャッシュ形式: `data/odds/win_odds_YYYYMM.parquet`（カラム: race_id, boat_no, odds）

#### DL 想定時間

- 1 ヶ月 ≈ 4,500 レース × 1 リクエスト ≈ 1〜2 時間（並列 10）
- 12 ヶ月 → 12〜24 時間（バックグラウンド推奨）
- 既存 trifecta DL と同等以上のコスト

#### Step 1 の代替: API がない場合

- boatrace.jp / boatrace API で win オッズが取得不能なら本フェーズ撤退
- まず 1 ヶ月だけ試行 DL して動作確認

### Step 2: 単勝市場効率のキャリブレーション分析

B-1 Step 1 と同じ枠組みを単勝に適用:

- `ml/src/scripts/run_market_efficiency.py` を `--bet-type win` 対応に拡張
- 暗黙確率: 6 通りの implied_p で正規化 / `(1-θ)/odds` 両方 CSV 列に出す
- ビニング: 単勝は分布が広い（implied 0.05〜0.80）ため等幅 10 ビン（[0, 0.1, 0.2, ..., 1.0)）で開始
- bootstrap 90% CI（レース単位 × 月 stratify、n_resamples=2000）

### Step 3: サブセグメント分析（Step 2 で歪みが見つかった場合）

- focus 帯（lift > 1.10 のビン）を stadium / month で細分
- 採用基準: `n ≥ 1,000`、`lift_boot_lo > 1.0`、`ev_all_buy > 1.0`、`ev_boot_lo > 1.0`
- 単勝は 6 通りなので 1 軸（stadium）でも十分なサンプルサイズ確保しやすい

### Step 4: 単勝戦略のバックテスト（Step 3 で採用基準達成した場合のみ）

- 既存 `run_backtest.py` の流儀で単勝戦略を実装
- ただし既存モデル（trifecta 用）は使わない。Step 3 で見つけた「単勝 implied X% 帯 / 場 Y で買う」というルールベース戦略
- 採用基準: 通算 ROI ≥ +10%、broken_months = 0、プラス月 ≥ 60%、bootstrap CI 下限 ≥ 0

### Step 5: 撤退判定 or 拡張

- Step 2 で全 implied_p 帯にわたり lift が控除率破壊閾値（1.25）未達 → B-3 撤退
- Step 3 のサブセグメントで `ev_all_buy > 1.0` のセル無し → B-3 撤退
- Step 4 のバックテスト採用基準未達 → B-3 撤退
- 採用基準達成 → 複勝拡張 / 実運用再開準備フェーズへ

## 3. 採用判断基準

### Step 2 合格条件（B-1 と同様）

- ある暗黙確率帯（n ≥ 1,000）で `lift ≥ 1.10` または `≤ 0.85`
- 90% bootstrap CI で lift = 1.0 を含まない
- 前半 6 ヶ月 / 後半 6 ヶ月で同方向

### Step 3 合格条件（控除率 20% を考慮）

- ある (帯, セグメント) で:
  - `n ≥ 1,000`
  - `lift_boot_lo > 1.0`
  - `ev_all_buy > 1.0`（控除率 20% 破壊の点推定）
  - `ev_boot_lo > 1.0`（控除率破壊の確信あり）

### Step 4 合格条件

MODEL_LOOP_PLAN §3-5 と同じ:
- 通算 ROI ≥ +10%
- broken_months = 0（worst > -50%）
- プラス月 ≥ 60%
- bootstrap CI 下限 ≥ 0

## 4. 想定実装規模

| ステップ | 想定コスト | 主な成果物 |
|---|---|---|
| Step 1 (DL) | 12〜24 時間（バックグラウンド DL）+ 実装 1〜2 時間 | `fetch_win_odds`, `load_or_download_month_win_odds`, `data/odds/win_odds_*.parquet` |
| Step 2 | 半日 | `run_market_efficiency.py --bet-type win` 拡張、CSV、プロット |
| Step 3 | 半日 | サブセグメント集計（既存スクリプト拡張） |
| Step 4 | 1〜2 日（採用基準達成時のみ） | 戦略実装、バックテスト |
| Step 5 | 数時間 | 結果ドキュメント、採用判定 |

**最小成果物**: Step 2 完了時点で「単勝市場の歪みは控除率 20% を破れる / 破れない」の見当が付くはず。破れなければそこで撤退候補。

## 5. 厳守事項

- ❌ 既存モデル（trainer / predictor / engine）は**触らない**
- ❌ Step 4 のバックテスト前に Step 2-3 の歪み確認を完了する
  （フェーズ 6 + B-1 の教訓: 「精度改善 → ROI 改善」「歪み発見 → ROI プラス」の素朴な期待は何度も裏切られた）
- ❌ 既存の購入条件（CLAUDE.md「現在の仕様」、prob ≥ 7%、EV ≥ 2.0 等）を Step 4 戦略に流用しない
- ❌ サンプルサイズ小（n < 1,000）には飛びつかない
- ❌ Step 1 の DL 開始前に「単勝オッズが boatrace API で取得可能か」を 1 ヶ月だけテスト DL で確認する

## 6. 参照すべきドキュメント

- [CLAUDE.md](CLAUDE.md) — 「現在の仕様」「現行の運用方針」
- [NEXT_PHASE_B1_PLAN.md](NEXT_PHASE_B1_PLAN.md) §9 — B-1 撤退結果（本フェーズの起点）
- [MARKET_EFFICIENCY_RESULTS.md](MARKET_EFFICIENCY_RESULTS.md) — B-1 Step 1 結果
- [MARKET_EFFICIENCY_SEGMENT_RESULTS.md](MARKET_EFFICIENCY_SEGMENT_RESULTS.md) — B-1 Step 2 結果
- [LAMBDARANK_WALKFORWARD_RESULTS.md](LAMBDARANK_WALKFORWARD_RESULTS.md) — フェーズ 6 撤退結果（参考流儀）
- [BET_RULE_REVIEW_202509_202512.md](BET_RULE_REVIEW_202509_202512.md) §28-32 — 実運用再開条件
- [ml/src/collector/odds_downloader.py](ml/src/collector/odds_downloader.py) — 既存 trifecta / trio DL（流用ベース）
- [ml/src/collector/openapi_client.py](ml/src/collector/openapi_client.py) — `fetch_odds` / `fetch_trio_odds`（流用ベース）
- [ml/src/scripts/run_market_efficiency.py](ml/src/scripts/run_market_efficiency.py) — Step 2 拡張対象

## 7. 着手タイミング

ユーザーが「次に何かやろう」と思ったとき、本ドキュメントを参照して Step 1 から開始する。即着手の必要はなく、案 A 凍結状態で**いつでも再開できる**ことが重要。

着手時は [NEXT_SESSION_PROMPT.md](NEXT_SESSION_PROMPT.md) を新セッション冒頭に貼り付けて開始すること。

## 8. 撤退基準（B-3 でも撤退する条件）

以下のいずれかを満たした時点で B-3 撤退、案 A 完全凍結に戻る:

- Step 1: 単勝オッズが boatrace API で取得不能（API スキーマがない / 認証エラー継続等）
- Step 2: 全 implied_p 帯にわたり lift が 0.95〜1.05 の範囲（歪みなし、控除率破壊不能）
- Step 3: セグメントを細分しても `ev_all_buy > 1.0` のサブセグメントが見つからない
- Step 4: バックテストで採用基準未達

撤退時は本ドキュメントに「B-3 撤退結果」セクションを追加し、CLAUDE.md / AUTO_LOOP_PLAN.md を更新して**全フェーズ撤退（A 完全凍結）状態**を継続する。

その時点で「このアプリケーションで通算黒字化は不可能」と確定するわけではない（B-2 動的オッズ等の他候補は残る）が、控除率の最も低い単勝が撃破された場合、**他券種転換も保留判断が傾く**。
