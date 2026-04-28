> # 🛑 (P-v) 凍結後の参照記録 (2026-04-28、Q-B 合意)
>
> 本ドキュメントの実行ループ・改善計画はすべて凍結済み。**新規着手は不可**。
> 設計記録 / 仕様参照としてのみ保持。詳細は [CLAUDE.md](CLAUDE.md)「現行の運用方針」冒頭参照。
>
> 手動レース予想は CLAUDE.md「手動レース予想の手順 (P-v 凍結後)」を参照。

---

# 舟券自動購入 方式検討メモ

作成日: 2026-04-23
関連ドキュメント: [NOTIFICATION_PLAN.md](NOTIFICATION_PLAN.md) / [PREDICT_REALTIME_IMPROVEMENT.md](PREDICT_REALTIME_IMPROVEMENT.md) / [CLAUDE.md](CLAUDE.md)

---

## 1. ゴール

`run_predict.py` + `run_refresh_ev.py` が DB (`predictions`) に書き込んでいる
購入条件合致レース（prob ≥ 7%, EV ≥ 2.0, コース2/4/5除外, オッズ<100x除外,
びわこ除外）を **自動でテレボートに投票**する仕組みを整える。

- **投票対象**: 3連単、1点 100 円（`--kelly-fraction 0.25` 使用時は変動）
- **想定件数**: S6-3 実績で月 ~2,600 件（日 ~85 件、ピーク時刻に集中）
- **運用環境**: Windows 11 (現 dev 環境) + 常時稼働可能な PC/VM

---

## 2. 制度・規約上の制約（結論: グレーだが"節度運用"なら実害リスクは小さい）

### 2-1. 公式規約の明文

[BOAT RACE サイトポリシー](https://www.boatrace.jp/owpc/pc/extra/policy.html) に
"自動投票禁止" の明示条項は**ない**。ただし以下の包括禁止条項が存在する:

> 不正アクセス、大量の情報送受信及び大量のアクセスなど、
> 本サイトの運営に支障を与える行為

→ DoS 的な高頻度アクセスや、複数アカウントでの並列運用は明確にアウト。
1アカウントで人間的ペースならグレー。

### 2-2. テレボート（楽天銀行 / 三菱UFJ 経由）の会員規約

楽天銀行・UFJ 経由の口座開設契約には「本人のみの利用」「他者への
譲渡禁止」は明示されているが、**プログラム経由の操作そのものを
禁じる条項は現時点で確認できず**。ただしアカウント凍結リスクは以下:

| リスク | 引き金 | 実害 |
|-------|--------|------|
| 自動解約 | 1年間ログインなし / 投票なし | 残高精算手続き要・復旧困難 |
| 利用停止 | 不正アクセス・規約違反判定 | 投票不可・残高返金に時間 |
| 凍結・訴訟 | 他人アカウント利用・著作権侵害ツール利用 | 民事・刑事の両面リスク |

Yahoo 知恵袋・個人ブログでは「自動投票使用で即凍結された」
という一次情報は確認できず。**現状、BOAT RACE 側の対抗措置は
"異常アクセス検知 → 一時停止" レベルにとどまる** と推測される。

### 2-3. 過去の判例（[知財弁護士.COM](https://www.ip-bengoshi.com/archives/5279)）

舟券自動購入プログラムに関する著作権侵害訴訟あり。
ただし争点は**他社ソフトの逆コンパイル・無断販売**で、
**購入者側の利用そのものが違法とされた訳ではない**。

→ 「自作」で「自分のアカウントのみ」で使う限り、訴訟リスクは低い。
**ただし他人の自動投票ソフトを買って使うのは供給側のリスクを継承する可能性あり。**

### 2-4. 類似既存ソフト

| ソフト | 方式 | 状態 |
|-------|------|------|
| [KyoteiVBA](https://vba-create.jp/kyoteivba/) | Excel VBA + SeleniumBasic で Chrome/Edge を画面操作 | 現役販売中。数年運用実績あり |
| [teleboat_agent (GitHub)](https://github.com/k0kishima/teleboat_agent) | Ruby + HTTP リクエスト直接叩き | OSS・自己責任運用 |
| [TELEBOAT API (team-nave)](https://www.team-nave.com/system/jp/products/brapi/) | 商用 API ラッパー 3,300円/月 | 個人向け提供、ビジネス利用は別プラン |

→ **既に画面操作型・HTTP 直叩き型の両方が運用されており、
BOAT RACE 側が一律に排除している様子はない**。

### 2-5. 結論

- 公式規約・法律の観点では **明確な違法ではないが完全に安全でもない** グレーゾーン
- 凍結を避ける鍵は **"人間に見える挙動"**（リクエスト間隔、UA、同時接続数、時間帯）
- **自作ツールを自分のアカウントのみで使う**のが最もリスクが低い経路

---

## 3. 実現方式の比較

### 方式A: 自作 HTTP クライアント（テレボート直叩き）

```
predictions DB → auto_bet.py (requests + BeautifulSoup) → テレボート HTTP POST
```

| 観点 | 評価 |
|------|------|
| 実装コスト | 中（ログイン・投票 POST の仕様解析が必要） |
| 安定性 | 低（テレボート UI 変更で即破綻） |
| 凍結リスク | **中〜高**（通常ブラウザと異なる挙動が検知される可能性） |
| 柔軟性 | 高（バッチ投票・条件分岐自在） |
| 依存 | requests, BeautifulSoup のみ |

**teleboat_agent 相当を Python で再実装する案**。技術的には可能だが、
UA・Cookie・JS チャレンジを模倣しきれないとログイン段階で弾かれる。

### 方式B: Selenium / Playwright で Chrome を自動操作

```
predictions DB → auto_bet.py (Playwright) → 実 Chrome でテレボート操作
```

| 観点 | 評価 |
|------|------|
| 実装コスト | 中（操作手順の DOM セレクタ管理が必要） |
| 安定性 | 中（UI 変更時は selector を調整） |
| 凍結リスク | **低〜中**（実ブラウザ挙動なので検知されにくい） |
| 柔軟性 | 中（画面操作ベースなので多少遅い） |
| 依存 | playwright / selenium |

KyoteiVBA と同じアプローチの Python 版。**実運用実績があり
BOAT RACE 側から拒絶されていないという点で最もリスクが低い**。

### 方式C: Claude Code Agent（Playwright MCP）による自動操作

```
predictions DB → Claude Code が candidate を読む → Playwright MCP で実ブラウザ操作
```

| 観点 | 評価 |
|------|------|
| 実装コスト | 低（既存 MCP + プロンプトで実現） |
| 安定性 | **低**（LLM の判断ブレで誤投票リスクあり） |
| 凍結リスク | 中（実ブラウザ操作なので挙動自体は自然） |
| 柔軟性 | 極高（例外処理もプロンプトで書ける） |
| コスト | **高**（毎回 LLM 呼び出し、月 2,600 件で API コストが嵩む） |
| 決定論性 | **低**（同じ入力でも出力が揺れる、金銭取引で致命的）|

**非推奨**: 金銭が直接動くフローで LLM の非決定性は致命的。
`5R の 1-3-5 を 100 円` を `5R の 1-3-2 を 1000 円` に誤って解釈する
可能性がゼロでない以上、本番では使えない。

### 方式D: Claude Code Agent が方式Bの投票スクリプトを呼び出すだけ

```
predictions DB → Claude Code が候補を整形 → 決定論的な auto_bet.py を subprocess 実行
```

| 観点 | 評価 |
|------|------|
| 実装コスト | 低 |
| 安定性 | 高（実投票ロジックは決定論的） |
| 凍結リスク | 方式Bと同じ |
| 柔軟性 | 中 |

LLM は「候補抽出 → スクリプト呼び出し」までに限定し、
**実際のフォーム入力・送信は方式Bの Python スクリプトが担う**。
LLM は意思決定の監督者として使うだけ。これは現実的。

### 方式E: TELEBOAT API (team-nave) を購入する

| 観点 | 評価 |
|------|------|
| 実装コスト | 最低 |
| 安定性 | 最高（API 提供元がメンテ） |
| 凍結リスク | **最低**（公式連携に近い扱い） |
| コスト | 3,300 円/月（S6-3 実績の月 ROI ~800% 中では誤差） |
| 依存 | 外部 SaaS 継続提供 |

**コスト対効果では最良の選択**。ただし個人可否・SDK 言語・
API 仕様の詳細が Web 上では不透明のため、問い合わせが必要。

---

## 4. 推奨構成（段階導入）

### Phase 0: 半自動運用（即時開始可、今日から実施可能）

- [NOTIFICATION_PLAN.md](NOTIFICATION_PLAN.md) の Discord 通知を完成させる
- 通知を見てユーザーが**手動で**テレボート投票（現状の運用）
- **目的**: 現在の予測精度・運用想定の最終確認、誤ベット時の被害をゼロに

### Phase 1: 方式B ベースの自動投票スクリプト（2〜3 日）

ファイル構成:

```
ml/src/auto_bet/
  __init__.py
  teleboat_client.py      # Playwright で Chrome 操作
  bet_executor.py         # predictions → 投票リスト → クライアント呼出
  safety_guard.py         # 凍結回避ルール（後述）
  audit_log.py            # 全投票を JSON ログに書き出し
ml/src/scripts/
  run_auto_bet.py         # CLI エントリポイント
.env                      # TELEBOAT_USER_ID, TELEBOAT_PASSWORD, etc. (gitignore)
```

**投票フロー**:

1. `predictions` から `alert_flag=true AND race_date=today AND status='active'` を取得
2. 発走 **10 分前以降** の候補のみ対象（オッズ締切直前の最新 EV）
3. `safety_guard` で凍結回避チェック（後述）
4. `teleboat_client` が **ヘッドフルな Chrome** でログイン → 投票
5. 成功/失敗を `bets` テーブル（新規）と `audit_log` JSON に記録
6. Discord 通知に「実投票完了: 5R 1-3-5 100 円」を追記

**新規テーブル案**:

```sql
CREATE TABLE bets (
  id SERIAL PRIMARY KEY,
  race_id INTEGER REFERENCES races(id),
  combination VARCHAR(10),
  stake INTEGER,
  win_probability NUMERIC,
  expected_value NUMERIC,
  odds_at_bet NUMERIC,
  placed_at TIMESTAMP,
  teleboat_voucher_no VARCHAR(50),
  status VARCHAR(20),   -- pending / placed / failed / skipped
  error_reason TEXT
);
```

### Phase 2: 方式D（Claude Code 監督モード・任意）

- 日次 1 回、Claude Code Agent が `bets` テーブルと `race_results` を突合
- 異常（連敗・通常と乖離した ROI・投票漏れ）があれば Discord に警告
- 自動投票スクリプト自体は決定論的な Phase 1 実装をそのまま使う

### Phase 3: 方式E 切替の検討（3 ヶ月運用後）

- Phase 1 で運用実績が出た後に team-nave TELEBOAT API へ問い合わせ
- 凍結リスク排除と保守コスト削減を天秤にかけて判断

---

## 5. アカウント凍結回避ルール (`safety_guard`)

**最優先要件** として以下を実装:

### 5-1. リクエスト間隔
- 投票間隔: 最短 **8 秒**、ランダムジッター ±3 秒
- ログインは **1 日 3 回まで**（朝・昼・夜セッションで再利用）

### 5-2. 投票量制限
- **日次上限**: 200 件 / 日（S6-3 月平均の約 2.3 倍を上限）
- **時間帯集中回避**: 同一場の同一 R に複数点数を張る際も 1 点ずつ間隔を空ける

### 5-3. 人間らしい挙動
- ヘッドフル Chrome（headless=False）
- 本物の User Agent（Chrome の最新安定版）
- Cookie は永続化してログインセッションを使い回す
- 投票完了後に即ログアウトせず、1〜3 分ブラウザを開いたままにする

### 5-4. 異常時フェイルセーフ
- ログイン失敗 3 連続 → **自動停止**、Discord に緊急通知
- 残高不足エラー → 自動停止、Discord 通知
- テレボート UI 変更検知（想定セレクタ不在）→ 自動停止、Discord 通知
- 1 時間あたり投票失敗率 > 30% → 自動停止

### 5-5. ドライラン機能
- `--dry-run` で「ログイン・投票フォーム記入まで実行、送信直前で停止」
- 初回運用は必ず `--dry-run` + `--one-race` で 1 レースのみ実投票して検証

### 5-6. 自動解約回避
- 30 日間投票がない場合でも **週 1 回ログイン** + **残高確認**のみ実施
- `run_keepalive.py` として別スクリプト化

---

## 6. ClaudeCode / エージェントモードの役割分担

| タスク | 実行者 | 理由 |
|-------|-------|------|
| 予測・EV 計算 | 既存 `run_predict.py` | 決定論的・実装済み |
| 購入候補抽出 | 既存 `run_refresh_ev.py` + DB クエリ | 同上 |
| **投票実行** | **Phase 1 `run_auto_bet.py` (決定論スクリプト)** | 金銭取引に LLM 非決定性を持ち込まない |
| 結果モニタリング | Phase 2 Claude Code (日次) | 異常検知・パターン認識は LLM が得意 |
| 凍結兆候の早期発見 | Phase 2 Claude Code | ログパターン解析で有用 |
| UI 変更時のセレクタ調整 | 開発者 + Claude Code 支援 | テレボート UI 改修時に都度発生する作業 |

**重要方針**: Claude Code は「観察・補助・開発支援」、
実投票は「監査ログ付き決定論的スクリプト」で固定する。

---

## 7. リスクとその対策

| リスク | 深刻度 | 対策 |
|-------|-------|------|
| 誤投票（組番・金額） | 高 | dry-run 必須、`bets` テーブル + 監査ログ、金額 100 円固定で上限抑制 |
| 凍結 | 中 | §5 の safety_guard、予備アカウント不使用（規約違反） |
| テレボート UI 変更 | 中 | 1 箇所セレクタ集約、E2E 検知、Discord 即通知 |
| ネット・PC 障害で投票漏れ | 低 | bets.status=pending で記録、再起動時にリトライ（発走前のみ）|
| 法改正・規約改定 | 低〜中 | Phase 3 で API 切替を選択肢として維持、半期ごとに規約再確認 |
| モデル精度劣化による損失 | 中 | CLAUDE.md の月次モニタリング基準（ROI<300% で一時停止）を厳守 |
| 通信キャプチャによる投票内容漏洩 | 低 | HTTPS のみ、認証情報は `.env`・OS キーチェーン経由 |

---

## 8. 開発ロードマップ

| Phase | 期間目安 | 成果物 |
|-------|---------|--------|
| Phase 0 | 即時 | Discord 通知の本稼働（NOTIFICATION_PLAN 実施） |
| Phase 1a | Week 1 | `teleboat_client.py` でログイン・残高確認まで実装（投票なし）|
| Phase 1b | Week 2 | 投票フォーム自動入力（dry-run のみ）|
| Phase 1c | Week 3 | 実投票 1 レース手動実行で検証 |
| Phase 1d | Week 4 | `run_auto_bet.py` を cron 化、safety_guard 完備 |
| Phase 2 | Month 2 | Claude Code による日次モニタリング導入 |
| Phase 3 | Month 3+ | team-nave API 見積り・切替判断 |

---

## 9. 判断が必要なポイント

1. **投票スケールの上限**: 現在の月 2,600 件を自動化すると投資額 26 万円/月。
   これを一気に自動化するか、まず日 10 件等で絞って試すか。
2. **Phase 0 をどれだけ長くやるか**: Discord 通知で 1 ヶ月運用し、
   ユーザー自身の投票精度・ルール遵守感覚を検証するのが安全。
3. **24h 常時稼働 PC**: 自宅デスクトップ or クラウド Windows VM。
   後者だと月 3,000〜5,000 円の追加コスト。S6-3 ROI から見れば誤差。
4. **予備のアカウント作成**: **やらない**。複数アカウントは明確な規約違反で凍結リスク激増。
5. **TELEBOAT API（team-nave）への問い合わせ**: Phase 1 着手前に
   事前に問い合わせて個人利用可否を確認しておけば Phase 3 の判断が早くなる。

---

## 10. 次アクション（ユーザー判断待ち）

- [ ] Phase 0（NOTIFICATION_PLAN.md の Discord 通知）を先に完走させるか確認
- [ ] Phase 1 着手可否の判断（投票スケール含む）
- [ ] team-nave TELEBOAT API への問い合わせを並行して行うか
- [ ] 常時稼働環境（自宅 PC / クラウド VM）の選定

---

## 付録: 参考リンク

- [BOAT RACE サイトポリシー](https://www.boatrace.jp/owpc/pc/extra/policy.html)
- [team-nave TELEBOAT API](https://www.team-nave.com/system/jp/products/brapi/)
- [teleboat_agent (GitHub)](https://github.com/k0kishima/teleboat_agent)
- [KyoteiVBA](https://vba-create.jp/kyoteivba/)
- [舟券自動購入プログラム訴訟解説（知財弁護士.COM）](https://www.ip-bengoshi.com/archives/5279)
- [自動解約について (BOAT RACE 公式)](https://www.boatrace.jp/owpc/pc/extra/tb/support/information/t_autocancel.html)
