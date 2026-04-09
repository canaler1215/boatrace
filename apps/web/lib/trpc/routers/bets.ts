import { z } from "zod";
import { createTRPCRouter, publicProcedure } from "../server";
import { db, bets } from "@/lib/db";
import { desc, eq } from "drizzle-orm";

export const betsRouter = createTRPCRouter({
  list: publicProcedure.query(async () => {
    return db.select().from(bets).orderBy(desc(bets.bettedAt)).limit(100);
  }),

  create: publicProcedure
    .input(
      z.object({
        raceId: z.string(),
        combination: z.string(),
        amount: z.number().int().positive(),
        oddsAtBet: z.number().optional(),
        note: z.string().optional(),
      })
    )
    .mutation(async ({ input }) => {
      const result = await db.insert(bets).values(input).returning();
      return result[0];
    }),

  updateResult: publicProcedure
    .input(
      z.object({
        id: z.number(),
        isWin: z.boolean(),
        payout: z.number().int().min(0),
      })
    )
    .mutation(async ({ input }) => {
      const { id, ...data } = input;
      const result = await db
        .update(bets)
        .set(data)
        .where(eq(bets.id, id))
        .returning();
      return result[0];
    }),
});
