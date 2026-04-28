> # 🛑 凍結済み (2026-04-28、Q-B 合意 / (P-v) ハイブリッド採用)
>
> 本ファイルは凍結時点の参照記録として保持されている。**新規着手は不可**。
>
> 全 6 系統 (B-1 / B-3 win / 拡張 A / P-v condition / P4-α LLM / Model-loop) で採用基準未達。
> 後続作業は無し。詳細は [CLAUDE.md](CLAUDE.md)「現行の運用方針」冒頭参照。
>
> 手動でレース予想したくなった時は CLAUDE.md「手動レース予想の手順 (P-v 凍結後)」へ。

---

# 次セッション用プロンプト C_R1 — 連系券種（2 連単 / 2 連複 / 拡連複）DL 関数の実装（B-1/B-3 win/拡張 A 全撤退後の更新版）

> 🛑 **凍結確定（2026-04-28、Q-A 合意）**: 本プロンプトは **新規着手不可**。
> 拡張 A 撤退（2026-04-28）の直後に P-v race condition × odds 軸の事前検証を追加実施し、
> その結果も flagged = 0 / 16 valid segments で「歪み < 控除率」の構造的結論が確定。
> 連系券種の DL も着手しないことが Q-A で合意された。本ファイルは過去の検討記録としてのみ参照する。
> 詳細は [CLAUDE.md](CLAUDE.md) §「現行の運用方針」 / [MARKET_EFFICIENCY_RESULTS.md](MARKET_EFFICIENCY_RESULTS.md) §10 を参照。

以下を新セッションの最初のユーザープロンプトとして貼り付けてください。

> 旧 [NEXT_SESSION_PROMPT_C.md](NEXT_SESSION_PROMPT_C.md) は **拡張 A R3 撤退前** の前提で書かれていた。
> 本ファイルは拡張 A 撤退確定（2026-04-28）を踏まえた更新版。実装内容（着手前合意 1〜9 や DL 関数仕様）はほぼ
> 同じ内容を継承するが、**そもそも C を進めるか / 完全凍結するか** の判断を改めて入れてある。

---

## プロンプト本文

boatrace プロジェクトのフェーズ B-3 系列の最後のオプション「**連系券種 (2 連単 / 2 連複 / 拡連複) の市場効率分析**」について、まず**着手するか / 完全凍結するか**をユーザーと合意してから、進める場合は DL 関数を実装する。

### これまでの経緯（R3 拡張 A 撤退後の現状）

| フェーズ | 内容 | 結果 |
|---|---|---|
| 3 `/inner-loop` | 購入フィルタ探索 | 凍結 |
| 6 `/model-loop` | モデル構造改善 | 完全撤退 |
| 7 (B-1) | 3 連単市場効率（控除率 25%） | 完全撤退（最善 ev=0.98） |
| **B-3 win** | 単勝市場効率（控除率 20%） | 完全撤退（最善 ev=0.964） |
| **B-3 拡張 A 複勝** R1+R2+R3 | 複勝 top-2、控除率 20%、R2 補正後 ev | **撤退確定**（最善 ev_corr=0.93、CI=[0.80, 1.07]）|
| **B-3 拡張 C**（本タスク）| 連系券種 DL + 集計 | **着手判断待ち** |

### 構造的に判明した結論（重要）

3 券種（trifecta / win / place）すべてで「控除率を縮める弱い歪み（lift 1.0 付近）はあるが
収支プラス化（ev > 1.0）までは至らない」**同じ構造**を確認した:

| 券種 | 控除率 | 組合せ数 | 最善セグメント ev |
|---|---:|---:|---:|
| trifecta | 25% | 120 | 0.98 |
| win | 20% | 6 | 0.964 |
| **place (top-2)** | **20%** | **6** | **0.93** (R2 補正後) |

**控除率の低さや組合せ数の多寡では決着がつかない**。市場参加者の総体的な予測精度が高く、
歪みは控除率を破る規模に達しない。

### 着手判断の合意ポイント（**最初に決める**）

**Q1**: 連系券種 (2 連単 30 / 2 連複 15 / 拡連複 15) の DL を進めるか？

| 選択肢 | 説明 | 推奨理由 |
|---|---|---|
| **(a) 完全凍結** | 全フェーズ撤退状態継続、`run_market_efficiency.py` の改善ループ停止 | trifecta / win / place で同じ構造的結論。連系券種で異なる結論が出る根拠は薄い。**デフォルト推奨** |
| **(b) 連系券種 DL 着手** | 旧 [NEXT_SESSION_PROMPT_C.md](NEXT_SESSION_PROMPT_C.md) の着手前合意 1〜9 に従い実装 | 「組合せ数が中間 (15〜30) なのでサンプル分厚さで小さな歪みを発見できる可能性は残る」という弱い仮説のみ。実装 2〜3h + DL 12〜36h × 3 種 |
| **(c) 連系券種は DL 関数だけ整える（本番 DL は保留）** | 旧 C プロンプトの「DL 関数のみ実装、試行 DL は別途」の路線 | 将来の選択肢を残しつつ実装コスト最小化。**(a) 凍結との中間案** |

**推奨**: **(a) 完全凍結**。3 券種で同じ「歪みが控除率を破らない」結論が出ているため、
連系券種で異なる結果を得る根拠は薄い。新軸（B-2 動的オッズ等）を別途検討するほうが
期待値が高い可能性。

ただしユーザーが (b) または (c) を選んだ場合は、旧 [NEXT_SESSION_PROMPT_C.md](NEXT_SESSION_PROMPT_C.md)
の着手前合意 1〜9 をそのまま適用して進める（差分は試行 DL 着手のタイミングのみ、単勝・複勝
本番 DL の完了確認はすでに済んでいる前提）。

### (b) を選んだ場合の補足（実装スコープ）

旧 [NEXT_SESSION_PROMPT_C.md](NEXT_SESSION_PROMPT_C.md) §着手前合意ポイント 1〜9 をそのまま採用:

1. 3 券種一括実装（HTML 構造調査の重複回避）
2. `artifacts/` に 1 レース分 HTML 保存して観察
3. `odds2tf` ページに 2 連単 + 2 連複 同居を内部 helper で 1 度の取得に集約
4. combination キー: 2 連単 = 順序つき、2 連複 / 拡連複 = ソート済み艇番
5. 拡連複は `odds_low / odds_high` 別カラム（拡張 A complex 流儀踏襲）
6. 試行 DL は `place_odds_*.parquet` 12 件揃いを確認後（**現時点で完了済み**）
7. 試行 DL の月: 2025-12
8. 想定外の HTML 構造: 該当券種のみ撤退
9. コード差分: `openapi_client.py` + `odds_downloader.py` のみ、`run_market_efficiency.py` は触らない

加えて R3 から得た新ガイドライン:

- **採用基準は補正後 ev > 1.0 & CI 下限 > 1.0** で固定。後付けで緩めない（拡張 A R1 の `ev_all_buy_mid > 1.05` 補助基準は楽観的すぎたため R3 で廃止した経緯がある）
- 拡連複は range odds なので、複勝と同じく **R2 相当の実 payout sample** が必要になる可能性あり（`pos_in_range` 補正係数を券種ごとに sample 取得する想定で計画する）
- **集計時は実 ROI ベース必須**（B-3 win 教訓: `mean(odds × hit) = mean(odds) × mean(hit)` には `Cov(odds, hit) < 0` 由来の上方バイアスがある）

### (c) を選んだ場合の補足

DL 関数 + 試行 DL（2025-12 単月）まで実施。本番 DL（12 ヶ月 × 3 種 = 約 36 時間）と Step 2 集計は
別セッションへ後送り。

### (a) を選んだ場合の補足

- `CLAUDE.md` 現行運用方針を「全フェーズ撤退状態 + 連系券種も着手しないことを確定」に更新
- `AUTO_LOOP_PLAN.md` フェーズ 8 を「凍結確定」に更新
- 関連プロンプト（[NEXT_SESSION_PROMPT_C.md](NEXT_SESSION_PROMPT_C.md) / [NEXT_SESSION_PROMPT_C_R1.md](NEXT_SESSION_PROMPT_C_R1.md)）を「凍結時の参照のみ、新規着手は不可」とマーク
- 別軸（B-2 動的オッズ、`/predict` LLM 予想の再評価、完全休止）の検討に移る

### 着手前読書

- [MARKET_EFFICIENCY_PLACE_RESULTS.md](MARKET_EFFICIENCY_PLACE_RESULTS.md) §13-§14 — **拡張 A R3 撤退結果（必読）**
- [MARKET_EFFICIENCY_WIN_RESULTS.md](MARKET_EFFICIENCY_WIN_RESULTS.md) §6-§7 — B-3 win 撤退結果
- [MARKET_EFFICIENCY_RESULTS.md](MARKET_EFFICIENCY_RESULTS.md) — B-1 trifecta 撤退結果
- [NEXT_SESSION_PROMPT_C.md](NEXT_SESSION_PROMPT_C.md) — (b)(c) 選択時のベース実装計画
- [CLAUDE.md](CLAUDE.md) — 「現行の運用方針」「現在の仕様」
- [BET_RULE_REVIEW_202509_202512.md](BET_RULE_REVIEW_202509_202512.md) §28-32 — 実運用再開条件（通算 ROI ≥ +10% & 最悪月 > -50%）

### 厳守事項（全選択肢共通）

- ❌ 既存モデル（trainer.py / predictor.py / engine.py）は触らない
- ❌ predict.md / predict_llm/ / evaluate_predictions.py / eval_summary.py 書き換え禁止
- ❌ 既存 `data/odds/*.parquet`（odds / trio_odds / win_odds / place_odds）を上書きしない
- ❌ Q1 の合意なしに DL 関数実装に着手しない
- ❌ (b)(c) を選ぶ場合も、後付けで採用基準を緩める変更禁止（フェーズ 3〜6 + B-1 + B-3 win + 拡張 A の教訓）

### 実行環境

- Python 3.12（`py -3.12`）
- ローカル（Windows）、DB 接続不要
- 想定実行時間:
  - (a) 完全凍結: ドキュメント更新 30 分
  - (b) 連系券種フル実装: HTML 調査 1h + 実装 2〜3h + 試行 DL 4h + 12 ヶ月本番 DL 36h + 集計実装 3h + 集計 1〜2 分 + レポート 30 分（合計 1〜2 セッション）
  - (c) DL 関数のみ実装 + 試行 DL: HTML 調査 1h + 実装 2〜3h + 試行 DL 4h + ドキュメント 30 分

以上。**Q1 の合意（(a) / (b) / (c)）が出てから着手内容を決めてほしい**。
