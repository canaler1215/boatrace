import { db, bets } from "@/lib/db";
import { sql } from "drizzle-orm";
import {
  calcROI,
  getMonitoringZone,
  ZONE_LABELS,
  ZONE_ROI_RANGE,
  ZONE_ACTION,
  ZONE_CSS,
  ZONE_BADGE_CSS,
  type MonitoringZone,
} from "@/lib/utils/ev";

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

  // 回収率 (payout/amount): 100% = 損益ゼロ（日本競馬・競艇の標準表記）
  const payoutRate = totalAmount > 0 ? (totalPayout / totalAmount) * 100 : 0;
  // ROI (CLAUDE.md形式): (payout/amount - 1) × 100、0% = 損益ゼロ
  const roiPct = calcROI(totalPayout, totalAmount);
  const winRate = decided > 0 ? wins / decided : 0;
  const profit = totalPayout - totalAmount;
  const overallZone: MonitoringZone | null =
    roiPct !== null ? getMonitoringZone(roiPct) : null;

  // 月別集計（直近12ヶ月）
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

  // 停止条件チェック（直近月から判定）
  const monthlyROIs = monthly.map((m) => {
    const amt = Number(m.amount);
    const pay = Number(m.payout);
    return calcROI(pay, amt) ?? 0;
  });

  const below300Count = monthlyROIs.slice(0, 2).filter((r) => r < 300).length;
  const below500Count = monthlyROIs.slice(0, 3).filter((r) => r < 500).length;
  const hasZeroMinus = monthlyROIs.slice(0, 1).some((r) => r < 0);

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">収支分析</h2>

      {/* サマリーカード */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard title="総購入件数" value={`${totalBets}件`} />
        <StatCard title="総購入金額" value={`${totalAmount.toLocaleString()}円`} />
        <StatCard title="総払戻金額" value={`${totalPayout.toLocaleString()}円`} />
        <StatCard
          title="損益"
          value={`${profit >= 0 ? "+" : ""}${profit.toLocaleString()}円`}
          highlight={profit >= 0 ? "green" : "red"}
        />
      </div>

      {/* ROI + 回収率 + 的中率 */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {/* ROI（CLAUDE.md形式） */}
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="mb-1 text-base font-semibold">ROI（利益率）</h3>
          <p
            className={`mb-1 text-3xl font-bold ${
              roiPct === null
                ? "text-gray-400"
                : roiPct >= 0
                  ? "text-green-600"
                  : "text-red-600"
            }`}
          >
            {roiPct !== null
              ? `${roiPct >= 0 ? "+" : ""}${roiPct.toFixed(1)}%`
              : "-"}
          </p>
          <p className="mb-3 text-xs text-gray-400">
            (払戻 / 投資 − 1) × 100 ※ 0% = 損益ゼロ
          </p>
          {overallZone && (
            <div className={`rounded border px-3 py-2 text-sm ${ZONE_CSS[overallZone]}`}>
              <span className="font-semibold">{ZONE_LABELS[overallZone]}</span>
              <span className="ml-2 text-xs">{ZONE_ROI_RANGE[overallZone]}</span>
              <p className="mt-1 text-xs">{ZONE_ACTION[overallZone]}</p>
            </div>
          )}
        </div>

        {/* 回収率（日本競艇標準表記） */}
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="mb-1 text-base font-semibold">回収率</h3>
          <p
            className={`mb-3 text-3xl font-bold ${payoutRate >= 100 ? "text-green-600" : "text-red-600"}`}
          >
            {totalAmount > 0 ? `${payoutRate.toFixed(1)}%` : "-"}
          </p>
          <div className="h-3 overflow-hidden rounded-full bg-gray-200">
            <div
              className={`h-3 rounded-full transition-all ${payoutRate >= 100 ? "bg-green-500" : "bg-red-500"}`}
              style={{ width: `${Math.min(payoutRate, 200) / 2}%` }}
            />
          </div>
          <p className="mt-1 text-xs text-gray-400">
            基準ライン: 100%（損益ゼロ）| ROI = 回収率 − 100%
          </p>
        </div>

        {/* 的中率 */}
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
          <p className="mt-1 text-xs text-gray-400">
            S6-3実績: 1.53% avg（的中時 avg 586倍）
          </p>
        </div>
      </div>

      {/* 停止条件チェック */}
      {monthly.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <h3 className="mb-3 text-base font-semibold text-gray-800">
            停止条件チェック
            <span className="ml-2 text-xs font-normal text-gray-500">
              S6-4運用ルールに基づく自動判定
            </span>
          </h3>
          <div className="space-y-2">
            <StopConditionRow
              label="直近月ROI < 0%（即時停止）"
              triggered={hasZeroMinus}
              triggeredAction="即時停止 → Calibration + Segment Analysis で原因分析"
              okLabel="問題なし"
            />
            <StopConditionRow
              label={`ROI < 300% が2ヶ月連続（直近2ヶ月: ${below300Count}/2ヶ月該当）`}
              triggered={below300Count >= 2}
              triggeredAction="一時停止 → run_retrain.py 再学習 + 直近3ヶ月セグメント分析"
              okLabel="問題なし"
            />
            <StopConditionRow
              label={`ROI < 500% が3ヶ月連続（直近3ヶ月: ${below500Count}/3ヶ月該当）`}
              triggered={below500Count >= 3}
              triggeredAction="ルール見直し → Grid Search で閾値再最適化"
              okLabel="問題なし"
            />
          </div>
          <p className="mt-3 text-xs text-gray-400">
            ※ 判定は記録済みのbet結果に基づきます。月次バックテスト結果（GitHub Actions: Backtest）と照合してください。
          </p>
        </div>
      )}

      {/* 月別収支 */}
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold">月別収支</h3>
          <div className="flex gap-2 text-xs">
            <span className="rounded px-2 py-0.5 text-green-700 bg-green-100">正常域 ≥500%</span>
            <span className="rounded px-2 py-0.5 text-yellow-700 bg-yellow-100">注意域 300-499%</span>
            <span className="rounded px-2 py-0.5 text-orange-700 bg-orange-100">警戒域 0-299%</span>
            <span className="rounded px-2 py-0.5 text-red-700 bg-red-100">危険域 &#x3C;0%</span>
          </div>
        </div>
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
                <th className="pb-2 text-right">ROI</th>
                <th className="pb-2 text-center">ゾーン</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {monthly.map((row) => {
                const amt = Number(row.amount);
                const pay = Number(row.payout);
                const prof = pay - amt;
                const roi = calcROI(pay, amt);
                const zone = roi !== null ? getMonitoringZone(roi) : null;
                return (
                  <tr key={row.month}>
                    <td className="py-2 font-medium">{row.month}</td>
                    <td className="py-2 text-right">{Number(row.count)}件</td>
                    <td className="py-2 text-right">{amt.toLocaleString()}円</td>
                    <td className="py-2 text-right">{pay.toLocaleString()}円</td>
                    <td
                      className={`py-2 text-right font-medium ${prof >= 0 ? "text-green-600" : "text-red-600"}`}
                    >
                      {prof >= 0 ? "+" : ""}
                      {prof.toLocaleString()}円
                    </td>
                    <td
                      className={`py-2 text-right font-semibold ${
                        roi === null
                          ? "text-gray-400"
                          : roi >= 0
                            ? "text-green-600"
                            : "text-red-600"
                      }`}
                    >
                      {roi !== null
                        ? `${roi >= 0 ? "+" : ""}${roi.toFixed(1)}%`
                        : "-"}
                    </td>
                    <td className="py-2 text-center">
                      {zone ? (
                        <span
                          className={`rounded px-2 py-0.5 text-xs font-medium ${ZONE_BADGE_CSS[zone]}`}
                        >
                          {ZONE_LABELS[zone]}
                        </span>
                      ) : (
                        <span className="text-gray-400">-</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* 運用メモ */}
      <div className="rounded-lg border border-gray-100 bg-gray-50 p-4 text-xs text-gray-500 space-y-1">
        <p className="font-medium text-gray-700">モデル特性メモ（S6-3実績）</p>
        <p>• 宝くじ構造: 的中率 avg 1.53% × 的中時 avg 586倍。月次ベット数が少ないと確率的ブレが大きくなります。</p>
        <p>• 1着識別能力: 全予測ビンで実際的中率 ~17%（ランダム相当）。ROIは確率精度ではなく高オッズ×絞り込みに依存。</p>
        <p>• 季節性: 3月（実績平均ROI 465%）・6月（578%）が低め。7〜9月・12月（900%〜1,106%）が高め。</p>
        <p>• S6-3 Walk-Forward 24ヶ月全月プラス: 最低 +297.9%（2024-06）、最高 +1,430.3%（2025-12）、std 220%。</p>
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

function StopConditionRow({
  label,
  triggered,
  triggeredAction,
  okLabel,
}: {
  label: string;
  triggered: boolean;
  triggeredAction: string;
  okLabel: string;
}) {
  return (
    <div
      className={`flex items-start gap-3 rounded-lg border p-3 ${
        triggered
          ? "border-red-200 bg-red-50"
          : "border-green-200 bg-green-50"
      }`}
    >
      <span className="mt-0.5 text-base leading-none">
        {triggered ? "⚠️" : "✅"}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-gray-800">{label}</p>
        {triggered ? (
          <p className="mt-0.5 text-xs font-semibold text-red-700">{triggeredAction}</p>
        ) : (
          <p className="mt-0.5 text-xs text-green-700">{okLabel}</p>
        )}
      </div>
    </div>
  );
}
