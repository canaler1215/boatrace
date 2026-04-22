/**
 * EV 乖離（Drift）ユーティリティ
 *
 * D-2: 予測時 EV（predictions.expected_value）と確定 EV
 * （win_probability × predictions.final_odds）の乖離を集計する。
 *
 * 「予測時に見ていた EV が、確定オッズベースで見るとどれだけズレていたか」
 * を継続モニタリングするためのロジック。A-3 で保存された final_odds が前提。
 */

export interface EVDriftRow {
  predictedEV: number;
  winProbability: number;
  finalOdds: number;
}

export interface EVDriftSummary {
  count: number;
  avgPredictedEV: number;
  avgFinalEV: number;
  avgDrift: number; // 平均 (finalEV - predictedEV)
  avgAbsDrift: number; // 平均絶対乖離
  rmse: number;
  overEstimatedRate: number; // predictedEV > finalEV の割合（過大評価率）
  underEstimatedRate: number; // predictedEV < finalEV の割合（過小評価率）
}

/**
 * 確定 EV を計算: 的中確率 × 確定オッズ
 */
export function calcFinalEV(winProbability: number, finalOdds: number): number {
  return winProbability * finalOdds;
}

/**
 * 乖離 = 確定 EV - 予測時 EV
 * 正 → 確定時の方が EV が高かった（実力より控えめに予測）
 * 負 → 確定時の方が EV が低かった（予測時に過大評価していた）
 */
export function calcDrift(predictedEV: number, finalEV: number): number {
  return finalEV - predictedEV;
}

/**
 * 集計: 行リストから平均・RMSE・過大評価率などを一括算出
 */
export function summarizeEVDrift(rows: EVDriftRow[]): EVDriftSummary {
  const count = rows.length;
  if (count === 0) {
    return {
      count: 0,
      avgPredictedEV: 0,
      avgFinalEV: 0,
      avgDrift: 0,
      avgAbsDrift: 0,
      rmse: 0,
      overEstimatedRate: 0,
      underEstimatedRate: 0,
    };
  }

  let sumPredicted = 0;
  let sumFinal = 0;
  let sumDrift = 0;
  let sumAbsDrift = 0;
  let sumSquaredDrift = 0;
  let overCount = 0;
  let underCount = 0;

  for (const row of rows) {
    const finalEV = calcFinalEV(row.winProbability, row.finalOdds);
    const drift = calcDrift(row.predictedEV, finalEV);
    sumPredicted += row.predictedEV;
    sumFinal += finalEV;
    sumDrift += drift;
    sumAbsDrift += Math.abs(drift);
    sumSquaredDrift += drift * drift;
    if (row.predictedEV > finalEV) overCount += 1;
    else if (row.predictedEV < finalEV) underCount += 1;
  }

  return {
    count,
    avgPredictedEV: sumPredicted / count,
    avgFinalEV: sumFinal / count,
    avgDrift: sumDrift / count,
    avgAbsDrift: sumAbsDrift / count,
    rmse: Math.sqrt(sumSquaredDrift / count),
    overEstimatedRate: overCount / count,
    underEstimatedRate: underCount / count,
  };
}

/**
 * オッズ帯別（確定オッズ）ビン定義
 * 現行の購入ルールが min_odds=100 なので 100x 以上を細かく分ける
 */
export interface OddsBin {
  label: string;
  min: number; // 含む
  max: number; // 未満
}

export const ODDS_BINS: OddsBin[] = [
  { label: "< 50x", min: 0, max: 50 },
  { label: "50-100x", min: 50, max: 100 },
  { label: "100-300x", min: 100, max: 300 },
  { label: "300-600x", min: 300, max: 600 },
  { label: "600-1000x", min: 600, max: 1000 },
  { label: "≥ 1000x", min: 1000, max: Infinity },
];

/**
 * オッズ帯別に集計。確定オッズを基準にビンへ振り分ける。
 */
export function summarizeByOddsBin(
  rows: EVDriftRow[]
): { bin: OddsBin; summary: EVDriftSummary }[] {
  return ODDS_BINS.map((bin) => {
    const subset = rows.filter(
      (r) => r.finalOdds >= bin.min && r.finalOdds < bin.max
    );
    return { bin, summary: summarizeEVDrift(subset) };
  });
}

/**
 * 乖離度のラベル・CSS 付与
 * 「予測時 EV が確定 EV をどれくらい上回っていたか」の過大評価度合いで色分け。
 * predictedEV >> finalEV は購入判断の信頼性を損なうため警戒色。
 */
export function driftSeverity(avgDrift: number): {
  label: string;
  cls: string;
} {
  // avgDrift = finalEV - predictedEV。負が大きいほど過大評価。
  if (avgDrift >= -0.2) return { label: "良好", cls: "text-green-700 bg-green-100" };
  if (avgDrift >= -0.5)
    return { label: "やや過大", cls: "text-yellow-700 bg-yellow-100" };
  if (avgDrift >= -1.0)
    return { label: "過大評価", cls: "text-orange-700 bg-orange-100" };
  return { label: "重度の過大評価", cls: "text-red-700 bg-red-100" };
}
