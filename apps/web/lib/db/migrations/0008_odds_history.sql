-- C-1: オッズ履歴テーブル（ODDS_FRESHNESS_IMPROVEMENT.md）
-- 既存の odds テーブルは「最新値キャッシュ」として残し、
-- odds_history に INSERT ONLY で時系列データを蓄積する。
--
-- 用途:
--   - 「発走 30 分前 → 10 分前 → 1 分前」のオッズ推移分析
--   - バックテストで「発走 X 分前オッズ」を使う場合のデータソース
--   - E-1（オッズ変動の特徴量化）の前提データ
--
-- 容量試算: ~300 レース × 120 組 × 60 スナップショット/日 ≒ 2.16M 行/日。
-- 運用で最新 N 日に刈り込むか、EV ≥ 2.0 の組合せのみに絞る方針は追って検討する。
CREATE TABLE "odds_history" (
  "id"           bigserial PRIMARY KEY,
  "race_id"      varchar(20) NOT NULL,
  "combination"  varchar(10) NOT NULL,
  "odds_value"   real NOT NULL,
  "snapshot_at"  timestamp NOT NULL DEFAULT now()
);

--> statement-breakpoint
ALTER TABLE "odds_history" ADD CONSTRAINT "odds_history_race_id_races_id_fk"
  FOREIGN KEY ("race_id") REFERENCES "public"."races"("id") ON DELETE no action ON UPDATE no action;

--> statement-breakpoint
-- レース別の時系列検索（推移グラフ・特徴量生成）
CREATE INDEX "odds_history_race_id_snapshot_at_idx" ON "odds_history" ("race_id", "snapshot_at");

--> statement-breakpoint
-- 保持期間に基づく削除バッチ（`DELETE WHERE snapshot_at < now() - interval '30 day'`）向け
CREATE INDEX "odds_history_snapshot_at_idx" ON "odds_history" ("snapshot_at");
