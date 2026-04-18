import { db, predictions, races, stadiums } from "@/lib/db";
import { eq, desc, and, gte } from "drizzle-orm";
import { calcKellyFraction, EV_THRESHOLD, getSeasonalBet } from "@/lib/utils/ev";
import Link from "next/link";
import { ProbThresholdControl } from "./ProbThresholdControl";

export const dynamic = "force-dynamic";

const DEFAULT_PROB_PCT = 7; // S6-4運用ルール: prob ≥ 7%

interface Props {
  searchParams: Promise<{ prob?: string }>;
}

export default async function DashboardPage({ searchParams }: Props) {
  const { prob } = await searchParams;
  const probPct = Math.max(
    1,
    Math.min(50, parseFloat(prob ?? String(DEFAULT_PROB_PCT)) || DEFAULT_PROB_PCT)
  );
  const probThreshold = probPct / 100;

  const now = new Date();
  const jstOffset = 9 * 60 * 60 * 1000;
  const jstNow = new Date(now.getTime() + jstOffset);
  const today = jstNow.toISOString().slice(0, 10);
  const currentMonth = jstNow.getMonth() + 1; // 1-12
  const seasonal = getSeasonalBet(currentMonth);

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
        gte(predictions.winProbability, probThreshold),
        gte(predictions.expectedValue, EV_THRESHOLD) // S6-4: EV ≥ 2.0
      )
    )
    .orderBy(desc(predictions.winProbability));

  return (
    <div className="space-y-6">
      {/* ヘッダー */}
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">本日のレース予測</h2>
        <div className="flex items-center gap-4">
          <ProbThresholdControl current={probPct} />
          <span className="text-sm text-gray-500">{today}</span>
        </div>
      </div>

      {/* 現在の購入ルール */}
      <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
        <h3 className="mb-3 text-sm font-semibold text-blue-800">現在の購入ルール（S6-4運用ルール固定）</h3>
        <div className="grid grid-cols-2 gap-x-8 gap-y-1 text-sm sm:grid-cols-3 lg:grid-cols-6">
          <RuleItem label="的中確率" value="≥ 7%" />
          <RuleItem label="期待値(EV)" value="≥ 2.0" />
          <RuleItem label="除外コース" value="2・4・5番艇" />
          <RuleItem label="最低オッズ" value="100倍以上" />
          <RuleItem label="除外場" value="びわこ(ID=11)" />
          <RuleItem label="ベット額" value={`${seasonal.amount}円/点`} highlight={seasonal.amount !== 100} />
        </div>
        {seasonal.amount !== 100 && (
          <p className="mt-2 text-xs text-blue-700">
            季節性調整: {currentMonth}月は{seasonal.roiNote}のためベット額を{seasonal.amount}円/点に減額推奨。
          </p>
        )}
        <p className="mt-2 text-xs text-blue-600">
          ※ コース・オッズ・場フィルタは <code className="rounded bg-blue-100 px-1">run_predict.py</code> 実行時に適用済み。
          このページは確率・EV条件でさらに絞り込みます。
        </p>
      </div>

      {/* 予測テーブル */}
      {alerts.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 p-12 text-center">
          <p className="text-gray-500">
            本日は的中確率 {probPct}% 以上 かつ EV ≥ {EV_THRESHOLD.toFixed(1)} の舟券はありません。
          </p>
          <p className="mt-2 text-sm text-gray-400">
            GitHub Actions「Predict &amp; Calculate EV」を手動実行して予測データを更新してください。
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
          <div className="border-b border-gray-100 bg-gray-50 px-4 py-2 text-xs text-gray-500">
            確率 ≥ {probPct}% かつ EV ≥ {EV_THRESHOLD.toFixed(1)}（{alerts.length}件）
          </div>
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
                    <td className="px-4 py-3 text-right font-medium text-gray-700">
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

      {/* GitHub Actions 操作ガイド */}
      <div className="rounded-lg border border-gray-200 bg-white p-5">
        <h3 className="mb-4 text-base font-semibold text-gray-800">GitHub Actions 操作ガイド</h3>
        <div className="space-y-3">
          <OperationCard
            freq="日次"
            freqColor="bg-blue-100 text-blue-700"
            workflow="Predict & Calculate EV"
            timing="予測したい日に手動実行"
            description="当日レースの購入候補を取得。run_predict.py が実行され、コース・オッズ・場フィルタが適用されたデータがDBに保存されます。"
          />
          <OperationCard
            freq="月初"
            freqColor="bg-purple-100 text-purple-700"
            workflow="Retrain Model"
            timing="毎月1〜3日に手動実行"
            description="LightGBMモデルを最新データで再学習（softmax正規化 + Isotonic Regression）。再学習後は翌日以降の予測精度が向上します。"
          />
          <OperationCard
            freq="月次"
            freqColor="bg-green-100 text-green-700"
            workflow="Backtest (Real Odds)"
            timing="翌月初に前月分を手動実行"
            description="実オッズで先月のROIを確認。prob=0.07, ev=2.0, --exclude-courses 2 4 5 --min-odds 100 --exclude-stadiums 11 のオプションを指定してください。収支分析ページで停止条件と照合。"
          />
          <OperationCard
            freq="週次(自動)"
            freqColor="bg-gray-100 text-gray-600"
            workflow="Collect Race Data"
            timing="毎週日曜 03:00 JST（自動）"
            description="選手STスタッツ（直近2年スタートタイミング平均）を自動更新。手動実行も可能。"
          />
          <OperationCard
            freq="四半期"
            freqColor="bg-yellow-100 text-yellow-700"
            workflow="Calibration Analysis"
            timing="3ヶ月ごとに手動実行"
            description="モデルのキャリブレーション精度（ECE）を確認。1着ECE が大幅悪化（+30%以上）していたら再学習を検討。"
          />
          <OperationCard
            freq="半期"
            freqColor="bg-orange-100 text-orange-700"
            workflow="Walk-Forward Backtest"
            timing="6ヶ月ごとに手動実行"
            description="複数月にわたる実オッズWalk-Forward検証で戦略の統計的信頼性を再確認。--start / --end で期間を指定。"
          />
          <OperationCard
            freq="不定期"
            freqColor="bg-red-100 text-red-700"
            workflow="Grid Search / Segment Analysis"
            timing="停止条件トリガー時（ROI<500%が3ヶ月連続など）"
            description="場・コース・オッズ帯・確率帯別ROIを分析して劣化箇所を特定。グリッドサーチで閾値を再最適化。"
          />
        </div>
      </div>

      {/* 停止条件クイックリファレンス */}
      <div className="rounded-lg border border-gray-200 bg-white p-5">
        <h3 className="mb-3 text-base font-semibold text-gray-800">
          停止条件クイックリファレンス
          <span className="ml-2 text-xs font-normal text-gray-500">S6-3実績（24ヶ月全月プラス）に基づく</span>
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-gray-200 text-xs text-gray-500">
              <tr>
                <th className="pb-2 text-left">ゾーン</th>
                <th className="pb-2 text-left">月次ROI基準</th>
                <th className="pb-2 text-left">S6-3実績</th>
                <th className="pb-2 text-left">アクション</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 text-sm">
              <tr>
                <td className="py-2"><span className="rounded px-2 py-0.5 text-xs font-medium text-green-700 bg-green-100">正常域</span></td>
                <td className="py-2">≥ 500%</td>
                <td className="py-2 text-gray-500">22/24ヶ月（92%）</td>
                <td className="py-2 text-green-700">継続</td>
              </tr>
              <tr>
                <td className="py-2"><span className="rounded px-2 py-0.5 text-xs font-medium text-yellow-700 bg-yellow-100">注意域</span></td>
                <td className="py-2">300〜499%</td>
                <td className="py-2 text-gray-500">1/24ヶ月（4%）</td>
                <td className="py-2 text-yellow-700">要観察（翌月改善なら継続）</td>
              </tr>
              <tr>
                <td className="py-2"><span className="rounded px-2 py-0.5 text-xs font-medium text-orange-700 bg-orange-100">警戒域</span></td>
                <td className="py-2">0〜299%</td>
                <td className="py-2 text-gray-500">0/24ヶ月</td>
                <td className="py-2 text-orange-700 font-medium">一時停止 → 再学習 + 分析</td>
              </tr>
              <tr>
                <td className="py-2"><span className="rounded px-2 py-0.5 text-xs font-medium text-red-700 bg-red-100">危険域</span></td>
                <td className="py-2">{"< 0%"}</td>
                <td className="py-2 text-gray-500">0/24ヶ月</td>
                <td className="py-2 text-red-700 font-bold">即時停止 → 総点検</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="mt-3 space-y-1 text-xs text-gray-500">
          <p>• ROI {"<"} 300% が<strong>2ヶ月連続</strong> → 一時停止 + run_retrain.py 再学習</p>
          <p>• ROI {"<"} 500% が<strong>3ヶ月連続</strong> → Grid Search でルール再最適化</p>
          <p>• ベット数が月平均（2,600件）の<strong>50%未満</strong> → データ取得・フィルタ設定を確認</p>
        </div>
      </div>
    </div>
  );
}

function RuleItem({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className="flex flex-col">
      <span className="text-xs text-blue-600">{label}</span>
      <span className={`font-semibold ${highlight ? "text-orange-700" : "text-blue-900"}`}>
        {value}
      </span>
    </div>
  );
}

function OperationCard({
  freq,
  freqColor,
  workflow,
  timing,
  description,
}: {
  freq: string;
  freqColor: string;
  workflow: string;
  timing: string;
  description: string;
}) {
  return (
    <div className="flex gap-3 rounded-lg border border-gray-100 bg-gray-50 p-3">
      <div className="shrink-0">
        <span className={`inline-block rounded px-2 py-0.5 text-xs font-semibold ${freqColor}`}>
          {freq}
        </span>
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="font-medium text-gray-800">{workflow}</span>
          <span className="text-xs text-gray-500">{timing}</span>
        </div>
        <p className="mt-0.5 text-xs text-gray-600">{description}</p>
      </div>
    </div>
  );
}
