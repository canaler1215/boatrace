import { pgTable, varchar, serial, integer, real, boolean, timestamp, text, index, unique } from "drizzle-orm/pg-core";

// 競艇場マスタ
export const stadiums = pgTable("stadiums", {
  id: integer("id").primaryKey(),
  name: varchar("name", { length: 50 }).notNull(),
  location: varchar("location", { length: 50 }),
  waterType: varchar("water_type", { length: 20 }), // 淡水・海水
  inWinRate: real("in_win_rate"), // 1コース勝率
});

// 選手マスタ
export const racers = pgTable("racers", {
  id: integer("id").primaryKey(),
  name: varchar("name", { length: 50 }).notNull(),
  grade: varchar("grade", { length: 4 }), // A1/A2/B1/B2
  winRate: real("win_rate"),
  weight: real("weight"),
  updatedAt: timestamp("updated_at").defaultNow(),
});

// レース情報
export const races = pgTable("races", {
  id: varchar("id", { length: 20 }).primaryKey(), // {stadium_id}{yyyymmdd}{race_no}
  stadiumId: integer("stadium_id").references(() => stadiums.id),
  raceDate: varchar("race_date", { length: 10 }).notNull(), // YYYY-MM-DD
  raceNo: integer("race_no").notNull(),
  grade: varchar("grade", { length: 20 }),
  status: varchar("status", { length: 20 }).default("scheduled"), // scheduled/running/finished
  createdAt: timestamp("created_at").defaultNow(),
  updatedAt: timestamp("updated_at").defaultNow(),
}, (t) => [
  index().on(t.raceDate),
  index().on(t.stadiumId),
]);

// 出走表
export const raceEntries = pgTable("race_entries", {
  id: serial("id").primaryKey(),
  raceId: varchar("race_id", { length: 20 }).references(() => races.id),
  boatNo: integer("boat_no").notNull(), // 1〜6
  racerId: integer("racer_id").references(() => racers.id),
  motorWinRate: real("motor_win_rate"),
  boatWinRate: real("boat_win_rate"),
  exhibitionTime: real("exhibition_time"),
  startTiming: real("start_timing"), // ST
  finishPosition: integer("finish_position"), // 着順（レース後）
}, (t) => [
  index().on(t.raceId),
]);

// 3連単オッズ
export const odds = pgTable("odds", {
  id: serial("id").primaryKey(),
  raceId: varchar("race_id", { length: 20 }).references(() => races.id),
  combination: varchar("combination", { length: 10 }).notNull(), // 例: "1-2-3"
  oddsValue: real("odds_value").notNull(),
  snapshotAt: timestamp("snapshot_at").defaultNow(),
}, (t) => [
  index().on(t.raceId),
]);

// 潮位データ
export const tidalData = pgTable("tidal_data", {
  id: serial("id").primaryKey(),
  stadiumId: integer("stadium_id").references(() => stadiums.id),
  recordedAt: timestamp("recorded_at").notNull(),
  tidalLevel: real("tidal_level"),
  tidalType: varchar("tidal_type", { length: 10 }), // 満潮・干潮
});

// ML予測結果
export const predictions = pgTable("predictions", {
  id: serial("id").primaryKey(),
  raceId: varchar("race_id", { length: 20 }).references(() => races.id),
  combination: varchar("combination", { length: 10 }).notNull(),
  winProbability: real("win_probability").notNull(),
  expectedValue: real("expected_value").notNull(),
  alertFlag: boolean("alert_flag").default(false), // EV >= 1.2
  modelVersionId: integer("model_version_id"),
  predictedAt: timestamp("predicted_at").defaultNow(),
}, (t) => [
  index().on(t.raceId),
  index().on(t.alertFlag),
  unique().on(t.raceId, t.combination),
]);

// 購入記録（手動入力）
export const bets = pgTable("bets", {
  id: serial("id").primaryKey(),
  raceId: varchar("race_id", { length: 20 }).references(() => races.id),
  combination: varchar("combination", { length: 10 }).notNull(),
  amount: integer("amount").notNull(), // 購入金額（円）
  oddsAtBet: real("odds_at_bet"),
  isWin: boolean("is_win"),
  payout: integer("payout").default(0),
  note: text("note"),
  bettedAt: timestamp("betted_at").defaultNow(),
});

// MLモデルバージョン管理
export const modelVersions = pgTable("model_versions", {
  id: serial("id").primaryKey(),
  version: varchar("version", { length: 50 }).notNull(),
  releaseUrl: text("release_url"), // GitHub Releases URL
  trainedAt: timestamp("trained_at").notNull(),
  dataRangeFrom: varchar("data_range_from", { length: 10 }),
  dataRangeTo: varchar("data_range_to", { length: 10 }),
  rpsScore: real("rps_score"),
  isActive: boolean("is_active").default(false),
  createdAt: timestamp("created_at").defaultNow(),
});
