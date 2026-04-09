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
| MLエンジン | Python + Modal.com |
| キャッシュ | Vercel KV (Redis) |
| モデル保存 | Cloudflare R2 |
| スケジューラー | Vercel Cron + Modal Cron |
| 認証 | NextAuth.js v5 |
| CI/CD | GitHub Actions |
| 実行環境 | Vercel |
| バージョン管理 | GitHub |

---

## システムアーキテクチャ

```
BoatraceOpenAPI / 公式CSV（2002年〜）
        ↓
Modal Cron（毎時30分）→ Neon に収集・更新
        ↓
Vercel Cron → Modal predict エンドポイント呼び出し
        ↓
LightGBM推論 → 期待値計算 → alert_flag設定（EV >= 1.2）
        ↓
Next.js ダッシュボードに表示 → ユーザーが手動購入判断
        ↓
購入記録を手動入力 → レース後に的中判定・収支管理
```

**Vercel制限への対処:**
- VercelはPython非対応・実行時間10秒制限（Hobby）
- ML学習・推論・データ収集バッチはすべてModal.comに委託
- Vercel Cronはモーダルへのトリガー投げのみ（即時200返却）

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
- **再学習:** 月1回（Modal Job・約4時間）
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
│   └── deploy-modal.yml       # ml/変更→Modalデプロイ
│
├── apps/web/                  # Next.js 15 (Vercel)
│   ├── app/
│   │   ├── dashboard/         # 本日のEV上位レース一覧
│   │   ├── races/[id]/        # 予測詳細・オッズ表
│   │   ├── bets/              # 購入記録（手動入力）
│   │   ├── analytics/         # 収支・回収率グラフ
│   │   └── api/
│   │       ├── trpc/          # tRPCハンドラー
│   │       └── cron/          # Vercel Cron（Modalトリガーのみ）
│   ├── lib/
│   │   ├── db/
│   │   │   ├── index.ts       # Drizzle + Neon接続
│   │   │   └── schema.ts      # 全テーブルスキーマ定義
│   │   ├── trpc/routers/      # races・predictions・bets・analytics
│   │   └── utils/ev.ts        # 期待値計算ロジック
│   └── vercel.json            # Cron設定
│
├── ml/                        # Python (Modal.com)
│   ├── modal_app.py           # エントリーポイント
│   └── src/
│       ├── collector/         # BoatraceOpenAPI取得・Neon書き込み
│       ├── features/          # 特徴量生成（60次元）
│       ├── model/             # LightGBM 学習・推論・評価
│       └── pipeline/          # Cron・Endpoint・再学習Job
│
└── packages/types/            # 共有型定義
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
| model_versions | MLモデルバージョン管理 |

**race_id形式:** `{stadium_id}{yyyymmdd}{race_no}` 例: `012024120901`

---

## スケジュール（レース当日）

```
06:00  当日レース情報取得（Modal Cron）
09:30  展示タイム・オッズ取得（Modal Cron）
10:00  最終予測実行 → EV >= 1.2 でalert_flag=true
10:15  ユーザーが手動購入判断・記録入力
各レース後+10分  結果取得・的中判定（Modal Cron）
月1日  LightGBMモデル再学習（Modal Job・約4時間）
```

---

## コスト概算（月額）

| サービス | プラン | 月額 |
|---|---|---|
| Vercel | Hobby | $0 |
| Neon | Free Tier | $0 |
| Modal.com | 使用量課金 | $3〜$15 |
| Cloudflare R2 | 10GB無料 | $0 |
| **合計** | | **$3〜$15/月** |

---

## 実装手順

1. リポジトリ作成（Turborepoモノレポ）+ Next.js初期セットアップ
2. Neon接続 + Drizzleスキーマ定義 + マイグレーション実行
3. Modal.comセットアップ + BoatraceOpenAPI疎通確認
4. データ収集パイプライン実装（collector/）
5. 初期MLモデル訓練（公式歴史データ2002年〜）
6. Next.jsダッシュボード・各画面実装
7. Vercel Cron + Modal 連携
8. GitHub Actions CI/CD設定

---

## ブランチ戦略

```
main        本番（Vercel本番・Modal本番）
  └── develop   開発統合（Vercel Preview）
        ├── feature/xxx
        ├── fix/xxx
        └── chore/xxx
```

- mainへの直接push禁止
- PRはすべてdevelopへ
- develop→mainは週次またはリリース判断時にSquash merge
