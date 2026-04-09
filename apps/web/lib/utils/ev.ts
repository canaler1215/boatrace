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

export const EV_THRESHOLD = 1.2;

export function isAlertEV(ev: number): boolean {
  return ev >= EV_THRESHOLD;
}
