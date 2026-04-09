import { createTRPCRouter, publicProcedure } from "../server";
import { db, bets } from "@/lib/db";
import { sql } from "drizzle-orm";

export const analyticsRouter = createTRPCRouter({
  summary: publicProcedure.query(async () => {
    const result = await db
      .select({
        totalBets: sql<number>`count(*)`,
        totalAmount: sql<number>`sum(${bets.amount})`,
        totalPayout: sql<number>`sum(${bets.payout})`,
        wins: sql<number>`count(*) filter (where ${bets.isWin} = true)`,
      })
      .from(bets);
    const row = result[0];
    const totalAmount = row.totalAmount ?? 0;
    const totalPayout = row.totalPayout ?? 0;
    return {
      totalBets: row.totalBets,
      totalAmount,
      totalPayout,
      roi: totalAmount > 0 ? totalPayout / totalAmount : 0,
      wins: row.wins,
    };
  }),
});
