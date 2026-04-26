"""Claude (LLM) が出力する予想 JSON のスキーマ + バリデーション.

設計書 LLM_PREDICT_DESIGN.md §3.2 に準拠.
pydantic は依存に持たないため、dataclass + 手書き validate で実装する.

JSON 例:
    {
      "race_id": "2025-12-01_01_01",
      "predicted_at": "2025-12-01T15:00:00+09:00",
      "model": "claude-opus-4-7",
      "analysis": "1号艇は B1...",
      "primary_axis": [1, 4],
      "verdict": "bet",
      "skip_reason": null,
      "bets": [
        {
          "trifecta": "1-4-3",
          "stake": 100,
          "current_odds": 12.5,
          "expected_prob": 0.10,
          "ev": 1.25,
          "confidence": 0.6
        }
      ]
    }
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

VALID_VERDICTS = ("bet", "skip")
VALID_BOAT_NOS = (1, 2, 3, 4, 5, 6)

# 3 連単 / 3 連複 共通: "1-2-3" / "1=2=3" 等. 本実装は 3 連単のみ "N-N-N" 形式を要求
_TRIFECTA_RE = re.compile(r"^([1-6])-([1-6])-([1-6])$")


class PredictionValidationError(ValueError):
    """予想 JSON の構造が不正."""


@dataclass
class Bet:
    trifecta: str  # "1-4-3" 形式 (3 桁の艇番ハイフン区切り、重複不可)
    stake: int  # 円 (100 単位想定だがバリデーションは正の整数のみ)
    current_odds: float  # 倍率
    expected_prob: float  # 0.0 〜 1.0
    ev: float  # = expected_prob * current_odds (Claude 算出値、信用しない)
    confidence: float  # 0.0 〜 1.0 (Claude 自由値、初期は閾値判定なし)


@dataclass
class Prediction:
    race_id: str  # "YYYY-MM-DD_NN_RR" (例 "2025-12-01_01_01")
    predicted_at: str  # ISO8601
    model: str  # "claude-opus-4-7" 等 (実行時 Claude が自己申告)
    analysis: str  # 自由記述 (本選択の根拠)
    primary_axis: list[int]  # 軸艇 1〜2 個
    verdict: str  # "bet" | "skip"
    skip_reason: str | None  # verdict == "skip" のときに必須
    bets: list[Bet]  # verdict == "bet" のときに 1 件以上, "skip" のときは空


# ---------------------------------------------------------------------------
# バリデーション
# ---------------------------------------------------------------------------


def _validate_bet(b: dict, idx: int) -> Bet:
    """1 件の bet dict を Bet にして返す. 不正なら PredictionValidationError."""
    if not isinstance(b, dict):
        raise PredictionValidationError(f"bets[{idx}] must be object")

    trifecta = b.get("trifecta")
    if not isinstance(trifecta, str) or not _TRIFECTA_RE.match(trifecta):
        raise PredictionValidationError(
            f"bets[{idx}].trifecta must match 'N-N-N' (1-6): {trifecta!r}"
        )
    parts = trifecta.split("-")
    if len(set(parts)) != 3:
        raise PredictionValidationError(
            f"bets[{idx}].trifecta has duplicate boats: {trifecta!r}"
        )

    stake = b.get("stake")
    if not isinstance(stake, int) or stake <= 0:
        raise PredictionValidationError(f"bets[{idx}].stake must be positive int: {stake!r}")

    current_odds = b.get("current_odds")
    if not isinstance(current_odds, (int, float)) or current_odds <= 0:
        raise PredictionValidationError(
            f"bets[{idx}].current_odds must be positive number: {current_odds!r}"
        )

    expected_prob = b.get("expected_prob")
    if not isinstance(expected_prob, (int, float)) or not (0.0 <= expected_prob <= 1.0):
        raise PredictionValidationError(
            f"bets[{idx}].expected_prob must be in [0,1]: {expected_prob!r}"
        )

    ev = b.get("ev")
    if not isinstance(ev, (int, float)) or ev < 0:
        raise PredictionValidationError(f"bets[{idx}].ev must be non-negative: {ev!r}")

    confidence = b.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
        raise PredictionValidationError(
            f"bets[{idx}].confidence must be in [0,1]: {confidence!r}"
        )

    return Bet(
        trifecta=trifecta,
        stake=int(stake),
        current_odds=float(current_odds),
        expected_prob=float(expected_prob),
        ev=float(ev),
        confidence=float(confidence),
    )


def validate(payload: dict) -> Prediction:
    """dict (json.load の出力等) を Prediction に変換.

    不正なら PredictionValidationError を送出.
    """
    if not isinstance(payload, dict):
        raise PredictionValidationError("payload must be object")

    race_id = payload.get("race_id")
    if not isinstance(race_id, str) or not re.match(
        r"^\d{4}-\d{2}-\d{2}_\d{2}_\d{2}$", race_id
    ):
        raise PredictionValidationError(
            f"race_id must be 'YYYY-MM-DD_NN_RR' format: {race_id!r}"
        )

    predicted_at = payload.get("predicted_at")
    if not isinstance(predicted_at, str):
        raise PredictionValidationError("predicted_at must be ISO8601 string")
    # parse 試行 (失敗してもエラーにせず警告にとどめる方針もあるが、ここは厳しめに)
    try:
        _dt.datetime.fromisoformat(predicted_at)
    except ValueError as exc:
        raise PredictionValidationError(f"predicted_at not ISO8601: {predicted_at!r}") from exc

    model = payload.get("model")
    if not isinstance(model, str) or not model:
        raise PredictionValidationError("model must be non-empty string")

    analysis = payload.get("analysis")
    if not isinstance(analysis, str) or not analysis.strip():
        raise PredictionValidationError("analysis must be non-empty string")

    primary_axis = payload.get("primary_axis", [])
    if not isinstance(primary_axis, list) or not (1 <= len(primary_axis) <= 2):
        raise PredictionValidationError(
            f"primary_axis must be list of 1-2 ints: {primary_axis!r}"
        )
    for v in primary_axis:
        if v not in VALID_BOAT_NOS:
            raise PredictionValidationError(f"primary_axis contains invalid boat: {v!r}")

    verdict = payload.get("verdict")
    if verdict not in VALID_VERDICTS:
        raise PredictionValidationError(f"verdict must be 'bet' or 'skip': {verdict!r}")

    skip_reason = payload.get("skip_reason")
    if verdict == "skip":
        if not isinstance(skip_reason, str) or not skip_reason.strip():
            raise PredictionValidationError(
                "skip_reason must be non-empty string when verdict=='skip'"
            )
    else:
        if skip_reason not in (None, ""):
            # bet なのに skip_reason が入っている → 警告レベルだが今は許容
            pass

    raw_bets = payload.get("bets", [])
    if not isinstance(raw_bets, list):
        raise PredictionValidationError("bets must be list")

    if verdict == "bet" and len(raw_bets) == 0:
        raise PredictionValidationError("bets must be non-empty when verdict=='bet'")
    if verdict == "skip" and len(raw_bets) != 0:
        raise PredictionValidationError("bets must be empty when verdict=='skip'")

    bets = [_validate_bet(b, i) for i, b in enumerate(raw_bets)]

    # 最大 5 点 (設計書 §3.2 の初期ルール)
    if len(bets) > 5:
        raise PredictionValidationError(f"bets must be at most 5 items (got {len(bets)})")

    return Prediction(
        race_id=race_id,
        predicted_at=predicted_at,
        model=model,
        analysis=analysis,
        primary_axis=list(primary_axis),
        verdict=verdict,
        skip_reason=(skip_reason if verdict == "skip" else None),
        bets=bets,
    )


def validate_file(path: Path) -> Prediction:
    """JSON ファイルを読み込んで validate."""
    with path.open(encoding="utf-8") as f:
        return validate(json.load(f))


def to_dict(p: Prediction) -> dict:
    """Prediction → dict (json.dump 用)."""
    return asdict(p)


# ---------------------------------------------------------------------------
# race_id 生成
# ---------------------------------------------------------------------------


def make_race_id(race_date: str, stadium_id: int, race_no: int) -> str:
    """race_id を生成する.

    Examples
    --------
    >>> make_race_id("2025-12-01", 1, 1)
    '2025-12-01_01_01'
    """
    return f"{race_date}_{stadium_id:02d}_{race_no:02d}"
