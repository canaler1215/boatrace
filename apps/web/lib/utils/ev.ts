/**
 * 期待値計算
 * 期待値 = 的中確率 × オッズ
 */
export function calcExpectedValue(probability: number, odds: number): number {
  return probability * odds;
}

/**
 * Kelly基準によるベット割合（保守的に1/4 Kelly）
 * ベット割合 = (期待値 - 1) / (オッズ - 1)
 */
export function calcKellyFraction(
  expectedValue: number,
  odds: number,
  fraction = 0.25
): number {
  if (odds <= 1) return 0;
  const kelly = (expectedValue - 1) / (odds - 1);
  return Math.max(0, kelly * fraction);
}

/** S6-4運用ルール: 的中確率閾値 ≥ 7% */
export const PROB_THRESHOLD = 0.07;

/** S6-4運用ルール: 期待値閾値 ≥ 2.0 */
export const EV_THRESHOLD = 2.0;

export function isAlertProb(prob: number): boolean {
  return prob >= PROB_THRESHOLD;
}

export function isAlertEV(ev: number): boolean {
  return ev >= EV_THRESHOLD;
}

/**
 * ROI (CLAUDE.md形式): (払戻額 / 投資額 - 1) × 100
 * 例: 払戻9万 / 投資1万 → ROI = 800%
 * 損益ゼロ = 0%, 競艇公式払戻率75% → ROI = -25%
 */
export function calcROI(totalPayout: number, totalAmount: number): number | null {
  if (totalAmount === 0) return null;
  return (totalPayout / totalAmount - 1) * 100;
}

export type MonitoringZone = "normal" | "caution" | "warning" | "danger";

/**
 * S6-4運用ルールに基づくモニタリングゾーン判定
 * 正常域 ≥ 500% | 注意域 300-499% | 警戒域 0-299% | 危険域 < 0%
 */
export function getMonitoringZone(roi: number): MonitoringZone {
  if (roi < 0) return "danger";
  if (roi < 300) return "warning";
  if (roi < 500) return "caution";
  return "normal";
}

export const ZONE_LABELS: Record<MonitoringZone, string> = {
  normal: "正常域",
  caution: "注意域",
  warning: "警戒域",
  danger: "危険域",
};

export const ZONE_ROI_RANGE: Record<MonitoringZone, string> = {
  normal: "≥ 500%",
  caution: "300〜499%",
  warning: "0〜299%",
  danger: "< 0%",
};

export const ZONE_ACTION: Record<MonitoringZone, string> = {
  normal: "継続",
  caution: "要観察（翌月改善なら継続）",
  warning: "一時停止 → 再学習 + 直近3ヶ月分析",
  danger: "即時停止 → モデル・ルール総点検",
};

export const ZONE_CSS: Record<MonitoringZone, string> = {
  normal: "text-green-700 bg-green-100 border-green-300",
  caution: "text-yellow-700 bg-yellow-100 border-yellow-300",
  warning: "text-orange-700 bg-orange-100 border-orange-300",
  danger: "text-red-700 bg-red-100 border-red-300",
};

export const ZONE_BADGE_CSS: Record<MonitoringZone, string> = {
  normal: "text-green-700 bg-green-100",
  caution: "text-yellow-700 bg-yellow-100",
  warning: "text-orange-700 bg-orange-100",
  danger: "text-red-700 bg-red-100",
};

/** S6-3実績ベースの月別推奨ベット額 */
export const SEASONAL_BET: Record<number, { amount: number; roiNote: string }> = {
  3: { amount: 70, roiNote: "実績平均ROI 465%（年間最低）" },
  6: { amount: 80, roiNote: "実績平均ROI 578%（年間2位低）" },
};

export function getSeasonalBet(month: number): { amount: number; roiNote: string } {
  return SEASONAL_BET[month] ?? { amount: 100, roiNote: "標準月（実績平均ROI ~800%）" };
}
