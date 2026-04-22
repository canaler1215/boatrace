/**
 * evDrift.ts の単体テスト
 *
 * node --import tsx apps/web/lib/utils/evDrift.test.ts で実行可能。
 * 他の簡易テスト（ml/tests/test_final_odds_writer.py）と同じ方針で、
 * 外部テストランナーに依存せず assert ベースで検証する。
 */
import assert from "node:assert/strict";
import {
  calcFinalEV,
  calcDrift,
  summarizeEVDrift,
  summarizeByOddsBin,
  driftSeverity,
  ODDS_BINS,
  type EVDriftRow,
} from "./evDrift";

type TestFn = () => void;

function test(name: string, fn: TestFn): { name: string; fn: TestFn } {
  return { name, fn };
}

const tests = [
  test("calcFinalEV: 勝率 10% × 確定オッズ 20x = 2.0", () => {
    assert.equal(calcFinalEV(0.1, 20), 2);
  }),

  test("calcDrift: finalEV - predictedEV", () => {
    // predicted=3.0, final=2.0 → 予測が過大だった（drift=-1.0）
    assert.equal(calcDrift(3.0, 2.0), -1.0);
    // predicted=2.0, final=3.0 → 予測が控えめだった（drift=+1.0）
    assert.equal(calcDrift(2.0, 3.0), 1.0);
  }),

  test("summarizeEVDrift: 空配列は全てゼロ", () => {
    const s = summarizeEVDrift([]);
    assert.equal(s.count, 0);
    assert.equal(s.avgPredictedEV, 0);
    assert.equal(s.avgFinalEV, 0);
    assert.equal(s.avgDrift, 0);
    assert.equal(s.rmse, 0);
    assert.equal(s.overEstimatedRate, 0);
    assert.equal(s.underEstimatedRate, 0);
  }),

  test("summarizeEVDrift: 3件の過大・一致・過小を集計", () => {
    // prob=0.1, finalOdds=10 → finalEV=1.0
    const rows: EVDriftRow[] = [
      { predictedEV: 1.5, winProbability: 0.1, finalOdds: 10 }, // 過大 drift=-0.5
      { predictedEV: 1.0, winProbability: 0.1, finalOdds: 10 }, // 一致 drift=0
      { predictedEV: 0.6, winProbability: 0.1, finalOdds: 10 }, // 過小 drift=+0.4
    ];
    const s = summarizeEVDrift(rows);
    assert.equal(s.count, 3);
    // avgPredictedEV = (1.5+1.0+0.6)/3 = 1.0333...
    assert.ok(Math.abs(s.avgPredictedEV - 1.0333333333) < 1e-6);
    assert.equal(s.avgFinalEV, 1.0);
    // avgDrift = (-0.5 + 0 + 0.4)/3 = -0.0333...
    assert.ok(Math.abs(s.avgDrift - -0.0333333333) < 1e-6);
    // avgAbsDrift = (0.5 + 0 + 0.4)/3 = 0.3
    assert.ok(Math.abs(s.avgAbsDrift - 0.3) < 1e-6);
    // rmse = sqrt((0.25 + 0 + 0.16)/3) = sqrt(0.1366...) ≈ 0.3697
    assert.ok(Math.abs(s.rmse - Math.sqrt(0.41 / 3)) < 1e-9);
    assert.ok(Math.abs(s.overEstimatedRate - 1 / 3) < 1e-9);
    assert.ok(Math.abs(s.underEstimatedRate - 1 / 3) < 1e-9);
  }),

  test("summarizeEVDrift: 全件過大評価で over_rate=1.0", () => {
    const rows: EVDriftRow[] = [
      { predictedEV: 3.0, winProbability: 0.1, finalOdds: 10 }, // final=1.0, drift=-2.0
      { predictedEV: 5.0, winProbability: 0.2, finalOdds: 10 }, // final=2.0, drift=-3.0
    ];
    const s = summarizeEVDrift(rows);
    assert.equal(s.overEstimatedRate, 1.0);
    assert.equal(s.underEstimatedRate, 0.0);
    assert.equal(s.avgDrift, -2.5);
  }),

  test("summarizeByOddsBin: ビン数が ODDS_BINS と一致", () => {
    const result = summarizeByOddsBin([]);
    assert.equal(result.length, ODDS_BINS.length);
    result.forEach((r, i) => {
      assert.equal(r.bin.label, ODDS_BINS[i].label);
      assert.equal(r.summary.count, 0);
    });
  }),

  test("summarizeByOddsBin: 確定オッズで正しいビンに振り分け", () => {
    const rows: EVDriftRow[] = [
      { predictedEV: 1.5, winProbability: 0.05, finalOdds: 30 }, // < 50x
      { predictedEV: 2.0, winProbability: 0.05, finalOdds: 80 }, // 50-100x
      { predictedEV: 3.0, winProbability: 0.05, finalOdds: 200 }, // 100-300x
      { predictedEV: 5.0, winProbability: 0.05, finalOdds: 500 }, // 300-600x
      { predictedEV: 8.0, winProbability: 0.05, finalOdds: 800 }, // 600-1000x
      { predictedEV: 20.0, winProbability: 0.05, finalOdds: 5000 }, // ≥ 1000x
    ];
    const result = summarizeByOddsBin(rows);
    for (const r of result) {
      assert.equal(r.summary.count, 1, `bin ${r.bin.label} should have 1 row`);
    }
  }),

  test("summarizeByOddsBin: 境界値は下限に含まれ上限に含まれない（min<=x<max）", () => {
    // 100x ちょうどは 100-300x に入るべき
    const rows: EVDriftRow[] = [
      { predictedEV: 2.0, winProbability: 0.02, finalOdds: 100 },
    ];
    const result = summarizeByOddsBin(rows);
    const bin100 = result.find((r) => r.bin.label === "100-300x");
    const bin50 = result.find((r) => r.bin.label === "50-100x");
    assert.ok(bin100);
    assert.ok(bin50);
    assert.equal(bin100!.summary.count, 1);
    assert.equal(bin50!.summary.count, 0);
  }),

  test("driftSeverity: 境界値で想定ラベルを返す", () => {
    assert.equal(driftSeverity(0).label, "良好");
    assert.equal(driftSeverity(-0.2).label, "良好");
    assert.equal(driftSeverity(-0.3).label, "やや過大");
    assert.equal(driftSeverity(-0.5).label, "やや過大");
    assert.equal(driftSeverity(-0.7).label, "過大評価");
    assert.equal(driftSeverity(-1.0).label, "過大評価");
    assert.equal(driftSeverity(-1.5).label, "重度の過大評価");
  }),
];

let passed = 0;
let failed = 0;
for (const t of tests) {
  try {
    t.fn();
    console.log(`  PASS: ${t.name}`);
    passed += 1;
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.log(`  FAIL: ${t.name}\n    ${msg}`);
    failed += 1;
  }
}
console.log(`\n${passed}/${passed + failed} passed`);
process.exit(failed === 0 ? 0 : 1);
