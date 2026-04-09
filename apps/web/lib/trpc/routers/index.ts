import { createTRPCRouter } from "../server";
import { racesRouter } from "./races";
import { predictionsRouter } from "./predictions";
import { betsRouter } from "./bets";
import { analyticsRouter } from "./analytics";

export const appRouter = createTRPCRouter({
  races: racesRouter,
  predictions: predictionsRouter,
  bets: betsRouter,
  analytics: analyticsRouter,
});

export type AppRouter = typeof appRouter;
