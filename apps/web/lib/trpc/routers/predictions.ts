import { z } from "zod";
import { createTRPCRouter, publicProcedure } from "../server";
import { db, predictions } from "@/lib/db";
import { eq, and } from "drizzle-orm";

export const predictionsRouter = createTRPCRouter({
  alerts: publicProcedure
    .input(z.object({ date: z.string().optional() }))
    .query(async () => {
      return db
        .select()
        .from(predictions)
        .where(eq(predictions.alertFlag, true))
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
