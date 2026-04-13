CREATE TABLE "racer_st_stats" (
	"racer_id" integer PRIMARY KEY NOT NULL,
	"avg_st" real NOT NULL,
	"sample_count" integer NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
