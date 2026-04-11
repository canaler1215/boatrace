"""
合成オッズ生成モジュール

アプローチ: 「艇番ベースの市場」
  実際の市場を「艇番（コース位置）のみを根拠にする投票者集団」と仮定し、
  Plackett-Luce モデルで 3 連単の市場確率を計算する。

  市場オッズ = PAYOUT_RATE / P_market(combo)

この設計の意味:
  EV = P_model(combo) × market_odds(combo)
     = P_model(combo) / P_market(combo) × PAYOUT_RATE

  EV > 1.2 ⟺ モデルが艇番ベース期待値より 20% 超の確率を見込んでいる
  → モデルが展示タイム・ST などのレース固有情報を活用できているかを検証できる
"""
from itertools import permutations

# 競艇全国平均 1 着入着率（艇番別）
# 出典: 日本モーターボート競走会 統計資料
BOAT_WIN_RATES: dict[int, float] = {
    1: 0.450,
    2: 0.150,
    3: 0.130,
    4: 0.110,
    5: 0.090,
    6: 0.070,
}

# 3 連単払戻率（競艇は約 75%）
PAYOUT_RATE: float = 0.75


def _calc_market_trifecta_probs() -> dict[str, float]:
    """
    Plackett-Luce モデルで艇番ベース 3 連単確率を計算する。

    P(a-b-c) = P(a 1着) × P(b 2着 | a 1着) × P(c 3着 | a 1着, b 2着)
             = w_a × (w_b / (1 - w_a)) × (w_c / (1 - w_a - w_b))

    120 通りの合計は 1.0 に収束（Plackett-Luce は proper distribution）。
    """
    rates = BOAT_WIN_RATES
    result: dict[str, float] = {}

    for combo in permutations(range(1, 7), 3):
        a, b, c = combo
        denom_ab = 1.0 - rates[a]
        denom_abc = denom_ab - rates[b]

        p = rates[a]
        p *= rates[b] / max(denom_ab, 1e-9)
        p *= rates[c] / max(denom_abc, 1e-9)

        result[f"{a}-{b}-{c}"] = float(p)

    return result


def _calc_synthetic_odds(
    market_probs: dict[str, float],
    payout_rate: float = PAYOUT_RATE,
) -> dict[str, float]:
    """
    合成オッズ = payout_rate / P_market(combo)

    P_market の合計が厳密に 1.0 でなくても、
    各コンボのオッズ比率は保持される。
    """
    return {
        combo: round(payout_rate / max(p, 1e-9), 2)
        for combo, p in market_probs.items()
    }


# モジュールロード時に一度だけ計算（全レース共通）
MARKET_TRIFECTA_PROBS: dict[str, float] = _calc_market_trifecta_probs()
SYNTHETIC_ODDS: dict[str, float] = _calc_synthetic_odds(MARKET_TRIFECTA_PROBS)
