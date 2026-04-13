import { db, predictions, races, stadiums } from "@/lib/db";
import { eq, desc, and, gte } from "drizzle-orm";
import { calcKellyFraction } from "@/lib/utils/ev";
import Link from "next/link";
import { ProbThresholdControl } from "./ProbThresholdControl";

export const dynamic = "force-dynamic";

const DEFAULT_PROB_PCT = 5;

interface Props {
  searchParams: Promise<{ prob?: string }>;
}

export default async function DashboardPage({ searchParams }: Props) {
  const { prob } = await searchParams;
  const probPct = Math.max(
    DEFAULT_PROB_PCT,
    Math.min(50, parseFloat(prob ?? String(DEFAULT_PROB_PCT)) || DEFAULT_PROB_PCT)
  );
  const probThreshold = probPct / 100;

  const today = new Date().toISOString().slice(0, 10);

  const alerts = await db
    .select({
      id: predictions.id,
      raceId: predictions.raceId,
      combination: predictions.combination,
      winProbability: predictions.winProbability,
      expectedValue: predictions.expectedValue,
      raceNo: races.raceNo,
      grade: races.grade,
      stadiumName: stadiums.name,
    })
    .from(predictions)
    .innerJoin(races, eq(predictions.raceId, races.id))
    .leftJoin(stadiums, eq(races.stadiumId, stadiums.id))
    .where(
      and(
        eq(races.raceDate, today),
        gte(predictions.winProbability, probThreshold)
      )
    )
    .orderBy(desc(predictions.winProbability));

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-2xl font-bold">本日のレース予測</h2>
        <div className="flex items-center gap-4">
          <ProbThresholdControl current={probPct} />
          <span className="text-sm text-gray-500">{today}</span>
        </div>
      </div>

      {alerts.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 p-12 text-center">
          <p className="text-gray-500">
            本日は的中確率 {probPct}% 以上の舟券はありません。
          </p>
          <p className="mt-2 text-sm text-gray-400">
            GitHub Actions (predict.yml) が毎時00分に更新します。
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs uppercase text-gray-600">
              <tr>
                <th className="px-4 py-3 text-left">競艇場</th>
                <th className="px-4 py-3 text-left">レース</th>
                <th className="px-4 py-3 text-left">組合せ</th>
                <th className="px-4 py-3 text-right">的中確率</th>
                <th className="px-4 py-3 text-right">期待値</th>
                <th className="px-4 py-3 text-right">推奨ベット (1/4 Kelly)</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {alerts.map((alert) => {
                const odds =
                  alert.winProbability > 0
                    ? alert.expectedValue / alert.winProbability
                    : 0;
                const kelly = calcKellyFraction(alert.expectedValue, odds);
                return (
                  <tr key={alert.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium">
                      {alert.stadiumName ?? "-"}
                    </td>
                    <td className="px-4 py-3">
                      {alert.raceNo}R
                      {alert.grade && (
                        <span className="ml-1 text-xs text-gray-500">
                          {alert.grade}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded bg-blue-100 px-2 py-0.5 font-mono text-blue-800">
                        {alert.combination}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className="font-semibold text-blue-600">
                        {(alert.winProbability * 100).toFixed(1)}%
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-gray-700">
                      {alert.expectedValue.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-600">
                      {kelly > 0 ? `${(kelly * 100).toFixed(1)}%` : "-"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Link
                        href={`/races/${alert.raceId}`}
                        className="text-blue-600 hover:underline"
                      >
                        詳細 →
                      </Link>
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
