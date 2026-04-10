import { db, predictions, races, raceEntries, racers, stadiums } from "@/lib/db";
import { eq, desc } from "drizzle-orm";
import { calcKellyFraction } from "@/lib/utils/ev";
import Link from "next/link";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ id: string }>;
}

const BOAT_COLORS: Record<number, string> = {
  1: "bg-white border border-gray-400 text-gray-900",
  2: "bg-black text-white",
  3: "bg-red-600 text-white",
  4: "bg-blue-600 text-white",
  5: "bg-yellow-400 text-gray-900",
  6: "bg-green-600 text-white",
};

export default async function RacePage({ params }: Props) {
  const { id } = await params;

  const raceRows = await db
    .select({ race: races, stadium: stadiums })
    .from(races)
    .leftJoin(stadiums, eq(races.stadiumId, stadiums.id))
    .where(eq(races.id, id));

  if (!raceRows[0]) notFound();

  const { race, stadium } = raceRows[0];

  const [predictionList, entries] = await Promise.all([
    db
      .select()
      .from(predictions)
      .where(eq(predictions.raceId, id))
      .orderBy(desc(predictions.expectedValue)),
    db
      .select({ entry: raceEntries, racer: racers })
      .from(raceEntries)
      .leftJoin(racers, eq(raceEntries.racerId, racers.id))
      .where(eq(raceEntries.raceId, id))
      .orderBy(raceEntries.boatNo),
  ]);

  return (
    <div>
      <div className="mb-2">
        <Link
          href="/dashboard"
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          ← ダッシュボードへ
        </Link>
      </div>

      <h2 className="mb-1 text-2xl font-bold">
        {stadium?.name ?? "競艇場"} {race.raceNo}R
      </h2>
      <p className="mb-6 flex gap-4 text-sm text-gray-500">
        <span>{race.raceDate}</span>
        <span>グレード: {race.grade ?? "-"}</span>
        <span>
          状態:{" "}
          <StatusBadge status={race.status ?? "scheduled"} />
        </span>
      </p>

      {/* Predictions table */}
      <section className="mb-8">
        <h3 className="mb-3 text-lg font-semibold">ML予測結果</h3>
        {predictionList.length === 0 ? (
          <p className="text-sm text-gray-500">予測データがありません。</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs uppercase text-gray-600">
                <tr>
                  <th className="px-4 py-3 text-left">組合せ</th>
                  <th className="px-4 py-3 text-right">的中確率</th>
                  <th className="px-4 py-3 text-right">オッズ (推定)</th>
                  <th className="px-4 py-3 text-right">期待値</th>
                  <th className="px-4 py-3 text-center">アラート</th>
                  <th className="px-4 py-3 text-right">推奨ベット (1/4 Kelly)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {predictionList.map((p) => {
                  const estimatedOdds =
                    p.winProbability > 0
                      ? p.expectedValue / p.winProbability
                      : 0;
                  const kelly = calcKellyFraction(
                    p.expectedValue,
                    estimatedOdds
                  );
                  return (
                    <tr
                      key={p.id}
                      className={p.alertFlag ? "bg-green-50" : ""}
                    >
                      <td className="px-4 py-3">
                        <span className="rounded bg-blue-100 px-2 py-0.5 font-mono text-blue-800">
                          {p.combination}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        {(p.winProbability * 100).toFixed(1)}%
                      </td>
                      <td className="px-4 py-3 text-right text-gray-600">
                        {estimatedOdds > 0
                          ? `${estimatedOdds.toFixed(1)}倍`
                          : "-"}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span
                          className={
                            p.alertFlag
                              ? "font-semibold text-green-600"
                              : "text-gray-700"
                          }
                        >
                          {p.expectedValue.toFixed(2)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center">
                        {p.alertFlag ? (
                          <span className="rounded bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                            アラート
                          </span>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-600">
                        {kelly > 0 ? `${(kelly * 100).toFixed(1)}%` : "-"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Race entries table */}
      <section>
        <h3 className="mb-3 text-lg font-semibold">出走表</h3>
        {entries.length === 0 ? (
          <p className="text-sm text-gray-500">出走データがありません。</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs uppercase text-gray-600">
                <tr>
                  <th className="px-4 py-3 text-left">艇番</th>
                  <th className="px-4 py-3 text-left">選手名</th>
                  <th className="px-4 py-3 text-center">級別</th>
                  <th className="px-4 py-3 text-right">選手勝率</th>
                  <th className="px-4 py-3 text-right">モーター2連率</th>
                  <th className="px-4 py-3 text-right">展示タイム</th>
                  <th className="px-4 py-3 text-right">ST</th>
                  <th className="px-4 py-3 text-right">着順</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {entries.map(({ entry, racer }) => (
                  <tr
                    key={entry.id}
                    className={entry.boatNo === 1 ? "bg-yellow-50" : ""}
                  >
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${BOAT_COLORS[entry.boatNo] ?? "bg-gray-400 text-white"}`}
                      >
                        {entry.boatNo}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-medium">
                      {racer?.name ?? "-"}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {racer?.grade ? (
                        <span
                          className={`rounded px-1.5 py-0.5 text-xs font-medium ${gradeClass(racer.grade)}`}
                        >
                          {racer.grade}
                        </span>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {racer?.winRate != null
                        ? racer.winRate.toFixed(2)
                        : "-"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {entry.motorWinRate != null
                        ? `${entry.motorWinRate.toFixed(1)}%`
                        : "-"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {entry.exhibitionTime != null
                        ? entry.exhibitionTime.toFixed(2)
                        : "-"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {entry.startTiming != null
                        ? entry.startTiming.toFixed(2)
                        : "-"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {entry.finishPosition != null
                        ? `${entry.finishPosition}着`
                        : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    scheduled: "bg-gray-100 text-gray-700",
    running: "bg-blue-100 text-blue-700",
    finished: "bg-green-100 text-green-700",
  };
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-xs font-medium ${map[status] ?? "bg-gray-100 text-gray-700"}`}
    >
      {status}
    </span>
  );
}

function gradeClass(grade: string): string {
  if (grade === "A1") return "bg-red-100 text-red-700";
  if (grade === "A2") return "bg-orange-100 text-orange-700";
  if (grade === "B1") return "bg-blue-100 text-blue-700";
  return "bg-gray-100 text-gray-700";
}
