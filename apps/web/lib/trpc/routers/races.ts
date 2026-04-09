import { z } from "zod";
import { createTRPCRouter, publicProcedure } from "../server";
import { db, races, stadiums } from "@/lib/db";
import { eq, desc } from "drizzle-orm";

export const racesRouter = createTRPCRouter({
  list: publicProcedure
    .input(z.object({ date: z.string().optional() }))
    .query(async ({ input }) => {
      const query = db.select().from(races).orderBy(desc(races.raceDate));
      if (input.date) {
        return db.select().from(races).where(eq(races.raceDate, input.date));
      }
      return query.limit(50);
    }),

  byId: publicProcedure
    .input(z.object({ id: z.string() }))
    .query(async ({ input }) => {
      const result = await db.select().from(races).where(eq(races.id, input.id));
      return result[0] ?? null;
    }),
});
