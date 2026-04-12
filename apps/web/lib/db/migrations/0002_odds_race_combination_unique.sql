-- odds テーブルの重複行を除去してから UNIQUE 制約を追加する
-- 同一 (race_id, combination) のうち最新の snapshot_at を1行だけ残す
DELETE FROM odds
WHERE id NOT IN (
    SELECT DISTINCT ON (race_id, combination) id
    FROM odds
    ORDER BY race_id, combination, snapshot_at DESC
);

--> statement-breakpoint
ALTER TABLE "odds" ADD CONSTRAINT "odds_race_id_combination_unique" UNIQUE ("race_id", "combination");
