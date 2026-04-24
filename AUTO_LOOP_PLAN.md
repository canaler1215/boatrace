# バックテスト自律改善ループ 実装計画

claude code agent がバックテスト実行 → 分析 → 対策立案 → 実装 → 再検証を自律反復する仕組みの実装計画。

## ステータス凡例
- `[ ]` 未着手
- `[~]` 着手中
- `[x]` 完了
- `[!]` ブロック中／保留（理由を注記）
- `[-]` スキップ／不要と判断

最終更新: 2026-04-24（フェーズ3 完了）

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

| フェーズ | 完了 / 総数 |
|---------|------------|
| 0. ローカル再現性 | 4 / 4 ✅ |
| 1. 評価ゲート | 3 / 3 ✅ |
| 2. 外ループ | 3 / 3 ✅ |
| 3. 内ループ | 4 / 4 ✅ |
| 4. PR フィードバック | 0 / 3 |
| 5. 観測性 | 0 / 3 |
| **合計** | **14 / 20** |

## 変更履歴

- 2026-04-24: 初版作成
- 2026-04-24: フェーズ 0 完了（`.env.example`, `docker-compose.yml`, `docker/init-db.sh`, `SETUP.md`, `ml/src/scripts/smoke_test.py`）
- 2026-04-24: フェーズ 0 動作確認完了（Windows / Python 3.12 / Neon DB で `Smoke test passed.` 確認）。知見を補足事項に追記。`SETUP.md` に Python 3.12 推奨を明記。
- 2026-04-24: フェーズ 1 完了（`run_gate_check.py`, `kpi_history.jsonl` 追記, `test_no_regression.py`）。`backtest_202512.csv`（合成オッズ）で動作確認済み。
- 2026-04-24: フェーズ 2 完了（`auto_backtest_loop.yml`, `auto_loop_alert.md`, `quarterly_walkforward.yml`）。ローカル構築手順は下記「フェーズ2 ローカル設定手順」セクション参照。
- 2026-04-24: フェーズ 3 完了（`claude_fix.yml`, `.claude/AGENT_BRIEF.md`, `ml/configs/strategy_default.yaml`, `.github/CODEOWNERS`）。`run_backtest.py` に `--strategy-config` オプション追加。ローカル設定手順は「フェーズ3 ローカル設定手順」セクション参照。
- 2026-04-24: フェーズ 3 設計変更: ANTHROPIC_API_KEY 不要な構成に変更。Claude（ローカルセッション）がオーケストレーターとなり `gh workflow run` で GitHub Actions をキック → artifacts 取得 → 分析・修正・再実行のループを回す。`claude_fix.yml` を `workflow_dispatch` のみのシンプルなワークフローに書き直し。
- 2026-04-24: `/inner-loop` スラッシュコマンドを追加（`.claude/commands/inner-loop.md`）。CLAUDE.md に内ループ運用章を追記し、「バックテストは GitHub Actions 経由必須」を明記。AGENT_BRIEF.md をパラメータ調整ガイドラインに整理。
