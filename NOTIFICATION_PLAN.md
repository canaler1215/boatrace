# ベット条件合致レース通知機能 計画書

## 背景・目的

`run_predict.py` で抽出された購入候補レース（prob ≥ 7%, EV ≥ 2.0 等の条件を満たすレース）を、
リアルタイムにユーザーのスマホへ通知する仕組みを導入する。

現状: 購入候補は CSV / 標準出力にしか出ておらず、ユーザーが能動的に確認しないと気づけない。
理想: 条件合致レースが検出された瞬間に、スマホで PUSH 通知として受信したい。

## 要件

- **最優先**: コスト 0 円
- **次点**: 実装・運用の難易度が低いこと
- **理想**: スマホへの PUSH 通知
- **許容**: メール通知
- 複数レースを一度に通知することがある（1日数十件レベル）

## 通知方法の比較表

| 方法 | コスト | 難易度 | PUSH通知 | 即時性 | 備考 |
|------|--------|--------|---------|--------|------|
| **Discord Webhook** | 無料 | ★☆☆☆☆ | ○ | 即時 | アプリ必須。リッチ表示可 |
| **Slack Webhook** | 無料 | ★☆☆☆☆ | ○ | 即時 | Discord と同等 |
| **ntfy.sh** | 無料 | ★☆☆☆☆ | ○ | 即時 | アカウント不要、OSS |
| **Gmail SMTP** | 無料 | ★★☆☆☆ | △（Gmailアプリ経由） | 数秒〜数十秒 | アプリパスワード発行要 |
| **LINE Messaging API** | 月200通まで無料 | ★★★☆☆ | ○ | 即時 | 旧LINE Notifyは2025-03-31終了済み |
| **Pushover** | $5買い切り | ★★☆☆☆ | ○ | 即時 | 通知特化、UI優秀 |

## 推奨構成

### メインチャンネル: Discord Webhook
- コスト 0 円、30 分で実装可能
- スマホの Discord アプリで PUSH 通知受信
- 表形式・リンク・色分けなどリッチな表示が可能
- 通知履歴がサーバーに残るので後から確認できる

### バックアップチャンネル: Gmail SMTP
- Discord が障害時の冗長化
- 検索性が高く、長期ログとしても機能
- 完全無料

### 将来の拡張候補
- ntfy.sh（Discord アカウント不要にしたい場合）
- LINE Messaging API（家族・複数人共有が必要になった場合）

## 実装ステップ

### Phase 1: Discord Webhook 導入（所要 1〜2 時間）

#### Step 1-1. Discord サーバー作成
1. Discord デスクトップ / Web 版にログイン
2. サイドバーの「+」から「サーバーを作る」→「自分用」
3. サーバー名は任意（例: `boatrace-alerts`）
4. チャンネルは `#bet-candidates` を作成

#### Step 1-2. Webhook URL 発行
1. 作成したチャンネルの歯車アイコン → 「連携サービス」
2. 「ウェブフック」→「新しいウェブフック」
3. 名前を `boatrace-bot` などに設定
4. 「ウェブフック URL をコピー」で URL 取得
5. URL 形式: `https://discord.com/api/webhooks/<ID>/<TOKEN>`

#### Step 1-3. 環境変数化
1. プロジェクトルートに `.env`（既存であればそれに追記）を作成
2. `DISCORD_WEBHOOK_URL=<コピーしたURL>` を記入
3. `.gitignore` に `.env` が含まれているか確認（含まれていなければ追加）

#### Step 1-4. 通知モジュール実装
- 配置: `ml/src/notifier/discord_notifier.py`
- 機能:
  - `send_bet_candidates(candidates: list[dict]) -> None`
  - 1 件ずつ送ると rate limit に引っかかるため、1 メッセージに複数レースを埋め込む
  - Discord の Embed 形式を使い、会場・R 番号・組番・確率・EV・オッズを表形式で表示
  - 失敗時は `logging.warning` でスキップ（本体処理は止めない）

#### Step 1-5. run_predict.py への組み込み
- 購入候補の CSV 出力直後に通知フックを呼ぶ
- `--notify` フラグで ON/OFF 切り替え可能に（デフォルトは OFF にして破壊的変更を避ける）
- 環境変数 `DISCORD_WEBHOOK_URL` が未設定ならスキップ

#### Step 1-6. スマホ側設定
1. iOS / Android の Discord アプリをインストール
2. 作成したサーバーにログイン
3. `#bet-candidates` チャンネルの通知設定を「すべてのメッセージ」に
4. OS 側の通知権限を Discord アプリに付与

#### Step 1-7. 動作確認
1. 過去レースで `run_predict.py --notify` を手動実行
2. スマホで PUSH 通知が来ることを確認
3. 表示内容（会場・確率・EV）が想定通りか確認

### Phase 2: Gmail SMTP 導入（所要 1 時間、Phase 1 動作確認後）

#### Step 2-1. Gmail アプリパスワード発行
1. Google アカウントで 2 段階認証を有効化（未設定の場合）
2. [Google アカウント → セキュリティ → アプリ パスワード](https://myaccount.google.com/apppasswords)
3. 「アプリ」に `boatrace-notifier` などの名前を入力して生成
4. 16 桁のパスワードを控える

#### Step 2-2. 環境変数追加
- `.env` に以下を追記:
  - `GMAIL_ADDRESS=canaler2703@gmail.com`
  - `GMAIL_APP_PASSWORD=<16桁>`
  - `NOTIFY_EMAIL_TO=canaler2703@gmail.com`（自分宛）

#### Step 2-3. メール通知モジュール実装
- 配置: `ml/src/notifier/email_notifier.py`
- Python 標準 `smtplib` + `email.mime` を使用
- SMTP サーバー: `smtp.gmail.com:587`（STARTTLS）
- 件名: `[boatrace] N件のベット候補 (YYYY-MM-DD HH:MM)`
- 本文: プレーンテキストで候補一覧（Discord と同等情報）

#### Step 2-4. 統合ファサード実装
- 配置: `ml/src/notifier/__init__.py`
- `notify_bet_candidates(candidates)` で Discord と Gmail の両方を呼ぶ
- どちらかが失敗しても続行（片方が落ちても通知が完全に止まらない）

#### Step 2-5. 動作確認
1. `run_predict.py --notify` で Discord・メール両方に通知が届くか確認
2. iOS / Android の Gmail アプリで PUSH 通知が来ることを確認
3. Gmail アプリの通知設定を「高優先度」に調整

### Phase 3: 運用設計（所要 30 分）

#### Step 3-1. 実行スケジュール決定
- `run_predict.py --notify` をいつ実行するか
- 候補:
  - 手動実行（当面はこれで十分）
  - Windows タスクスケジューラで定時実行（例: 毎日 9:00, 12:00, 15:00）
  - Claude Code の `/schedule` スキルで cron トリガー

#### Step 3-2. 通知内容のチューニング
- 1 日あたりの通知件数を確認（S6-3 実績だと月 2,600 件前後 = 日 85 件前後）
- **重要**: 現状の条件では通知数が多すぎる可能性が高い
- 対策候補:
  - 閾値を厳しくする（例: `--prob-threshold 0.10 --ev-threshold 3.0`）
  - 上位 N 件のみ通知
  - サマリー通知（件数だけ）＋ 詳細は CSV 参照

#### Step 3-3. エラー監視
- 通知失敗時のログを `logs/notifier.log` に出力
- 連続失敗時は標準出力に大きく警告表示

### Phase 4: 拡張（任意）

#### Step 4-1. 的中結果のフォローアップ通知
- レース結果取得後、事前通知した候補の的中/外れを集計して 1 日 1 回送信
- 既存 `fetch_race_results` スクリプトとの連携

#### Step 4-2. オッズ変動アラート
- 通知時点のオッズと発走直前オッズを比較し、乖離が大きい場合に再通知

#### Step 4-3. ntfy.sh / LINE への拡張
- Discord 以外で受け取りたい要望が出た場合に追加

## ファイル構成（予定）

```
ml/src/notifier/
  __init__.py              ファサード (notify_bet_candidates)
  discord_notifier.py      Discord Webhook 送信
  email_notifier.py        Gmail SMTP 送信
  formatter.py             候補データの整形（Discord Embed / メール本文）
.env                       DISCORD_WEBHOOK_URL, GMAIL_* を格納
.gitignore                 .env を除外
```

## セキュリティ上の注意

- Webhook URL / アプリパスワードは **絶対にコミットしない**
- `.env` は `.gitignore` で除外
- 公開リポジトリでないことを念のため確認
- Webhook URL が漏れた場合は Discord 側で即時再生成可能

## 判断が必要なポイント

1. 通知の粒度（全候補 vs 上位 N 件 vs サマリー）
2. 実行タイミング（手動 vs 定時自動）
3. Gmail SMTP は Phase 1 完了後すぐ入れるか、Discord で十分なら見送るか
4. 通知閾値を現行バックテスト条件と揃えるか、別途厳しくするか

## 進め方の推奨

1. まず Phase 1（Discord 単体）を実装し、数日運用してみる
2. 通知量・体験に満足なら Phase 2 は任意（Gmail は冗長化としてのみ追加）
3. 通知量が多すぎる場合は Phase 3-2 で閾値チューニング
4. 運用が安定したら Phase 3-1 で自動実行化
