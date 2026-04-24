# ローカルセットアップ手順

競艇予想システムをローカルで動かすための手順書。

## 前提ソフトウェア

| ソフトウェア | バージョン | 用途 |
|-------------|-----------|-----|
| Python | 3.11+ | ML パイプライン |
| Docker Desktop | 最新 | PostgreSQL |
| Git | 任意 | ソース管理 |
| lhasa | 任意（Linux/WSL） | LZH 展開（データ取得に必要） |

> **Windows ユーザーへ**: `lhasa` は Windows ネイティブで動作しません。
> データ取得（`run_collect.py`）は **WSL2 上の Ubuntu** で実行してください。
> バックテスト・予測・再学習は Windows / WSL どちらでも動作します。

---

## 手順

### 1. リポジトリ取得

```bash
git clone https://github.com/canaler2703/boatrace.git
cd boatrace
```

### 2. 環境変数ファイルを作成

```bash
cp .env.example .env
```

ローカル Docker を使う場合は `.env` の変更不要（デフォルト値がそのまま使えます）。

Neon など外部 PostgreSQL を使う場合は `DATABASE_URL` を書き換えてください。

### 3. PostgreSQL を起動（Docker）

```bash
docker compose up -d
```

初回起動時に `apps/web/lib/db/migrations/` のマイグレーションが自動適用されます。

起動確認:

```bash
docker compose ps
# db コンテナが healthy になるまで待つ
```

### 4. Python 依存関係をインストール

> **Python バージョン**: **3.12 を推奨**。pandas 2.2.3 等のビルド済みホイールが 3.12 向けに提供されており、3.13 以上ではビルドエラーになる場合があります。

```cmd
rem Windows: py ランチャーで 3.12 を明示
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r ml/requirements.txt
```

```bash
# Linux / macOS / WSL
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r ml/requirements.txt
```

### 5. Smoke test で疎通確認

```cmd
py -3.12 ml/src/scripts/smoke_test.py
```

以下が出力されれば OK:

```
[OK] DATABASE_URL が設定されています
[OK] PostgreSQL に接続できました
[OK] 必須テーブルが存在します
[OK] バックテストが 1 日分完走しました（合成オッズ）
Smoke test passed.
```

---

## よく使うコマンド

```bash
# バックテスト（合成オッズ、高速）
python ml/src/scripts/run_backtest.py --year 2025 --month 12

# バックテスト（実オッズ、初回 ~90 分）
python ml/src/scripts/run_backtest.py --year 2025 --month 12 --real-odds --retrain

# モデル再学習
python ml/src/scripts/run_retrain.py

# 当日予測
python ml/src/scripts/run_predict.py
```

詳細オプションは `CLAUDE.md` の「よく使うコマンド」セクションを参照。

---

## トラブルシューティング

### `DATABASE_URL` 未設定エラー

```
KeyError: 'DATABASE_URL'
```

`.env` ファイルが存在するか確認し、スクリプト実行前に読み込まれているか確認:

```bash
# python-dotenv を使っている場合は自動読み込み済み
# 手動でも可
export $(cat .env | grep -v '^#' | xargs)
```

### Docker が起動しない

```bash
docker compose logs db
```

ポート 5432 が占有されている場合は `docker-compose.yml` の `ports` を変更してください。

### `lhasa: command not found`

WSL2 (Ubuntu) で実行してください:

```bash
sudo apt-get install -y lhasa
```

Windows の場合はデータ取得をスキップして既存の `data/` キャッシュを利用するか、
WSL 環境でデータ取得後に Windows 側でバックテストを実行してください。
