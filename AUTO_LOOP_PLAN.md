# バックテスト自律改善ループ 実装計画

claude code agent がバックテスト実行 → 分析 → 対策立案 → 実装 → 再検証を自律反復する仕組みの実装計画。

## ステータス凡例
- `[ ]` 未着手
- `[~]` 着手中
- `[x]` 完了
- `[!]` ブロック中／保留（理由を注記）
- `[-]` スキップ／不要と判断

最終更新: 2026-04-26（フェーズ 6 完全撤退を確定。次フェーズ B-1「市場効率の歪み分析」着手予定として保留。実運用は引き続き停止、`/inner-loop` `/model-loop` も凍結。詳細は [NEXT_PHASE_B1_PLAN.md](NEXT_PHASE_B1_PLAN.md)）

---

## フェーズ 0: ローカル再現性の担保（前提整備）

自律ループの実行主体（agent・CI・他メンバー）が同じ手順で環境を立ち上げられる状態を作る。

- [x] **0-1. `.env.example` 作成** ✅ 2026-04-24
  - 必要変数: `DATABASE_URL`, `LOG_LEVEL`, (オプション) `DISCORD_WEBHOOK_URL`
  - 根拠: [db_writer.py:10](ml/src/collector/db_writer.py#L10) が `DATABASE_URL` 必須
  - 完了条件: `cp .env.example .env` でそのまま動く雛形
- [x] **0-2. `docker-compose.yml` 作成** ✅ 2026-04-24
  - PostgreSQL 16 サービス定義、ボリューム永続化
  - `docker/init-db.sh` で `apps/web/lib/db/migrations/` を番号順に自動適用
  - 完了条件: `docker compose up -d` で DB が起動し、マイグレーションが通る
- [x] **0-3. ローカルセットアップ手順書 `SETUP.md` 作成** ✅ 2026-04-24
  - 手順: clone → `.env` コピー → `docker compose up` → `pip install -r ml/requirements.txt` → smoke test
  - Windows での `lhasa` 代替（WSL 推奨）を明記
- [x] **0-4. smoke test スクリプト `ml/src/scripts/smoke_test.py` 作成** ✅ 2026-04-24
  - チェック項目: DATABASE_URL 設定確認 / DB 接続 / 必須テーブル存在 / 1 日分バックテスト（合成オッズ）
  - モデル・キャッシュデータがない場合は `[SKIP]` として通過（CI フレンドリー）
  - 完了条件: 完走で exit 0、いずれかの失敗で exit 1
  - **動作確認済み** ✅ 2026-04-24: Windows / Python 3.12 / Neon DB で `Smoke test passed.` 確認

### フェーズ 0 補足事項（実施中に判明した知見）

- **バックテストはDB非使用**: `run_backtest.py` はファイルキャッシュ（`data/`）と pandas のみで完結。DB書き込みなし。本番NeonとローカルDockerの分離は `run_retrain.py`（model_versions 上書き）・`run_predict.py` のテスト時に重要。
- **Python バージョン**: pandas 2.2.3 のビルド済みホイールは Python 3.12 向け。3.14 では `vswhere.exe` 未検出エラーでインストール失敗。**Python 3.12 を使うこと**（SETUP.md に明記済み）。
- **`.env.example` の認証情報漏洩防止**: example ファイルには実際の接続文字列を入れないこと。`.env` は `.gitignore` 済みだが `.env.example` は git 管理対象のため注意。

## フェーズ 1: 評価ゲート（KPI 機械判定）

CLAUDE.md の運用ルール（ROI 300/500%/負値）を自動判定し、後続ループのトリガを生む。

- [x] **1-1. `ml/src/scripts/run_gate_check.py` 新規作成** ✅ 2026-04-24
  - 入力: `artifacts/backtest_YYYYMM.csv`（`--csv` or `--year`/`--month` で指定）
  - 出力: `artifacts/gate_result_YYYYMM.json`（ROI, ベット数, 的中率, avg odds, ゾーン判定）
  - ゾーン: `normal / caution / warning / danger`（CLAUDE.md 運用ルールに準拠）
  - exit code: `warning` 以下で非0（CI 失敗扱い）
  - `--no-append` オプションで kpi_history への追記をスキップ可能
  - **動作確認済み** ✅: `artifacts/backtest_202512.csv` で warning ゾーン・exit 1 を確認
- [x] **1-2. KPI 履歴台帳 `artifacts/kpi_history.jsonl`** ✅ 2026-04-24
  - `run_gate_check.py` 実行ごとに 1 行追記（`append_kpi_history()` 関数）
  - 記録項目: timestamp, period, zone, commit_sha, model_version, ROI, ベット数, 的中率, avg odds, avg top_prob
  - `.gitignore` 済みにはせず、PR で履歴を残す運用に
  - **動作確認済み** ✅: `artifacts/kpi_history.jsonl` に 1 件追記を確認
- [x] **1-3. 回帰防止テスト `ml/tests/test_no_regression.py`** ✅ 2026-04-24
  - 直近 6 ランの ROI 中央値の 70% を下回る PR は fail（`REGRESSION_WINDOW`, `REGRESSION_FLOOR` で調整可能）
  - agent が閾値を過度に弄って見かけ ROI を悪化させるのを防ぐ
  - 追加チェック: 最新ゾーン danger 検出 / 2 ラン連続 warning 検出
  - 履歴 2 件未満は SKIP（CI 初回・フェーズ移行時はフレンドリー）
  - **動作確認済み** ✅: kpi_history 1 件で SKIP に分岐することを確認

## フェーズ 2: 外ループ（GitHub Actions で定期実行）

> **方針（2026-04-24 確定）**: バックテスト・Walk-Forward はすべて `--real-odds`（実オッズ）を使用する。
> 合成オッズは使用しない。boatrace.jp からのダウンロードキャッシュは `data/` に保存済みのものを再利用する。

cron で定期バックテストを回し、異常検知で Issue を自動起票する。

- [x] **2-1. `.github/workflows/auto_backtest_loop.yml` 新規作成** ✅ 2026-04-24
  - トリガ: `schedule: cron: "0 0 1 * *"`（毎月1日）+ `workflow_dispatch`
  - ステップ: モデルDL → 前月分 backtest（`--real-odds`）→ gate_check → kpi_history commit → 異常時 Issue 起票
  - ジョブ分割: `backtest-and-gate`（メイン）+ `create-issue`（warning/danger 時のみ実行）
  - Issue 本文: KPI サマリ、直近6ヶ月 ROI 推移、想定原因チェックリスト、推奨コマンド
- [x] **2-2. Issue 起票テンプレート `.github/ISSUE_TEMPLATE/auto_loop_alert.md`** ✅ 2026-04-24
  - タイトル例: `[auto-loop] 2026-03 ROI +280% (warning zone)`
  - 本文: KPI サマリ、artifact URL、直近 6 ヶ月比較、想定原因チェックリスト
  - ラベル: `auto-loop`, `needs-investigation`
- [x] **2-3. `.github/workflows/quarterly_walkforward.yml` 新規作成** ✅ 2026-04-24
  - トリガ: 四半期（1/1, 4/1, 7/1, 10/1 の 01:00 UTC）+ `workflow_dispatch`
  - デフォルト: 直近 6 ヶ月の Walk-Forward（`--real-odds --retrain`）
  - 各月 gate_check を自動実行し kpi_history に追記 → commit/push
  - Job Summary に直近 6 ヶ月 KPI テーブルを出力

## フェーズ 3: 内ループ（Claude がオーケストレーターとして自律修正）

> ⚠️ **凍結中（2026-04-24〜）**
>
> 3 エージェント独立相互レビューの結果、本ループは以下の理由で凍結。
> 実装は PR #3 で Critical バグ 4 件（C1/C3/C4/C5）を修正済みだが、
> 再開は `/model-loop`（フェーズ6）で黒字化を達成してから。
>
> **凍結理由**:
> - `BET_RULE_REVIEW_202509_202512.md` §30-32 で「フィルタ探索では
>   out-of-sample 黒字化不能」と判定済み（12ヶ月通算 ROI -13.4%、
>   破局月 2025-10 -72.4% / 2026-01 -79.5% / 2026-04 -65.4%）
> - 単月 ROI の偶発変動で ΔROI +50pp は容易に達成されるため、
>   現行採択ロジックでは破局月を baseline にすると必ず誤採択される
> - 1 着識別能力が全ビンでランダムに近いため、モデル側がボトルネック。
>   フィルタ調整は堂々巡りになる
>
> **再開条件**:
> - `/model-loop`（フェーズ6）で通算 ROI ≥ 0% を達成
> - 採択ロジックを「単月 ΔROI +50pp」→「多月ホールドアウト評価」に再設計
> - 手順書 `.claude/commands/inner-loop.md` の Step 7〜8（YAML 編集 →
>   CLI 引数渡し）を、`--strategy-config` 読み取り専用運用に合わせて
>   作り直す
>
> 詳細: `.claude/commands/inner-loop.md` 冒頭の凍結ノート、
> および [PR #3](https://github.com/canaler1215/boatrace/pull/3)。

**設計方針（2026-04-24 変更）**: ANTHROPIC_API_KEY を使わない設計。
Claude（ローカルの Claude Code セッション）がオーケストレーターとなり、
GitHub Actions は「重い計算を実行するサーバー」として使う。

```
Claude（ローカル）
  ↓ gh workflow run claude_fix.yml でキック
GitHub Actions
  → run_backtest.py（実オッズ, ~数時間）
  → run_gate_check.py（ゾーン判定）
  → run_segment_analysis.py（コース/場/確率帯 別 ROI）
  → artifacts を upload（CSV / JSON / TXT）
  ↓ gh run download で全 artifacts を取得
Claude（ローカル）が結果を読んで分析・判断
  → strategy_default.yaml を修正
  → 改善候補で再度 gh workflow run
  → 改善確認 → PR 作成
```

- [x] **3-1. `claude_fix.yml` をオーケストレーター対応に書き直し** ✅ 2026-04-24
  - トリガ: `workflow_dispatch` のみ（Claude が `gh workflow run` でキック）
  - 1ジョブで「バックテスト → gate_check → segment_analysis」を一括実行
  - すべての結果を artifacts にアップロード（Claude が `gh run download` で取得）
  - `label` パラメータで `baseline` / `candidate` を区別してファイル名を分けられる
  - **ANTHROPIC_API_KEY 不要**
- [x] **3-2. Agent 向けプロンプト整備 `.claude/AGENT_BRIEF.md`** ✅ 2026-04-24
  - 分析手順（セグメント分析 → キャリブレーション → KPI 履歴）
  - パラメータ調整ガイドライン（各閾値の意味・調整範囲）
  - 変更可/不可ファイルの明示、最大3イテレーション・撤退条件
- [x] **3-3. 戦略パラメータの外出し `ml/configs/strategy_default.yaml`** ✅ 2026-04-24
  - 購入フィルタ・賭け金管理パラメータを YAML に集約
  - `run_backtest.py` に `--strategy-config` オプション追加（CLI 引数優先）
- [x] **3-4. CODEOWNERS でガードレール** ✅ 2026-04-24
  - `ml/src/`, `ml/migrations/`, `.github/workflows/` は `@canaler2703` 必須
  - `ml/configs/` は Claude が変更できる唯一の場所
- [x] **3-5. 相互レビュー Critical バグ修正（PR #3）** ✅ 2026-04-24
  - C1: `run_gate_check.py` に `--label` 引数追加（JSON ファイル名衝突解消）
  - C3: `claude_fix.yml` の workflow_dispatch 入力から閾値類を削除、
    `ml/configs/strategy_default.yaml` 読み取り専用運用に統一
    （CODEOWNERS 迂回の遮断）
  - C4: `exclude_courses` 空文字時の argparse クラッシュ解消
    （C3 の `--strategy-config` 経由化により連動解決）
  - C5: `run_backtest.py` の `_apply_strategy_config` / `_set_if_default`
    のコメントと実装の乖離を訂正（YAML 優先の無条件上書きを明記）
  - `inner-loop.md` / `AGENT_BRIEF.md` 冒頭に凍結ノートを追加

## フェーズ3 ローカル設定手順

### 1. `auto-loop-candidate` ラベルの作成

```bash
gh label create "auto-loop-candidate" --color "0e8a16" --description "auto-loop agent が提案した修正 PR"
```

### 2. Branch Protection Rule の設定

`ml/configs/` への PR を意図せずマージしないよう、`main` ブランチを保護してください。

**Settings → Branches → Add branch protection rule**:
- Branch name pattern: `main`
- Require a pull request before merging: ✅
- Require approvals: 1
- Require review from Code Owners: ✅（CODEOWNERS が有効になる）

### 3. `gh` CLI のインストール・認証（Claude がキックに使用）

Windows:
```powershell
winget install --id GitHub.cli
gh auth login   # ブラウザ経由で認証
```

確認:
```bash
gh --version
gh auth status
gh repo view --json nameWithOwner -q '.nameWithOwner'
# → "canaler1215/boatrace" と出力されればOK
```

### 4. 動作確認（Claude セッションから `/inner-loop` で実行）

Claude Code セッションを開き、スラッシュコマンドを入力するだけで内ループが動きます。

```
/inner-loop 2025 12
```

または最大イテレーション数を指定:

```
/inner-loop 2025 12 3
```

Claude は `.claude/commands/inner-loop.md` の手順に従い、以下を自動実行します:

1. `gh workflow run claude_fix.yml -f year=2025 -f month=12 -f label=baseline` でキック
2. `gh run watch <run-id> --exit-status` で完了を待機
3. `gh run download <run-id> -D /tmp/inner-loop/baseline` で artifacts を取得
4. `gate_result_*.json` と `segment_*.txt` を読んで分析
5. `ml/configs/strategy_default.yaml` を 1 パラメータだけ修正
6. 修正後のパラメータで `label=candidate-iter1` として再キック
7. baseline vs candidate を比較
8. 改善確認 → PR 作成、改善不十分 → 次イテレーション、最大イテレーション到達 → 撤退

**重要**: `/inner-loop` は必ず GitHub Actions 経由で実行されます。
ローカルで `python ml/src/scripts/run_backtest.py` を呼ぶことはありません。

### 4. ワークフローの権限確認

**Settings → Actions → General → Workflow permissions**:

- **Read and write permissions** ✅（kpi_history commit push に必要）
- **Allow GitHub Actions to create and approve pull requests** ✅

---

## フェーズ 4: PR フィードバックループ

agent が出した PR 上で再バックテストを回し、改善を数値で確認する。

- [ ] **4-1. PR 上の自動バックテスト**
  - トリガ: `pull_request` with label `auto-loop-candidate`
  - 既存 `backtest.yml` を reusable workflow 化して呼び出す
- [ ] **4-2. PR コメントで KPI diff 表示**
  - `artifacts/kpi_history.jsonl` の直近値 vs この PR の値を表形式でコメント
  - 悪化時は明確にマーク
- [ ] **4-3. 自動 merge / revert 判定**
  - ΔROI ≥ +50pp かつ ECE 非悪化 → `auto-merge` ラベル
  - ΔROI < 0 → agent に仮説更新を促すコメントを自動投稿
  - 最大3イテレーション到達で `wontfix` クローズ

## フェーズ 5: 観測性とデバッグ支援

ループが回り始めた後の運用品質を上げる。

- [ ] **5-1. 月次ダッシュボード生成**
  - `kpi_history.jsonl` → matplotlib で ROI / ECE / ベット数の時系列プロット
  - `artifacts/dashboard_YYYYMM.png` として保存、Discord 通知に添付
- [ ] **5-2. agent のループ履歴メトリクス**
  - 何イテレーション目で解決したか、平均ΔROI、撤退率
  - `artifacts/loop_metrics.jsonl`
- [ ] **5-3. 失敗時の Runbook**
  - よくある失敗パターン（odds ダウンロード失敗、OOM、モデル DL 失敗）と対処を `RUNBOOK.md` に集約

## フェーズ 6: モデル構造ループ（/model-loop、ローカル）

`/inner-loop`（フィルタ探索）が out-of-sample で黒字化できなかったため（BET_RULE_REVIEW §30-32）、
モデル側（学習ハイパラ・学習窓・sample_weight）を探索する別系統のループを新設。
設計書: [MODEL_LOOP_PLAN.md](MODEL_LOOP_PLAN.md)

- [x] **6-1. trainer.py の config 対応** ✅ 2026-04-24
  - `train(..., lgb_params, num_boost_round, early_stopping_rounds, sample_weight, return_metrics)` を keyword-only で拡張
  - 既存呼び出し（5 箇所）を壊さず、`return_metrics=True` で `{model_path, metrics, best_iteration, params}` を返す
  - テスト: [ml/tests/test_trainer_config.py](ml/tests/test_trainer_config.py)（7 ケース）
- [x] **6-2. run_walkforward.py の config 対応** ✅ 2026-04-24
  - `build_sample_weight(race_dates, ref_date, config)` を新設（`recency` / `exp_decay` モード）
  - `get_model_for_month(..., trial_config, return_metrics)` を追加（既存 CLI は非破壊）
  - `build_features_from_history(..., return_dates=True)` で race_date を保持可能に
  - テスト: [ml/tests/test_walkforward_config.py](ml/tests/test_walkforward_config.py)（11 ケース）
- [x] **6-3. run_model_loop.py 新規作成** ✅ 2026-04-24
  - `trials/pending/*.yaml` を順次実行、YAML スキーマ検証、KPI 算出、`trials/results.jsonl` 追記
  - `primary_score = roi_total + 0.5 * cvar20 - 10 * broken_months`（2026-04-24 改訂、MODEL_LOOP_PLAN §3-4）、verdict（pass / marginal / fail）
  - 成功時 YAML を `completed/` へ移動、失敗時は pending 残留 + `artifacts/model_loop_<trial_id>_error.log`
  - テスト: [ml/tests/test_model_loop.py](ml/tests/test_model_loop.py)（22 ケース）
- [x] **6-4. 初期 trial seeds 8 本を配置** ✅ 2026-04-24
  - T00_baseline / T01_window_2024 / T02_window_2025 / T03_sample_weight_recency / T04_lgbm_regularized / T05_lgbm_conservative_lr / T06_early_stop_tight / T07_window_2024_plus_weight
  - 全 trial で `strategy` セクションを統一（比較可能性を保証）
  - テスト: [ml/tests/test_trial_seeds.py](ml/tests/test_trial_seeds.py)（40 ケース）
- [x] **6-5. /model-loop スラッシュコマンド** ✅ 2026-04-24
  - [.claude/commands/model-loop.md](.claude/commands/model-loop.md)（argument-hint: `[trial_id | all]`）
  - 連続実行合意のため途中報告は最小限、全 trial 完了後に `primary_score` 順で報告
  - `/inner-loop` との用途差を冒頭で明示
- [x] **6-6. ドキュメント更新** ✅ 2026-04-24
  - CLAUDE.md に「モデル構造自律改善ループ（/model-loop）」章を追加、`/inner-loop` との用途差を明示
  - 本書（AUTO_LOOP_PLAN.md）にフェーズ 6 を追記
  - trials/README.md はタスク 3 で作成済み（ディレクトリ運用ガイド）
- [x] **6-7. §7-6 動作確認（smoke 経路）** ✅ 2026-04-24
  - T00_smoke / T01_smoke（2025-12 単月・合成オッズ）で経路検証。結果は §10 スモーク節を参照
  - sample_weight 生成 / lgb_params 上書き伝搬 / status=success / 副産物後始末すべて確認済み
- [x] **6-8. 本番 10 trial 連続実行** ✅ 2026-04-25
  - `data/odds/2025-05〜2026-04` の 12 ヶ月分実オッズ完備（`.partial` なし、各 ~1MB × 12）
  - `py -3.12 ml/src/scripts/run_model_loop.py` で 10 trial 連続実行、エラー 0 / 全 YAML が `completed/` へ移動
  - 結果詳細: [MODEL_LOOP_RESULTS.md](MODEL_LOOP_RESULTS.md)（新規）
  - **要旨**: T07_window_2024_plus_weight のみ `verdict=pass`（ROI +15.30%, worst -35.16%, plus_ratio 66.7%, CI 下限 +1.94）
  - **重要所見**: T00/T08/T09（baseline seed 反復）で ROI range 9.3pp / worst range 26.4pp の大きな seed 変動を確認。
    T07 pass は seed ガチャの可能性があり、設計書 §5「近傍 2〜3 本で確証」が必要
- [x] **6-9. 次イテレーション: T10〜T12（T07 近傍確証）** ✅ 2026-04-25
  - T10_window_2024_weight_seed1 — T07 + `lgb_params.seed=1`: ROI -17.19%, plus_ratio 8.3%, verdict=fail
  - T11_window_2024_weight_seed2 — T07 + `lgb_params.seed=2`: ROI +9.47%, broken=1, verdict=marginal
  - T12_window_2024_weight_strong — T07 + `recency_months=3, recency_weight=3.0`: ROI -1.93%, broken=1, verdict=fail
  - **T10/T11 pass 再現 0/2** → T07 pass は seed ガチャ確定
  - T07/T10/T11 の seed 分散: ROI std 17.32pp / range 32.49pp（baseline 反復より大）
  - 詳細: [MODEL_LOOP_RESULTS.md](MODEL_LOOP_RESULTS.md) §「T10〜T12 追加サイクル」
- [ ] **6-10. 構造変更フェーズ（パラメータ探索打ち止め → 構造変更）** 🔴 進行中
  - 本番通算 13 trial で pass 再現 0 本、β(1,1) 事前 + 観測で P(p>10%) ≒ 15%、延長の経済合理性なし
  - 構造変更先は設計書 §5 の 4 項ツリー（特徴量拡張 / 目的関数変更 / キャリブレーション再設計 / Purged CV）
  - **6-10-a. 特徴量拡張 PoC（c → b → a → d 各単独 + 複合）** ✅ 完了（2026-04-25）
    - `ml/src/features/` 変更禁止パス解除合意（ユーザー承認 2026-04-25）
    - ベースライン確立: 12 次元、val=2025-12 単月、top1_acc=0.5753 / ECE_cal=0.00217 / mlogloss_cal=1.5981
    - PoC c (`racer_st_std` / `racer_late_rate`): top1=-0.32pp → **却下**
    - PoC b (`course_win_rate` 24×6 テーブル): top1=-0.18pp → **保留**（境界）
    - PoC a (`wind_speed_diff` 場過去平均との差): top1=+0.13pp → **保留**（唯一の正方向、境界）
    - PoC d (motor/boat 減衰平均): K/B ファイルにモーター/ボート ID 列なし、**仕様上実装不可** → スキップ
    - 複合 (a+b+c): top1=-0.27pp、mlogloss/ECE は最良だが top-1 改善せず
    - **採用基準達成 0 件** → Walk-Forward 検証はスキップ、構造変更ツリーの次候補へ
    - 詳細: [FEATURE_POC_RESULTS.md](FEATURE_POC_RESULTS.md)
    - 成果物: feature_builder.py / stadium_features.py 拡張、ハーネス 2 本、ユニットテスト 17 件 pass
  - **6-10-b. 目的関数変更 PoC** ✅ 完了（2026-04-25）
    - 方針合意: trainer.py / predictor.py / engine.py 不変、新規 `run_objective_poc.py` に閉じ込める
    - ベースライン（multiclass、IR キャリブレーションなし、apples-to-apples 比較用）: top1=0.5710 / NDCG@1=0.6910
    - **B1 (binary)**: top1=0.5698（**-0.13pp**）→ **却下**
    - **R1 (lambdarank)**: top1=0.5773（**+0.63pp**）/ NDCG@1=0.6969（+0.59pp）→ **保留**（+0.5〜+1.0pp 帯、唯一の改善）
    - **P1 (rank_xendcg)**: top1=0.5749（+0.39pp）→ **却下**（+0.5pp 未満）
    - **採用基準（+1.0pp）達成 0 件**
    - 推奨: 案 Y 撤退（+0.63pp は seed 分散範囲内、trainer.py/predictor.py 統合コストに見合わず）
    - 詳細: [OBJECTIVE_POC_RESULTS.md](OBJECTIVE_POC_RESULTS.md)
    - 成果物: `run_objective_poc.py`（新規）、jsonl 4 行、logs 4 本
  - **6-10-c. キャリブレーション再設計 / Purged CV** ✅ 完了（2026-04-25）
    - 案 Y 確定（ユーザー承認 2026-04-25）: R1 (LambdaRank) は Walk-Forward へ進めず、構造変更ツリー次候補へ移行
    - 着手順序合意（2026-04-25）: 先に Purged CV → leak 排除後 baseline で C1/C2 を評価する想定
    - 方針合意: trainer.py / predictor.py / engine.py 不変、新規 `run_purged_cv_poc.py` / `run_calibration_poc.py` に閉じ込める
    - **Purged CV PoC ✅ 完了（2026-04-25）**
      - ベースライン (月境界 split): top1=0.5728 / NDCG@1=0.6912
      - **embargo7**: top1=0.5750（+0.22pp）→ **却下**（±0.3pp 以内）
      - **embargo14**: top1=0.5709（-0.19pp）→ **却下**（±0.3pp 以内）
      - **meeting_purge**: top1=0.5694（-0.34pp）→ **却下**（±0.5pp 以内、弱い兆候のみ）
      - **採用基準（+0.5pp 以上低下）達成 0 件** → 月境界 split は実質 leak フリー判定
      - 副次成果: LightGBM の seed 分散が **~0.5pp 規模**であることを観測（同 train 集合・同 best_iter で top1 が 0.5694〜0.5750 と揺れる）。今後の PoC で採用基準（+1.0pp）の妥当性を補強
      - 詳細: [PURGED_CV_POC_RESULTS.md](PURGED_CV_POC_RESULTS.md)
      - 成果物: `run_purged_cv_poc.py`（新規）、jsonl 4 行、logs 4 本
    - **CAL PoC（C1 Dirichlet / C2 結合 IR）✅ 完了（2026-04-25）**
      - split: train=2023-01〜2025-10, cal=2025-11, val=2025-12（PCV と異なるため top-1 絶対値は内部 baseline 比較）
      - **CAL_baseline (per_class_ir)**: top1_cal=0.5756 / trifecta_ECE=0.00858 / mlogloss=1.6192
      - **CAL_C2_joint_ir** (T=1.0 で grid 貫通): top1_cal=0.5705（-0.51pp）/ trifecta_ECE -0.4% → **却下**
      - **CAL_C1_dirichlet**: top1_cal=0.5712（-0.44pp）/ trifecta_ECE 0.00768（**-10.4%**）/ mlogloss -0.88% → **却下**（top-1 低下、補助基準 trifecta ECE -50% に未達）
      - **採用基準（top-1 +1.0pp、補助基準 trifecta ECE -50%）達成 0 件**
      - C1 Dirichlet は確率質改善（trifecta ECE -10.4%）の方向性は正しいが幅が小さい
      - 詳細: [CALIBRATION_POC_RESULTS.md](CALIBRATION_POC_RESULTS.md)
      - 成果物: `run_calibration_poc.py`（新規）、jsonl 3 行、logs 3 本
    - **構造変更ツリー §5 全 4 候補（特徴量拡張 / 目的関数変更 / Purged CV / キャリブレーション再設計）すべて採用 0**
    - 次手の選択肢: (1) フェーズ 6 全体撤退、(2) ツリー外候補（多目的学習 / 二段階モデル / アンサンブル）、(3) R1 LambdaRank（保留ゾーン）を Walk-Forward まで進める
    - 推奨: (3) R1 を Walk-Forward 検証（最後の保留ゾーン候補。失敗ならフェーズ 6 撤退確定）
    - 既存 R1 数値・jsonl は将来の再評価用に保持
  - **6-10-d. R1 LambdaRank 本体統合 + Walk-Forward** ✅ 完了（2026-04-25）
    - **Step 1（seed 反復 sanity check）✅ go 判定**
      - baseline (multiclass) × 3 + R1 (lambdarank) × 3 = 計 6 run（seed=42/123/7、val=2025-12）
      - Δ_obs=+0.609pp、std_pooled=0.241pp、2σ=0.481pp
      - Δ_obs ≥ 2σ かつ Δ_obs ≥ 0.4pp → **verdict=go**（seed ノイズではない）
      - 詳細: [LAMBDARANK_SEED_CHECK_RESULTS.md](LAMBDARANK_SEED_CHECK_RESULTS.md)
      - 成果物: `run_objective_poc.py` に `--seed` 追加 / `run_lambdarank_seed_check.py` 新規 / jsonl 6 行
    - **Step 2-3（trainer.py / predictor.py / engine.py 統合 + smoke）✅ 完了**
      - trainer.py: `race_ids` 引数追加、lambdarank/rank_xendcg 分岐（race_id ソート + group + relevance=5-y）、(N,)→race-softmax→(N,6) ブロードキャスト
      - predictor.py: `predict_win_prob(model, X, race_ids=None)` 拡張、booster.params.objective で分岐
      - engine.py: race_ids を predict_win_prob に渡す（multiclass では無視される）
      - run_walkforward.py: ranking objective 時に df_train から race_id を抽出して trainer に注入
      - smoke: multiclass 後方互換 OK（race_ids あり/なし完全一致）/ lambdarank 一気通貫 OK（best_iter=29、ECE before=0.063→after=0.010）
      - 既存テスト 91 件 全 pass（test_model_loop / test_trial_seeds）
    - **Step 4-5（T13_lambdarank Walk-Forward 12 ヶ月）✅ verdict=fail**
      - trial_id=T13_lambdarank、2025-05〜2026-04、retrain_interval=3、real_odds、seed=42
      - 通算 ROI **-7.1%**、worst -56.3%（2025-09 broken）、プラス月 41.7%、CI 下限 -23.2
      - **採用基準 4 条件すべて未達** → fail
      - T00 baseline (multiclass、ROI=-6.6%) と統計的に区別不能、worst は -13pp 悪化
      - 単月 top-1 +0.609pp 改善は ROI ベース 12 ヶ月 Walk-Forward に転化しなかった
      - 詳細: [LAMBDARANK_WALKFORWARD_RESULTS.md](LAMBDARANK_WALKFORWARD_RESULTS.md)
    - **構造変更ツリー §5 全 4 候補 + 保留候補 R1 LambdaRank すべて fail**
    - **フェーズ 6 撤退判定の最終ゲート確定**: モデル側設計改善で CLAUDE.md 実運用再開条件
      （通算 ROI ≥ +10% / worst > -50%）はクリア不能と確定
    - 次手の候補（ユーザー判断委譲）:
      - 案 A: フェーズ 6 完全撤退、運用停止継続
      - 案 B: 全く別のアプローチで新フェーズ開始（市場効率の歪み / データソース拡張 / 馬券種転換）
      - 案 C: T13 を seed=123, 7 で 2 回追加実行（撤退判定の確証補強、~15 分）
    - 推奨: 案 C → 案 A or 案 B（撤退の意思決定には seed 反復確証が必要）
    - **案 C 実施 ✅ 完了（2026-04-25、Step 7）** — フェーズ 6 完全撤退の確証取得
      - T14_lambdarank_seed123: verdict=fail / ROI=-16.8% / worst=-59.1% / broken=2 / CI_low=-26.7
      - T15_lambdarank_seed7: verdict=fail / ROI=-6.1% / worst=-40.5% / broken=0 / CI_low=-20.2
      - **3 trial 集計**: ROI mean=-10.0%, std=5.9pp, range -16.8%..-6.1% / worst mean=-52.0%
        / broken total 3/36 月 / CI_low mean=-23.4
      - **採用基準（ROI ≥ +10%）達成 0/3、最良 seed でも閾値から 16pp 乖離**
      - **bootstrap CI 下限が 3 trial 全て -20pp 以下** で「真の通算 ROI が 0% を上回る」可能性は統計的に否定
      - 結論: **lambdarank で実運用再開条件はクリア不能、フェーズ 6 完全撤退を確定**
      - 詳細: [LAMBDARANK_WALKFORWARD_RESULTS.md](LAMBDARANK_WALKFORWARD_RESULTS.md) Step 7 セクション

## フェーズ 7（予定）: 市場効率の歪み分析（B-1）

**着手予定（2026-04-26 ユーザー合意）**: 案 A（フェーズ 6 凍結）を採りつつ、
直後の改善候補として **B-1: 市場効率の歪み分析**を着手予定として保留する。

### 動機

フェーズ 6 で「モデル精度をいくら上げても控除率 25% を超えて通算黒字化はできない」
ことが構造的に確認された。B-1 は方針を 180 度転換し、**モデル精度ではなくオッズ側の
構造的バイアス（人気馬券の過小オッズ / 高オッズ帯の過大オッズ等）を狙う**アプローチ。

### スコープ（最小着手）

1. オッズ vs 実勝率のキャリブレーション分析（既存 `run_calibration.py` をオッズ
   側にも適用、暗黙確率 = 1 / odds × (1 - 控除率) で逆算）
2. 人気帯別 / オッズ帯別の歪み定量化
3. もし系統的バイアスがあれば、それを利用した戦略を立案 → バックテスト

### 着手前の判断ポイント

- 既存の odds キャッシュ（`data/odds/2025-05〜2026-04`）で完結するため
  追加 DL 不要、新規実装は分析スクリプト 1〜2 本のみで小コスト
- バイアスが見つからなかった場合は B-1 で撤退、案 A 完全凍結に戻る
- 詳細計画: [NEXT_PHASE_B1_PLAN.md](NEXT_PHASE_B1_PLAN.md)
- 次セッション: [NEXT_SESSION_PROMPT.md](NEXT_SESSION_PROMPT.md)

---

## フェーズ2 ローカル設定手順（GitHub Actions を動かすために必要な作業）

GitHub Actions ワークフローが正しく動くには、以下の設定をリポジトリ側で行う必要があります。

### 1. GitHub Secrets の設定

GitHub リポジトリの **Settings → Secrets and variables → Actions → New repository secret** で以下を登録してください。

| Secret 名 | 値 | 用途 |
|-----------|-----|------|
| `BACKTEST_DATABASE_URL` | Neon の接続文字列（`postgresql://...`） | `run_backtest.py` からの DB 接続（再学習時に必要） |

> **注意**: `DATABASE_URL` は本番用（predict/collect 等）で別途使用中のため、バックテスト専用に `BACKTEST_DATABASE_URL` という別名を使います。
> `BACKTEST_DATABASE_URL` がなくてもバックテスト本体（ファイルキャッシュ利用）は動きますが、`--retrain` 実行時に model_versions テーブルへの書き込みが失敗します。

### 2. GitHub Labels の作成

Issue 起票で使用するラベルを事前に作成してください。

```bash
# GitHub CLI でラベルを作成
gh label create "auto-loop" --color "0075ca" --description "自律バックテストループの自動起票"
gh label create "needs-investigation" --color "e4e669" --description "調査が必要なアラート"
```

または GitHub の **Issues → Labels → New label** から手動で作成してください。

### 3. GitHub Actions の権限設定

**Settings → Actions → General → Workflow permissions** を確認し、以下を設定してください:

- **Read and write permissions** を選択（kpi_history.jsonl の git commit push に必要）
- **Allow GitHub Actions to create and approve pull requests** にチェック（フェーズ3以降で必要）

### 4. ワークフローの動作確認

設定後、手動でトリガして動作確認してください。

```bash
# workflow_dispatch でテスト実行（前月分 = 2026-03 でテスト）
gh workflow run auto_backtest_loop.yml \
  -f year=2026 -f month=3 -f force_issue=true

# 四半期 Walk-Forward テスト（3ヶ月分）
gh workflow run quarterly_walkforward.yml \
  -f end_month=2026-03 -f window_months=3
```

### 5. スケジュール確認

| ワークフロー | スケジュール | 内容 |
|-------------|------------|------|
| `auto_backtest_loop.yml` | 毎月1日 00:00 UTC | 前月分バックテスト → gate_check → 異常時 Issue 起票 |
| `quarterly_walkforward.yml` | 1/1, 4/1, 7/1, 10/1 の 01:00 UTC | 直近6ヶ月 Walk-Forward → kpi_history 更新 |

### 6. 初回実行後の確認事項

- `artifacts/kpi_history.jsonl` に行が追記されること
- `artifacts/gate_result_YYYYMM.json` が保存されること
- warning / danger ゾーンの場合は Issue が自動起票されること
- kpi_history の変更が `main` ブランチに push されること

---

## 進捗サマリ

| フェーズ | 完了 / 総数 | 状態 |
|---------|------------|------|
| 0. ローカル再現性 | 4 / 4 ✅ | |
| 1. 評価ゲート | 3 / 3 ✅ | |
| 2. 外ループ | 3 / 3 ✅ | |
| 3. 内ループ | 5 / 5 ✅ | ⚠️ **凍結中**（再開は /model-loop 黒字化後） |
| 4. PR フィードバック | 0 / 3 | ⚠️ **連動凍結**（フェーズ3 再開まで着手しない） |
| 5. 観測性 | 0 / 3 | 優先度低（/model-loop 結果を見てから判断） |
| 6. モデル構造ループ | 9 / 10 | 🔴 **最優先**（6-8/6-9 完了、6-10 構造変更フェーズ進行中） |
| **合計** | **24 / 31** | |

## 変更履歴

- 2026-04-24: 初版作成
- 2026-04-24: フェーズ 0 完了（`.env.example`, `docker-compose.yml`, `docker/init-db.sh`, `SETUP.md`, `ml/src/scripts/smoke_test.py`）
- 2026-04-24: フェーズ 0 動作確認完了（Windows / Python 3.12 / Neon DB で `Smoke test passed.` 確認）。知見を補足事項に追記。`SETUP.md` に Python 3.12 推奨を明記。
- 2026-04-24: フェーズ 1 完了（`run_gate_check.py`, `kpi_history.jsonl` 追記, `test_no_regression.py`）。`backtest_202512.csv`（合成オッズ）で動作確認済み。
- 2026-04-24: フェーズ 2 完了（`auto_backtest_loop.yml`, `auto_loop_alert.md`, `quarterly_walkforward.yml`）。ローカル構築手順は下記「フェーズ2 ローカル設定手順」セクション参照。
- 2026-04-24: フェーズ 3 完了（`claude_fix.yml`, `.claude/AGENT_BRIEF.md`, `ml/configs/strategy_default.yaml`, `.github/CODEOWNERS`）。`run_backtest.py` に `--strategy-config` オプション追加。ローカル設定手順は「フェーズ3 ローカル設定手順」セクション参照。
- 2026-04-24: フェーズ 3 設計変更: ANTHROPIC_API_KEY 不要な構成に変更。Claude（ローカルセッション）がオーケストレーターとなり `gh workflow run` で GitHub Actions をキック → artifacts 取得 → 分析・修正・再実行のループを回す。`claude_fix.yml` を `workflow_dispatch` のみのシンプルなワークフローに書き直し。
- 2026-04-24: `/inner-loop` スラッシュコマンドを追加（`.claude/commands/inner-loop.md`）。CLAUDE.md に内ループ運用章を追記し、「バックテストは GitHub Actions 経由必須」を明記。AGENT_BRIEF.md をパラメータ調整ガイドラインに整理。
- 2026-04-24: フェーズ 6 追加（モデル構造ループ `/model-loop`、ローカル実行）。タスク 1〜5（trainer 拡張 / walkforward 拡張 / run_model_loop / 初期 trial seeds 8 本 / スラッシュコマンド）完了。タスク 6（ドキュメント更新）完了。§7-6 smoke 動作確認も合格。本番 8 trial 連続実行（6-8）は `data/odds/2025-05〜2026-04` の DL 完了待ち。設計書: [MODEL_LOOP_PLAN.md](MODEL_LOOP_PLAN.md)
- 2026-04-24: **フェーズ 3 凍結決定**（[PR #3](https://github.com/canaler1215/boatrace/pull/3) マージ）。3 エージェント独立相互レビューの結果、Critical バグ 4 件（C1/C3/C4/C5）を修正しつつ、BET_RULE_REVIEW §30-32 の結論（フィルタ探索では out-of-sample 黒字化不能）と単月評価の誤採択リスクを理由に凍結。再開は `/model-loop` で通算 ROI ≥ 0% を達成し、採択ロジックを多月ホールドアウト評価に再設計してから。フェーズ4（PR フィードバック）も連動凍結。タスク 3-5（相互レビュー Critical バグ修正）を追記。
- 2026-04-24: AUTO_LOOP_PLAN.md の進捗サマリに状態列を追加、フェーズ3 凍結と最優先フェーズ6 を可視化（PR #4 マージ）。
- 2026-04-25: **フェーズ 6 タスク 6-8 完了**（本番 10 trial 連続実行）。T07_window_2024_plus_weight のみ verdict=pass（ROI +15.30%, worst -35.16%, CI 下限 +1.94）。T00/T08/T09 の seed 反復で ROI range 9.3pp / worst range 26.4pp の大きな変動を確認し、T07 の pass は seed ガチャ可能性あり。次イテレーションとして T10〜T12（T07 近傍確証 + 直近強調感度）を設計、タスク 6-9 として起票。詳細: [MODEL_LOOP_RESULTS.md](MODEL_LOOP_RESULTS.md)。
- 2026-04-25: **フェーズ 6 タスク 6-9 完了**（T07 近傍 T10〜T12 確証サイクル）。T10/T11 の T07 seed 再現は 0/2（T10 fail: ROI -17.19%, T11 marginal: ROI +9.47%）、T12（直近強調強化）も ROI -1.93% で敗北。T07/T10/T11 の ROI std 17.32pp / range 32.49pp は baseline seed 反復を更に上回り、**T07 pass は seed ガチャと確定**。通算 13 trial で pass 再現 0 本、β(1,1) 事前 + 観測で P(p>10%) ≒ 15% に低下。タスク 6-10（構造変更フェーズ）へ移行、第一着手は特徴量拡張 PoC（要 `ml/src/features/` 変更禁止パス解除合意）。
