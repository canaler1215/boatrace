# 競艇予想アプリ 設計書

## 概要

過去レース結果を統計・機械学習で分析し、期待値1.2以上の舟券のみアラート表示するアプリ。
券の購入はユーザーが手動で行う。

---

## 技術スタック

| レイヤー | 採用技術 |
|---|---|
| フロントエンド/API | Next.js 15 (App Router) + TypeScript + tRPC |
| UI | shadcn/ui + Tailwind CSS v4 |
| DB | Neon (PostgreSQL) + Drizzle ORM |
| MLエンジン | Python（GitHub Actions上で実行） |
| モデル保存 | GitHub Actions cache / Neon に結果書き込み |
| スケジューラー | GitHub Actions Cron |
| 認証 | NextAuth.js v5 |
| CI/CD | GitHub Actions |
| 実行環境 | Vercel |
| バージョン管理 | GitHub |

---

## システムアーキテクチャ

```
BoatraceOpenAPI / 公式CSV（2002年〜）
        ↓
GitHub Actions Cron（毎時）
  ├── collect.yml  : データ収集 → Neon に upsert
  └── predict.yml  : LightGBM推論 → 期待値計算 → Neon に upsert
        ↓
alert_flag=true（EV >= 1.2）
        ↓
Next.js ダッシュボード（Vercel）に表示
        ↓
ユーザーが手動購入判断 → 購入記録を入力
        ↓
レース後に的中判定・収支管理
```

**GitHub Actions を選んだ理由:**
- Python + LightGBM が追加サービスなしでそのまま動く
- ジョブあたり最大6時間実行可能（初期学習にも対応）
- プライベートリポジトリで月2,000分無料
- Secretsで DATABASE_URL を安全に管理できる
- Modal.com・Vercel Cronなど追加サービス不要でシンプル

---

## データソース

| ソース | 内容 | 形式 |
|---|---|---|
| BoatraceOpenAPI (GitHub) | レース情報・出走表・直前情報 | JSON・30分更新 |
| boatrace.jp 公式 | 2002年〜の歴史データ | LZH/CSV |
| スクレイピング | エンジン性能指数・オッズ | HTML |

※公式サイト規約で大量スクレイピング禁止。スクレイピングは最小限に。

---

## 予測モデル

### 使用特徴量（重要度順・約60次元）

1. **展示タイム** — 直線スピード・最重要
2. **モーター2連率** — 40%以上が高性能
3. **ボート2連率**
4. **コース番号（1〜6）** — 1コース全国平均勝率55.9%
5. **選手勝率・級別（A1/A2/B1/B2）**
6. **スタートタイミング(ST)**
7. **潮位** — 満潮→内有利、干潮→外有利
8. **レース場特性** — 大村・尼崎はイン強（68%超）、江戸川は荒れやすい（44%）
9. **風向** — 向かい風→内有利、追い風→外有利

### モデル構成

- **アルゴリズム:** LightGBM（各艇の1着確率を推定 → 3連単確率を近似計算）
- **再学習:** 月1回（GitHub Actions Job・約4時間）
- **モデルファイル保存:** `model_versions` テーブルのURLカラム + GitHub Releases（.pkl添付）
- **現実的な回収率水準:** 約98%

---

## 期待値計算

```
期待値 = 的中確率 × オッズ

例: 的中確率5% × オッズ25倍 = 期待値 1.25 → 購入推奨
```

- 控除率: 全券種一律25%（理論還元率75%）
- **購入判断閾値: 期待値 1.2以上**
- Kelly基準: `ベット割合 = (期待値 - 1) / (オッズ - 1)`（保守的に1/4 Kelly推奨）

---

## ディレクトリ構造

```
boatrace-predictor/
├── .github/workflows/
│   ├── ci.yml                 # PR時: lint・typecheck・test
│   ├── deploy-web.yml         # main→Vercelデプロイ
│   ├── collect.yml            # Cron: データ収集（毎時）
│   ├── predict.yml            # Cron: 推論・期待値計算（毎時）
│   └── retrain.yml            # Cron: モデル再学習（月1回）
│
├── apps/web/                  # Next.js 15 (Vercel)
│   ├── app/
│   │   ├── dashboard/         # 本日のEV上位レース一覧
│   │   ├── races/[id]/        # 予測詳細・オッズ表
│   │   ├── bets/              # 購入記録（手動入力）
│   │   └── analytics/         # 収支・回収率グラフ
│   ├── lib/
│   │   ├── db/
│   │   │   ├── index.ts       # Drizzle + Neon接続
│   │   │   └── schema.ts      # 全テーブルスキーマ定義
│   │   ├── trpc/routers/      # races・predictions・bets・analytics
│   │   └── utils/ev.ts        # 期待値計算ロジック
│   └── vercel.json
│
├── ml/                        # Python（GitHub Actions で実行）
│   ├── requirements.txt
│   └── src/
│       ├── collector/
│       │   ├── openapi_client.py   # BoatraceOpenAPI取得
│       │   ├── history_downloader.py # 公式歴史データ取得
│       │   └── db_writer.py        # Neon upsert (psycopg3)
│       ├── features/
│       │   ├── feature_builder.py  # 特徴量生成メイン
│       │   ├── tidal_features.py   # 潮位特徴量
│       │   └── stadium_features.py # 競艇場特性特徴量
│       ├── model/
│       │   ├── trainer.py          # LightGBM 学習
│       │   ├── predictor.py        # 推論・期待値計算
│       │   └── evaluator.py        # RPS・精度評価
│       └── scripts/
│           ├── run_collect.py      # collect.yml から呼び出し
│           ├── run_predict.py      # predict.yml から呼び出し
│           └── run_retrain.py      # retrain.yml から呼び出し
│
└── packages/types/            # 共有型定義（TS）
```

---

## GitHub Actions ワークフロー設計

### collect.yml（データ収集・毎時30分）

```yaml
name: Collect Race Data
on:
  schedule:
    - cron: '30 * * * *'   # 毎時30分
  workflow_dispatch:         # 手動実行も可

jobs:
  collect:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r ml/requirements.txt
      - run: python ml/src/scripts/run_collect.py
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
```

### predict.yml（推論・期待値計算・毎時00分）

```yaml
name: Predict & Calculate EV
on:
  schedule:
    - cron: '0 * * * *'    # 毎時00分
  workflow_dispatch:

jobs:
  predict:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r ml/requirements.txt
      - name: Download latest model
        run: python ml/src/scripts/download_model.py
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      - run: python ml/src/scripts/run_predict.py
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
```

### retrain.yml（月次再学習・毎月1日 2:00）

```yaml
name: Retrain Model
on:
  schedule:
    - cron: '0 2 1 * *'    # 毎月1日 2:00 UTC
  workflow_dispatch:

jobs:
  retrain:
    runs-on: ubuntu-latest
    timeout-minutes: 360    # 最大6時間
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r ml/requirements.txt
      - run: python ml/src/scripts/run_retrain.py
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      # 成果物をGitHub Releasesにアップロード
      - uses: softprops/action-gh-release@v2
        with:
          tag_name: model-${{ github.run_id }}
          files: ml/artifacts/model_*.pkl
```

---

## DBテーブル設計

| テーブル | 主な内容 |
|---|---|
| stadiums | 競艇場マスタ（水面種別・特性） |
| racers | 選手マスタ（勝率・級別・体重） |
| races | レース情報（場・日付・グレード・状態） |
| race_entries | 出走表（艇番・展示タイム・モーター率・ST・着順） |
| odds | 3連単オッズ（30分毎スナップショット） |
| tidal_data | 潮位データ |
| predictions | ML予測結果（各艇1着確率・期待値・alert_flag） |
| bets | 購入記録（手動入力・的中判定・払戻） |
| model_versions | MLモデルバージョン管理（GitHub Releases URL） |

**race_id形式:** `{stadium_id}{yyyymmdd}{race_no}` 例: `012024120901`

---

## スケジュール（レース当日）

```
毎時30分  GitHub Actions: データ収集（BoatraceOpenAPI → Neon）
毎時00分  GitHub Actions: 推論・期待値計算 → alert_flag更新
          EV >= 1.2 のレースがあればダッシュボードに表示
          ユーザーが確認 → 手動購入判断
各レース後  次の収集サイクルで結果取得・的中判定
月1日     GitHub Actions: LightGBM再学習（最大6時間）
```

---

## コスト概算（月額）

| サービス | プラン | 月額 |
|---|---|---|
| Vercel | Hobby | $0 |
| Neon | Free Tier | $0 |
| GitHub Actions | プライベートRepo: 月2,000分無料 | $0 |
| **合計** | | **$0/月** |

※GitHub Actions の消費目安: 収集(毎時・約2分) + 推論(毎時・約3分) = 約360分/月。無料枠内に収まる。

---

## 実装手順

1. リポジトリ作成（Turborepoモノレポ）+ Next.js初期セットアップ
2. Neon接続 + Drizzleスキーマ定義 + マイグレーション実行
3. `ml/src/collector/` 実装 + `collect.yml` でBoatraceOpenAPI疎通確認
4. 初期MLモデル訓練（`retrain.yml` を手動実行・公式歴史データ2002年〜）
5. `ml/src/scripts/run_predict.py` 実装 + `predict.yml` 動作確認
6. Next.jsダッシュボード・各画面実装
7. GitHub Actions CI/CD設定（deploy-web.yml）

---

## ブランチ戦略

```
main        本番（Vercel本番・GitHub Actions本番）
  └── develop   開発統合（Vercel Preview）
        ├── feature/xxx
        ├── fix/xxx
        └── chore/xxx
```

- mainへの直接push禁止
- PRはすべてdevelopへ
- develop→mainは週次またはリリース判断時にSquash merge

---

## GitHub Secrets 設定（リポジトリSettings > Secrets）

| Secret名 | 内容 |
|---|---|
| `DATABASE_URL` | Neon の接続文字列 |
| `VERCEL_TOKEN` | Vercel デプロイ用トークン |
| `VERCEL_ORG_ID` | Vercel 組織ID |
| `VERCEL_PROJECT_ID` | Vercel プロジェクトID |
