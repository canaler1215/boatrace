import { db, bets } from "@/lib/db";
import { sql } from "drizzle-orm";

export const dynamic = "force-dynamic";

export default async function AnalyticsPage() {
  const [summary] = await db
    .select({
      totalBets: sql<number>`count(*)`,
      totalAmount: sql<number>`coalesce(sum(${bets.amount}), 0)`,
      totalPayout: sql<number>`coalesce(sum(${bets.payout}), 0)`,
      wins: sql<number>`count(*) filter (where ${bets.isWin} = true)`,
      decided: sql<number>`count(*) filter (where ${bets.isWin} is not null)`,
    })
    .from(bets);

  const totalAmount = Number(summary?.totalAmount ?? 0);
  const totalPayout = Number(summary?.totalPayout ?? 0);
  const totalBets = Number(summary?.totalBets ?? 0);
  const wins = Number(summary?.wins ?? 0);
  const decided = Number(summary?.decided ?? 0);

  const roi = totalAmount > 0 ? totalPayout / totalAmount : 0;
  const winRate = decided > 0 ? wins / decided : 0;
  const profit = totalPayout - totalAmount;

  // Monthly breakdown (latest 12 months)
  const monthly = await db
    .select({
      month: sql<string>`to_char(${bets.bettedAt}, 'YYYY-MM')`,
      count: sql<number>`count(*)`,
      amount: sql<number>`coalesce(sum(${bets.amount}), 0)`,
      payout: sql<number>`coalesce(sum(${bets.payout}), 0)`,
      wins: sql<number>`count(*) filter (where ${bets.isWin} = true)`,
    })
    .from(bets)
    .groupBy(sql`to_char(${bets.bettedAt}, 'YYYY-MM')`)
    .orderBy(sql`to_char(${bets.bettedAt}, 'YYYY-MM') desc`)
    .limit(12);

  return (
    <div>
      <h2 className="mb-6 text-2xl font-bold">収支分析</h2>

      {/* Summary cards */}
      <div className="mb-8 grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard title="総購入件数" value={`${totalBets}件`} />
        <StatCard
          title="総購入金額"
          value={`${totalAmount.toLocaleString()}円`}
        />
        <StatCard
          title="総払戻金額"
          value={`${totalPayout.toLocaleString()}円`}
        />
        <StatCard
          title="損益"
          value={`${profit >= 0 ? "+" : ""}${profit.toLocaleString()}円`}
          highlight={profit >= 0 ? "green" : "red"}
        />
      </div>

      {/* ROI + Win rate */}
      <div className="mb-8 grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* ROI */}
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="mb-1 text-base font-semibold">回収率</h3>
          <p
            className={`mb-3 text-3xl font-bold ${roi >= 1 ? "text-green-600" : "text-red-600"}`}
          >
            {totalAmount > 0 ? `${(roi * 100).toFixed(1)}%` : "-"}
          </p>
          <div className="h-3 overflow-hidden rounded-full bg-gray-200">
            <div
              className={`h-3 rounded-full transition-all ${roi >= 1 ? "bg-green-500" : "bg-red-500"}`}
              style={{ width: `${Math.min(roi * 100, 200) / 2}%` }}
            />
          </div>
          <p className="mt-1 text-xs text-gray-400">
            基準ライン: 100%（損益ゼロ）
          </p>
        </div>

        {/* Win rate */}
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="mb-1 text-base font-semibold">的中率</h3>
          <p className="mb-3 text-3xl font-bold text-blue-600">
            {decided > 0 ? `${(winRate * 100).toFixed(1)}%` : "-"}
          </p>
          <div className="h-3 overflow-hidden rounded-full bg-gray-200">
            <div
              className="h-3 rounded-full bg-blue-500 transition-all"
              style={{ width: `${(winRate * 100).toFixed(1)}%` }}
            />
          </div>
          <p className="mt-1 text-xs text-gray-400">
            {wins}件 的中 / {decided}件 判定済 / {totalBets}件 合計
          </p>
        </div>
      </div>

      {/* Monthly breakdown */}
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h3 className="mb-4 text-base font-semibold">月別収支</h3>
        {monthly.length === 0 ? (
          <p className="text-sm text-gray-500">データがありません。</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b border-gray-200 text-xs uppercase text-gray-600">
              <tr>
                <th className="pb-2 text-left">月</th>
                <th className="pb-2 text-right">件数</th>
                <th className="pb-2 text-right">購入金額</th>
                <th className="pb-2 text-right">払戻金額</th>
                <th className="pb-2 text-right">損益</th>
                <th className="pb-2 text-right">回収率</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {monthly.map((row) => {
                const amt = Number(row.amount);
                const pay = Number(row.payout);
                const prof = pay - amt;
                const r = amt > 0 ? (pay / amt) * 100 : 0;
                return (
                  <tr key={row.month}>
                    <td className="py-2 font-medium">{row.month}</td>
                    <td className="py-2 text-right">{Number(row.count)}件</td>
                    <td className="py-2 text-right">
                      {amt.toLocaleString()}円
                    </td>
                    <td className="py-2 text-right">
                      {pay.toLocaleString()}円
                    </td>
                    <td
                      className={`py-2 text-right font-medium ${prof >= 0 ? "text-green-600" : "text-red-600"}`}
                    >
                      {prof >= 0 ? "+" : ""}
                      {prof.toLocaleString()}円
                    </td>
                    <td
                      className={`py-2 text-right ${r >= 100 ? "text-green-600" : "text-red-600"}`}
                    >
                      {r.toFixed(1)}%
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
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
