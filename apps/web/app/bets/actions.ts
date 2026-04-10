"use server";
import { db, bets } from "@/lib/db";
import { revalidatePath } from "next/cache";
import { eq } from "drizzle-orm";

export async function createBet(formData: FormData) {
  const raceId = formData.get("raceId") as string;
  const combination = formData.get("combination") as string;
  const amountRaw = formData.get("amount") as string;
  const oddsAtBetRaw = formData.get("oddsAtBet") as string;
  const note = (formData.get("note") as string) || undefined;

  const amount = parseInt(amountRaw, 10);
  if (!raceId || !combination || isNaN(amount) || amount <= 0) return;

  const oddsAtBet = oddsAtBetRaw ? parseFloat(oddsAtBetRaw) : undefined;

  await db.insert(bets).values({ raceId, combination, amount, oddsAtBet, note });
  revalidatePath("/bets");
}

export async function updateBetResult(
  id: number,
  isWin: boolean,
  payout: number
) {
  await db
    .update(bets)
    .set({ isWin, payout: isWin ? payout : 0 })
    .where(eq(bets.id, id));
  revalidatePath("/bets");
}
