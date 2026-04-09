import "server-only";
import { initTRPC } from "@trpc/server";
import { cache } from "react";
import { ZodError } from "zod";

export const createTRPCContext = cache(async () => {
  return {};
});

const t = initTRPC.context<typeof createTRPCContext>().create({
  errorFormatter({ shape, error }) {
    return {
      ...shape,
      data: {
        ...shape.data,
        zodError:
          error.cause instanceof ZodError ? error.cause.flatten() : null,
      },
    };
  },
});

export const createTRPCRouter = t.router;
export const publicProcedure = t.procedure;
