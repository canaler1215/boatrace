"""artifacts/predictions/<日付>/ 配下の予想 JSON を集約して index.json を生成.

P3 `/eval-predictions` で読む用. /predict スキルの最終ステップから呼ぶ.

使い方:
  py -3.12 ml/src/scripts/build_predictions_index.py 2025-12-01
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

from predict_llm.prediction_schema import (
    PredictionValidationError,
    validate_file,
)

logger = logging.getLogger("build_predictions_index")

PREDICTIONS_ROOT = Path(__file__).resolve().parents[3] / "artifacts" / "predictions"


def _parse_date(s: str) -> _dt.date:
    try:
        return _dt.date.fromisoformat(s)
    except ValueError as exc:
        raise SystemExit(f"date must be YYYY-MM-DD format: {s!r}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="予想 JSON 群を集約して index.json を生成"
    )
    parser.add_argument("date", help="対象日付 YYYY-MM-DD")
    parser.add_argument(
        "--predictions-root",
        default=str(PREDICTIONS_ROOT),
        help=f"predictions ルート (default: {PREDICTIONS_ROOT})",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="スキーマ違反を 1 件でも検出したら exit 1",
    )
    args = parser.parse_args()

    target_date = _parse_date(args.date)
    pred_dir = Path(args.predictions_root) / target_date.isoformat()
    if not pred_dir.exists():
        print(f"[build-index] predictions dir not found: {pred_dir}")
        return 1

    entries = []
    n_total = 0
    n_valid = 0
    n_bet = 0
    n_skip = 0
    invalid: list[str] = []

    for f in sorted(pred_dir.glob("*.json")):
        if f.name == "index.json":
            continue
        if f.name.endswith("_pre.json"):
            continue  # 直前情報ダンプは集約対象外
        n_total += 1
        try:
            p = validate_file(f)
        except PredictionValidationError as exc:
            invalid.append(f"{f.name}: {exc}")
            continue
        except Exception as exc:
            invalid.append(f"{f.name}: {exc}")
            continue

        n_valid += 1
        if p.verdict == "bet":
            n_bet += 1
        else:
            n_skip += 1

        entries.append({
            "file": f.name,
            "race_id": p.race_id,
            "verdict": p.verdict,
            "primary_axis": p.primary_axis,
            "n_bets": len(p.bets),
            "total_stake": sum(b.stake for b in p.bets),
            "skip_reason": p.skip_reason,
        })

    index = {
        "date": target_date.isoformat(),
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "n_total": n_total,
        "n_valid": n_valid,
        "n_invalid": len(invalid),
        "n_bet": n_bet,
        "n_skip": n_skip,
        "invalid_details": invalid,
        "predictions": entries,
    }

    out = pred_dir / "index.json"
    out.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[build-index] {target_date}: total={n_total} valid={n_valid} bet={n_bet} "
        f"skip={n_skip} invalid={len(invalid)} -> {out}"
    )
    if invalid:
        print("[build-index] invalid files:")
        for line in invalid:
            print(f"  - {line}")

    if args.strict and invalid:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
