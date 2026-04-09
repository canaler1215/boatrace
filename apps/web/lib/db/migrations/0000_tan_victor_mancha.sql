CREATE TABLE "bets" (
	"id" serial PRIMARY KEY NOT NULL,
	"race_id" varchar(20),
	"combination" varchar(10) NOT NULL,
	"amount" integer NOT NULL,
	"odds_at_bet" real,
	"is_win" boolean,
	"payout" integer DEFAULT 0,
	"note" text,
	"betted_at" timestamp DEFAULT now()
);
--> statement-breakpoint
CREATE TABLE "model_versions" (
	"id" serial PRIMARY KEY NOT NULL,
	"version" varchar(50) NOT NULL,
	"release_url" text,
	"trained_at" timestamp NOT NULL,
	"data_range_from" varchar(10),
	"data_range_to" varchar(10),
	"rps_score" real,
	"is_active" boolean DEFAULT false,
	"created_at" timestamp DEFAULT now()
);
--> statement-breakpoint
CREATE TABLE "odds" (
	"id" serial PRIMARY KEY NOT NULL,
	"race_id" varchar(20),
	"combination" varchar(10) NOT NULL,
	"odds_value" real NOT NULL,
	"snapshot_at" timestamp DEFAULT now()
);
--> statement-breakpoint
CREATE TABLE "predictions" (
	"id" serial PRIMARY KEY NOT NULL,
	"race_id" varchar(20),
	"combination" varchar(10) NOT NULL,
	"win_probability" real NOT NULL,
	"expected_value" real NOT NULL,
	"alert_flag" boolean DEFAULT false,
	"model_version_id" integer,
	"predicted_at" timestamp DEFAULT now()
);
--> statement-breakpoint
CREATE TABLE "race_entries" (
	"id" serial PRIMARY KEY NOT NULL,
	"race_id" varchar(20),
	"boat_no" integer NOT NULL,
	"racer_id" integer,
	"motor_win_rate" real,
	"boat_win_rate" real,
	"exhibition_time" real,
	"start_timing" real,
	"finish_position" integer
);
--> statement-breakpoint
CREATE TABLE "racers" (
	"id" integer PRIMARY KEY NOT NULL,
	"name" varchar(50) NOT NULL,
	"grade" varchar(4),
	"win_rate" real,
	"weight" real,
	"updated_at" timestamp DEFAULT now()
);
--> statement-breakpoint
CREATE TABLE "races" (
	"id" varchar(20) PRIMARY KEY NOT NULL,
	"stadium_id" integer,
	"race_date" varchar(10) NOT NULL,
	"race_no" integer NOT NULL,
	"grade" varchar(20),
	"status" varchar(20) DEFAULT 'scheduled',
	"created_at" timestamp DEFAULT now(),
	"updated_at" timestamp DEFAULT now()
);
--> statement-breakpoint
CREATE TABLE "stadiums" (
	"id" integer PRIMARY KEY NOT NULL,
	"name" varchar(50) NOT NULL,
	"location" varchar(50),
	"water_type" varchar(20),
	"in_win_rate" real
);
--> statement-breakpoint
CREATE TABLE "tidal_data" (
	"id" serial PRIMARY KEY NOT NULL,
	"stadium_id" integer,
	"recorded_at" timestamp NOT NULL,
	"tidal_level" real,
	"tidal_type" varchar(10)
);
--> statement-breakpoint
ALTER TABLE "bets" ADD CONSTRAINT "bets_race_id_races_id_fk" FOREIGN KEY ("race_id") REFERENCES "public"."races"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "odds" ADD CONSTRAINT "odds_race_id_races_id_fk" FOREIGN KEY ("race_id") REFERENCES "public"."races"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "predictions" ADD CONSTRAINT "predictions_race_id_races_id_fk" FOREIGN KEY ("race_id") REFERENCES "public"."races"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "race_entries" ADD CONSTRAINT "race_entries_race_id_races_id_fk" FOREIGN KEY ("race_id") REFERENCES "public"."races"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "race_entries" ADD CONSTRAINT "race_entries_racer_id_racers_id_fk" FOREIGN KEY ("racer_id") REFERENCES "public"."racers"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "races" ADD CONSTRAINT "races_stadium_id_stadiums_id_fk" FOREIGN KEY ("stadium_id") REFERENCES "public"."stadiums"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "tidal_data" ADD CONSTRAINT "tidal_data_stadium_id_stadiums_id_fk" FOREIGN KEY ("stadium_id") REFERENCES "public"."stadiums"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "odds_race_id_index" ON "odds" USING btree ("race_id");--> statement-breakpoint
CREATE INDEX "predictions_race_id_index" ON "predictions" USING btree ("race_id");--> statement-breakpoint
CREATE INDEX "predictions_alert_flag_index" ON "predictions" USING btree ("alert_flag");--> statement-breakpoint
CREATE INDEX "race_entries_race_id_index" ON "race_entries" USING btree ("race_id");--> statement-breakpoint
CREATE INDEX "races_race_date_index" ON "races" USING btree ("race_date");--> statement-breakpoint
CREATE INDEX "races_stadium_id_index" ON "races" USING btree ("stadium_id");