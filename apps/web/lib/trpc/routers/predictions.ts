import { z } from "zod";
import { createTRPCRouter, publicProcedure } from "../server";
import { db, predictions, races } from "@/lib/db";
import { eq, and, gte, desc } from "drizzle-orm";

export const predictionsRouter = createTRPCRouter({
  alerts: publicProcedure
    .input(
      z.object({
        date: z.string().optional(),
        probThreshold: z.number().min(0).max(1).default(0.05),
      })
    )
    .query(async ({ input }) => {
      const date = input.date ?? new Date().toISOString().slice(0, 10);
      return db
        .select()
        .from(predictions)
        .innerJoin(races, eq(predictions.raceId, races.id))
        .where(
          and(
            eq(races.raceDate, date),
            gte(predictions.winProbability, input.probThreshold)
          )
        )
        .orderBy(desc(predictions.winProbability))
        .limit(100);
    }),

  byRace: publicProcedure
    .input(z.object({ raceId: z.string() }))
    .query(async ({ input }) => {
      return db
        .select()
        .from(predictions)
        .where(eq(predictions.raceId, input.raceId));
    }),
});
