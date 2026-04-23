CREATE TABLE "race_results" (
	"race_id" varchar(20) PRIMARY KEY NOT NULL,
	"trifecta_combination" varchar(10) NOT NULL,
	"trifecta_payout" integer,
	"settled_at" timestamp DEFAULT now()
);
--> statement-breakpoint
ALTER TABLE "race_results" ADD CONSTRAINT "race_results_race_id_races_id_fk" FOREIGN KEY ("race_id") REFERENCES "public"."races"("id") ON DELETE no action ON UPDATE no action;
