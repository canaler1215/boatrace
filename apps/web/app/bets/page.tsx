import { db, bets, races, stadiums } from "@/lib/db";
import { eq, desc } from "drizzle-orm";
import { createBet } from "./actions";
import BetResultForm from "./BetResultForm";

export const dynamic = "force-dynamic";

export default async function BetsPage() {
  const betList = await db
    .select({
      bet: bets,
      raceDate: races.raceDate,
      raceNo: races.raceNo,
      stadiumName: stadiums.name,
    })
    .from(bets)
    .leftJoin(races, eq(bets.raceId, races.id))
    .leftJoin(stadiums, eq(races.stadiumId, stadiums.id))
    .orderBy(desc(bets.bettedAt))
    .limit(100);

  const totalAmount = betList.reduce((s, b) => s + b.bet.amount, 0);
  const totalPayout = betList.reduce((s, b) => s + (b.bet.payout ?? 0), 0);
  const roi = totalAmount > 0 ? (totalPayout / totalAmount) * 100 : 0;

  return (
    <div>
      <h2 className="mb-6 text-2xl font-bold">購入記録</h2>

      {/* Summary strip */}
      <div className="mb-6 grid grid-cols-3 gap-4">
        <StatCard
          title="総購入金額"
          value={`${totalAmount.toLocaleString()}円`}
        />
        <StatCard
          title="総払戻金額"
          value={`${totalPayout.toLocaleString()}円`}
        />
        <StatCard
          title="回収率"
          value={`${roi.toFixed(1)}%`}
          highlight={roi >= 100 ? "green" : roi > 0 ? "red" : undefined}
        />
      </div>

      {/* Add bet form */}
      <div className="mb-6 rounded-lg border border-gray-200 bg-white p-6">
        <h3 className="mb-4 text-base font-semibold">購入記録を追加</h3>
        <form
          action={createBet}
          className="grid grid-cols-2 gap-3 md:grid-cols-3"
        >
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-700">
              レースID <span className="text-gray-400">(例: 012024120901)</span>
            </label>
            <input
              name="raceId"
              required
              placeholder="012024120901"
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-400 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-700">
              組合せ <span className="text-gray-400">(例: 1-2-3)</span>
            </label>
            <input
              name="combination"
              required
              placeholder="1-2-3"
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-400 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-700">
              購入金額 (円)
            </label>
            <input
              name="amount"
              type="number"
              required
              min="100"
              step="100"
              placeholder="500"
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-400 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-700">
              購入時オッズ <span className="text-gray-400">(任意)</span>
            </label>
            <input
              name="oddsAtBet"
              type="number"
              step="0.1"
              min="1"
              placeholder="25.0"
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-400 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-700">
              メモ <span className="text-gray-400">(任意)</span>
            </label>
            <input
              name="note"
              placeholder="例: アラートで推奨"
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-400 focus:outline-none"
            />
          </div>
          <div className="flex items-end">
            <button
              type="submit"
              className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
            >
              追加
            </button>
          </div>
        </form>
      </div>

      {/* Bets list */}
      {betList.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 p-12 text-center">
          <p className="text-gray-500">購入記録がありません。</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs uppercase text-gray-600">
              <tr>
                <th className="px-4 py-3 text-left">日時</th>
                <th className="px-4 py-3 text-left">レース</th>
                <th className="px-4 py-3 text-left">組合せ</th>
                <th className="px-4 py-3 text-right">購入額</th>
                <th className="px-4 py-3 text-right">オッズ</th>
                <th className="px-4 py-3 text-center">結果</th>
                <th className="px-4 py-3 text-right">払戻</th>
                <th className="px-4 py-3 text-right">損益</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {betList.map(({ bet, raceDate, raceNo, stadiumName }) => {
                const profit = (bet.payout ?? 0) - bet.amount;
                return (
                  <tr
                    key={bet.id}
                    className={
                      bet.isWin === true
                        ? "bg-green-50"
                        : bet.isWin === false
                          ? "bg-red-50"
                          : ""
                    }
                  >
                    <td className="px-4 py-3 text-xs text-gray-500">
                      {bet.bettedAt
                        ? new Date(bet.bettedAt).toLocaleDateString("ja-JP")
                        : "-"}
                    </td>
                    <td className="px-4 py-3">
                      {stadiumName ?? bet.raceId}
                      {raceNo != null && (
                        <span className="ml-1 text-gray-500">{raceNo}R</span>
                      )}
                      {raceDate && (
                        <span className="ml-1 text-xs text-gray-400">
                          {raceDate}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded bg-blue-100 px-2 py-0.5 font-mono text-blue-800">
                        {bet.combination}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      {bet.amount.toLocaleString()}円
                    </td>
                    <td className="px-4 py-3 text-right">
                      {bet.oddsAtBet != null
                        ? `${bet.oddsAtBet.toFixed(1)}倍`
                        : "-"}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {bet.isWin === true ? (
                        <span className="rounded bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                          的中
                        </span>
                      ) : bet.isWin === false ? (
                        <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                          外れ
                        </span>
                      ) : (
                        <span className="text-gray-400">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {bet.payout != null && bet.payout > 0
                        ? `${bet.payout.toLocaleString()}円`
                        : "-"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {bet.isWin !== null ? (
                        <span
                          className={
                            profit >= 0 ? "text-green-600" : "text-red-600"
                          }
                        >
                          {profit >= 0 ? "+" : ""}
                          {profit.toLocaleString()}円
                        </span>
                      ) : (
                        <span className="text-gray-400">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {bet.isWin === null && (
                        <BetResultForm betId={bet.id} />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function StatCard({
  title,
  value,
  highlight,
}: {
  title: string;
  value: string;
  highlight?: "green" | "red";
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <p className="text-xs text-gray-500">{title}</p>
      <p
        className={`text-2xl font-bold ${
          highlight === "green"
            ? "text-green-600"
            : highlight === "red"
              ? "text-red-600"
              : ""
        }`}
      >
        {value}
      </p>
    </div>
  );
}
