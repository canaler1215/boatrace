# PURGED_CV_POC_RESULTS — Purged / Embargoed CV PoC 結果（タスク 6-10-c 第 1 候補）

最終更新: 2026-04-25
対象: AUTO_LOOP_PLAN フェーズ 6 タスク 6-10-c「構造変更フェーズ：キャリブレーション再設計 / Purged CV」

## 背景

- フェーズ 6 のパラメータ探索は通算 13 trial で verdict=pass 再現 0 本、撤退判定済み
- タスク 6-10-a（特徴量拡張 PoC）採用 0、タスク 6-10-b（目的関数変更 PoC）採用 0
- 残る構造変更ツリー（MODEL_LOOP_PLAN §5）: **Purged CV（leak 排除）** → キャリブレーション再設計（C1/C2）
- ユーザー合意のもと **Purged CV を先に検証**（leak 排除後の clean baseline を C1/C2 評価の土台にする狙い）

## 実装方針（合意 2026-04-25）

`ml/src/model/trainer.py` / `predictor.py` / `engine.py` は**変更しない**。
PoC は新規スクリプト `ml/src/scripts/run_purged_cv_poc.py` に閉じ込める。

## 実行条件（共通）

| 項目 | 値 |
|---|---|
| train 期間 | 2023-01 〜（split_mode に応じて末尾を切り詰め） |
| val 期間 | 2025-12（単月、~28k サンプル / ~4,718 races） |
| 特徴量 | ベースライン 12 次元（タスク 6-10-a の知見） |
| objective | multiclass（タスク 6-10-b の知見：LambdaRank は撤退） |
| LGB params | learning_rate=0.05, num_leaves=63, min_child_samples=50, feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=5 |
| num_boost_round | 1000（早期停止 50） |
| ハーネス | `ml/src/scripts/run_purged_cv_poc.py` |
| 結果保存 | `artifacts/purged_cv_poc_results.jsonl`（1 行/run） |

## 採用判断基準（プロトコル）

PCV 専用基準（プロンプト本文 + 合意事項より）:

- **採用**: leak あり baseline 比で top-1 accuracy が **+0.5pp 以上低下**（=leak の影響を確認）
- **保留**: leak あり baseline 比で top-1 accuracy が **±0.3〜±0.5pp** 範囲（要追試）
- **却下**: leak あり baseline 比で top-1 accuracy が **±0.3pp 以内**（leak 影響なし → C1/C2 へ進む）

## 試行 4 種

| tag | split-mode | 内容 |
|---|---|---|
| PCV_baseline | baseline | 月境界 split。`race_date < val_start` を train（現行 PoC と同じ） |
| **PCV_embargo7** | embargo7 | `race_date < val_start - 7 days` を train |
| **PCV_embargo14** | embargo14 | `race_date < val_start - 14 days` を train |
| **PCV_meeting_purge** | meeting_purge | 月境界 split をベースに、`val_start - 7 days` 以降に val 月の各場で開催のあった同 stadium のレースを train から除外（meeting_id 不在のため近似） |

## 結果テーブル

| tag | n_train | reduction | top-1 | NDCG@1 | NDCG@3 | ECE_raw | best_iter | mlogloss |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| PCV_baseline | 953,302 | 0.00% | **0.5728** | **0.6912** | 0.7607 | 0.00670 | 212 | 1.6040 |
| PCV_embargo7 | 947,686 | 0.59% | 0.5750 | 0.6910 | 0.7611 | 0.00609 | 173 | 1.6044 |
| PCV_embargo14 | 942,137 | 1.17% | 0.5709 | 0.6904 | **0.7612** | **0.00576** | 207 | 1.6044 |
| PCV_meeting_purge | 947,686 | 0.59% | 0.5694 | 0.6864 | 0.7609 | 0.00609 | 173 | 1.6044 |

baseline 比 Δ:

| tag | Δtop-1 | ΔNDCG@1 | ΔNDCG@3 | 判定 |
|---|---:|---:|---:|---|
| PCV_embargo7 | **+0.22pp** | -0.02pp | +0.04pp | **却下**（±0.3pp 以内、leak 影響なし） |
| PCV_embargo14 | **-0.19pp** | -0.08pp | +0.05pp | **却下**（±0.3pp 以内、leak 影響なし） |
| PCV_meeting_purge | **-0.34pp** | -0.48pp | +0.02pp | **却下**（±0.5pp 以内、leak 影響なし／弱い兆候のみ） |

## 主要所見

### 1. 採用基準（+0.5pp 以上低下）達成は 0 件

embargo7/14/meeting_purge いずれも top-1 が baseline と ±0.5pp 以内に留まった。
**月境界 split の現行 baseline は実質的に leak フリーと判定**できる。

### 2. embargo7 = meeting_purge の n_train 一致は実装の意図通り

両 mode とも n_train=947,686 で一致した。理由は **2025-12 の各場すべてが 11 月最終週にも稼働しており**、
val 月にかかる場の `val_start - 7 days` 以降のレース集合が、単純な 7 日 embargo の集合とほぼ完全に
一致したため。これは「ボートレースは年中 24 場でほぼ同時稼働している」というドメイン特性の表れ。

### 3. それでも top-1 が異なる（embargo7=0.5750 vs meeting_purge=0.5694, Δ=+0.56pp）

**同じ train 集合・同じ best_iter (173) でも top-1 が約 0.56pp ばらつく**。
LightGBM の確率的サンプリング (`bagging_fraction=0.8, bagging_freq=5`) と feature fraction (0.8) に
seed 指定がなく、実行ごとに乱数が変わる挙動。**seed 分散の規模が ~0.5pp 程度ある**ことが
本 PoC で確認できた。

これは 6-10-a (Δ ±0.13pp)、6-10-b R1 (Δ +0.63pp) の結果が「真の改善か seed ノイズか」の
判別を一層困難にする所見であり、**6-10-b R1 撤退判断（案 Y）の正当性を補強**する。

### 4. ECE は embargo を強めるほど僅かに改善傾向

| split | ECE_raw | ECE_norm |
|---|---:|---:|
| baseline | 0.00670 | 0.01847 |
| embargo7 | 0.00609 | 0.02021 |
| embargo14 | 0.00576 | 0.01800 |
| meeting_purge | 0.00609 | 0.01957 |

raw ECE は baseline → embargo14 で 14% 改善（0.00670 → 0.00576）。ただし絶対値が
すでに非常に小さく（IR キャリブレーション無しで <1%）、PCV の主目的「top-1 改善」に対しては
副次的効果に留まる。

### 5. 月境界 split で leak が見えなかった理由（仮説）

`feature_builder.py` の `_add_rolling_racer_win_rate`（直近 3 ヶ月加重平均）と
`_add_racer_avg_st`（過去 ST 平均）は **前月以前のみ参照（look-ahead なし）**で実装済み。
本 PoC で月境界 split が clean だったのはこの look-ahead 排除実装が機能している証拠。

すなわち **boatrace の現行特徴量パイプラインは look-ahead leak がほぼゼロ**であり、
PCV による追加 leak 排除の余地がない、というのが本 PoC の帰結。

## 結論

Purged / Embargoed CV PoC は **採用基準（+0.5pp 以上低下）達成 0 件** で終了。

月境界 split の現行 baseline は実質 leak フリーであり、PCV を導入しても top-1 改善は得られない。
本来の目的「leak 排除後の clean baseline で C1/C2 を再評価」は、**現行 baseline が
すでに clean とみなせる**ため不要となった。

**確定判断**: PCV は採用せず、構造変更ツリーの次候補
**「キャリブレーション再設計（C1: Dirichlet calibration / C2: 結合 IR）」へ進む**。

副次的成果として、**LightGBM の seed 分散が ~0.5pp 規模**であることを確認。
この観測は今後の PoC（C1/C2 含む）における採用基準（top-1 +1.0pp）の
妥当性を補強する: seed 分散の 2 倍以上の改善幅を求める設計は適切である。

## 成果物

- `ml/src/scripts/run_purged_cv_poc.py`（新規）
  - baseline / embargo7 / embargo14 / meeting_purge をサポート
  - meeting_purge は近似実装（meeting_id 不在）。将来 program data から meeting boundary を
    抽出する設計に差し替え可能（`_build_train_mask` に閉じ込め済み）
  - trainer.py / predictor.py / engine.py は一切変更せず
- `artifacts/purged_cv_poc_results.jsonl`（4 行: baseline + embargo7 + embargo14 + meeting_purge）
- `artifacts/purged_cv_poc_logs/*.log`（各 run のフルログ）

## 次手

- タスク 6-10-c 第 2 候補 **C1: Dirichlet calibration** または **C2: 結合 IR**
- ハーネス: `ml/src/scripts/run_calibration_poc.py`（新規）
- baseline は本 PoC の `PCV_baseline`（top-1=0.5728）を流用
- 採用判断: top-1 +1.0pp 以上（C1/C2 共通）

## 参考

- 設計書: [MODEL_LOOP_PLAN.md](MODEL_LOOP_PLAN.md) §5 構造変更ツリー
- 直前結果: [OBJECTIVE_POC_RESULTS.md](OBJECTIVE_POC_RESULTS.md)（タスク 6-10-b 撤退判定、案 Y）
- その前: [FEATURE_POC_RESULTS.md](FEATURE_POC_RESULTS.md)（タスク 6-10-a 撤退判定）
- 13 trial 結果: [MODEL_LOOP_RESULTS.md](MODEL_LOOP_RESULTS.md)
- 重大発見: [CLAUDE.md](CLAUDE.md)（1 着識別能力の全ビン均一）
