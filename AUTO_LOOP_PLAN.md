# バックテスト自律改善ループ 実装計画

claude code agent がバックテスト実行 → 分析 → 対策立案 → 実装 → 再検証を自律反復する仕組みの実装計画。

## ステータス凡例
- `[ ]` 未着手
- `[~]` 着手中
- `[x]` 完了
- `[!]` ブロック中／保留（理由を注記）
- `[-]` スキップ／不要と判断

最終更新: 2026-04-24

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
  - キャッシュデータがない場合は DB チェックのみ実行してスキップ（CI フレンドリー）
  - 完了条件: 完走で exit 0、いずれかの失敗で exit 1

## フェーズ 1: 評価ゲート（KPI 機械判定）

CLAUDE.md の運用ルール（ROI 300/500%/負値）を自動判定し、後続ループのトリガを生む。

- [ ] **1-1. `ml/src/scripts/run_gate_check.py` 新規作成**
  - 入力: `artifacts/backtest_YYYYMM_*.csv`
  - 出力: `artifacts/gate_result_YYYYMM.json`（ROI, ベット数, 的中率, avg odds, ゾーン判定）
  - ゾーン: `normal / caution / warning / danger`（CLAUDE.md 運用ルールに準拠）
  - exit code: `warning` 以下で非0（CI 失敗扱い）
- [ ] **1-2. KPI 履歴台帳 `artifacts/kpi_history.jsonl`**
  - 1 ラン 1 行追記（タイムスタンプ、期間、KPI、ゾーン、commit SHA、model version）
  - `.gitignore` 済みにはせず、PR で履歴を残す運用に
- [ ] **1-3. 回帰防止テスト `ml/tests/test_no_regression.py`**
  - 直近 6 ランの ROI 中央値の 70% を下回る PR は fail
  - agent が閾値を過度に弄って見かけ ROI を悪化させるのを防ぐ

## フェーズ 2: 外ループ（GitHub Actions で定期実行）

cron で定期バックテストを回し、異常検知で Issue を自動起票する。

- [ ] **2-1. `.github/workflows/auto_backtest_loop.yml` 新規作成**
  - トリガ: `schedule: cron: "0 0 1 * *"`（毎月1日）+ `workflow_dispatch`
  - ステップ: モデルDL → 前月分 backtest → gate_check → kpi_history 更新 → 異常時 Issue 起票
- [ ] **2-2. Issue 起票テンプレート**
  - タイトル例: `[auto-loop] 2026-03 ROI +280% (warning zone)`
  - 本文: KPI サマリ、artifact URL、過去 N ヶ月との比較、想定原因チェックリスト
  - ラベル: `auto-loop`, `needs-investigation`
- [ ] **2-3. Walk-Forward モード**
  - 月次だけでなく「直近6ヶ月」を四半期で回す second workflow
  - 完了条件: `run_walkforward.py` のラッパ workflow

## フェーズ 3: 内ループ（Claude Code Action による自律修正）

Issue をトリガに agent が原因分析→修正 PR を作成する。

- [ ] **3-1. Claude Code Action 導入**
  - ワークフロー: `.github/workflows/claude_fix.yml`
  - トリガ: `issue_comment` で `@claude` メンション、または `issues.opened` (label: `auto-loop`)
  - 機密情報を渡せない制約下での認証方式を検討（OAuth / GitHub Models 経由）
- [ ] **3-2. Agent 向けプロンプト整備 `.claude/AGENT_BRIEF.md`**
  - Issue 本文 → 実行すべき分析コマンド（`run_segment_analysis.py`, `run_calibration.py`）
  - 「触ってよい場所」「触ってはいけない場所」の明示
  - 最大イテレーション数・撤退条件
- [ ] **3-3. 戦略パラメータの外出し `ml/configs/strategy_*.yaml`**
  - 現在 `run_backtest.py` の CLI 引数で渡している閾値（prob, ev, exclude_courses, min_odds, exclude_stadiums）を YAML 化
  - agent はこの YAML のみ書き換え可能とする
- [ ] **3-4. CODEOWNERS でガードレール**
  - `ml/src/collector/`, `ml/migrations/`, `.github/workflows/` は人間レビュー必須
  - `ml/configs/`, `ml/src/model/`（閾値周辺）は agent 単独変更可

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

## 進捗サマリ

| フェーズ | 完了 / 総数 |
|---------|------------|
| 0. ローカル再現性 | 4 / 4 ✅ |
| 1. 評価ゲート | 0 / 3 |
| 2. 外ループ | 0 / 3 |
| 3. 内ループ | 0 / 4 |
| 4. PR フィードバック | 0 / 3 |
| 5. 観測性 | 0 / 3 |
| **合計** | **0 / 20** |

## 変更履歴

- 2026-04-24: 初版作成
- 2026-04-24: フェーズ 0 完了（`.env.example`, `docker-compose.yml`, `docker/init-db.sh`, `SETUP.md`, `ml/src/scripts/smoke_test.py`）
