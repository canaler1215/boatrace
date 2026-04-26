"""Evaluate Claude (LLM) predictions against actual race results (P3).

設計書 LLM_PREDICT_DESIGN.md §3.3 / P3 合意ポイント に準拠.

過去日:
  - 着順: K ファイル parse_result_file で finish_position を引く
  - 払戻: data/odds/odds_YYYYMM.parquet の actual_combo オッズ × stake

当日:
  - fetch_race_result_full で着順 + 払戻金を取得 (payout / 100 = actual_odds)

引数:
  evaluate_predictions.py <YYYY-MM-DD>            # その日の全予想
  evaluate_predictions.py <YYYY-MM-DD> <会場>      # 1 会場のみ

出力:
  artifacts/eval/<YYYY-MM-DD>.json            (場フィルタなし)
  artifacts/eval/<YYYY-MM-DD>_<NN>.json       (場フィルタあり)

集計:
  - 全体 ROI / 的中率 (per bet, per race) / 見送り率 / 平均 confidence
  - 場別 ROI
  - confidence 帯別 ROI ([0.0-0.3, 0.3-0.5, 0.5-0.7, 0.7-1.0])
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "ml" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from collector.history_downloader import (  # noqa: E402
    DATA_DIR as _HISTORY_DIR,
    download_day_data,
    extract_lzh,
    parse_result_file,
)
from collector.odds_downloader import _cache_path as _odds_cache_path  # noqa: E402
from collector.openapi_client import fetch_race_result_full  # noqa: E402
from predict_llm.prediction_schema import (  # noqa: E402
    Prediction,
    PredictionValidationError,
    validate_file,
)
from predict_llm.stadium_resolver import (  # noqa: E402
    name_of,
    resolve as resolve_stadium,
)

logger = logging.getLogger("eval_predictions")

PREDICTIONS_DIR = ROOT / "artifacts" / "predictions"
EVAL_DIR = ROOT / "artifacts" / "eval"

CONF_BANDS: tuple[tuple[str, float, float], ...] = (
    ("0.0-0.3", 0.0, 0.3),
    ("0.3-0.5", 0.3, 0.5),
    ("0.5-0.7", 0.5, 0.7),
    ("0.7-1.0", 0.7, 1.000001),
)

JST = _dt.timezone(_dt.timedelta(hours=9))

_FILE_RE = re.compile(r"^(\d{2})_(\d{2})\.json$")


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------


@dataclass
class BetEval:
    trifecta: str
    stake: int
    current_odds: float                 # Claude が JSON に書いたオッズ
    actual_odds: float | None           # parquet (過去日) または raceresult (当日)
    confidence: float
    expected_prob: float
    is_hit: bool
    payout: float
    payout_source: str                  # "actual" | "fallback_current_odds" | "miss"
    odds_drift_pct: float | None        # (current_odds - actual_odds) / actual_odds


@dataclass
class RaceEval:
    race_id: str                        # P2 形式 "YYYY-MM-DD_NN_RR"
    stadium_id: int
    race_no: int
    status: str                         # "settled" | "skipped_by_claude" | "no_result"
    verdict: str                        # "bet" | "skip"
    skip_reason: str | None
    primary_axis: list[int]
    actual_combination: str | None
    bets: list[BetEval]
    total_stake: int
    total_payout: float
    note: str | None


@dataclass
class StadiumStat:
    stadium_id: int
    name: str
    n_races: int
    n_bets: int
    n_hits: int
    total_stake: int
    total_payout: float
    roi: float


@dataclass
class ConfBandStat:
    band: str
    n_bets: int
    n_hits: int
    total_stake: int
    total_payout: float
    roi: float


@dataclass
class Summary:
    n_races: int
    n_settled: int
    n_skipped_by_claude: int
    n_no_result: int
    n_bet_races: int
    n_hit_races: int
    n_bets: int
    n_hits: int
    total_stake: int
    total_payout: float
    roi: float
    hit_rate_per_bet: float
    hit_rate_per_race: float
    skip_rate: float
    avg_confidence: float
    by_stadium: list[StadiumStat]
    by_confidence_band: list[ConfBandStat]


# ---------------------------------------------------------------------------
# 結果取得 (過去日 / 当日)
# ---------------------------------------------------------------------------


def _kfile_finish_map(date: _dt.date) -> dict[str, dict[int, int]]:
    """K ファイルから race_id (12 桁) → {boat_no: finish_position} を返す.

    ファイルが無ければ download_day_data で自動 DL を試行.
    """
    yy = date.year % 100
    lzh_name = f"k{yy:02d}{date.month:02d}{date.day:02d}.lzh"
    lzh = _HISTORY_DIR / lzh_name

    if not lzh.exists():
        logger.info("K ファイルなし、DL を試行: %s", lzh_name)
        try:
            lzh_dl = download_day_data(date.year, date.month, date.day, dest_dir=_HISTORY_DIR)
        except Exception as exc:
            logger.warning("K ファイル DL 失敗: %s", exc)
            return {}
        if lzh_dl is None or not lzh_dl.exists():
            logger.warning("K ファイル DL 結果なし: %s", date)
            return {}
        lzh = lzh_dl

    tmpdir = Path(tempfile.mkdtemp(prefix="boatrace_eval_k_"))
    out: dict[str, dict[int, int]] = {}
    try:
        files = extract_lzh(lzh, tmpdir / lzh.stem)
        for f in files:
            for rec in parse_result_file(f):
                rid = rec["race_id"]
                bn = rec["boat_no"]
                fp = rec["finish_position"]
                if fp is None:
                    continue
                out.setdefault(rid, {})[bn] = fp
    except Exception as exc:
        logger.warning("K ファイル parse 失敗: %s", exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    logger.info("K ファイル読み込み: %d races (%s)", len(out), lzh.name)
    return out


def _odds_map_for_month(year: int, month: int) -> dict[str, dict[str, float]]:
    """parquet キャッシュから race_id → {combination: odds} を返す."""
    p = _odds_cache_path(year, month)
    if not p.exists():
        logger.warning("3 連単オッズ parquet なし: %s", p)
        return {}
    try:
        df = pd.read_parquet(p)
        out: dict[str, dict[str, float]] = {}
        for race_id, g in df.groupby("race_id", sort=False):
            out[str(race_id)] = dict(zip(g["combination"], g["odds"].astype(float)))
        logger.info("オッズ parquet 読み込み: %d races (%s)", len(out), p.name)
        return out
    except Exception as exc:
        logger.warning("parquet 読み込み失敗 (%s): %s", p, exc)
        return {}


def _finish_to_combo(finish: dict[int, int]) -> str | None:
    """{boat_no: finish_position} → '1-2-3' 形式. 1〜3 着が揃わなければ None."""
    inv: dict[int, int] = {}
    for bn, pos in finish.items():
        if pos in (1, 2, 3):
            inv[pos] = bn
    if {1, 2, 3}.issubset(inv.keys()):
        return f"{inv[1]}-{inv[2]}-{inv[3]}"
    return None


def _make_kfile_race_id(stadium_id: int, date: _dt.date, race_no: int) -> str:
    """K ファイル / parquet の race_id 形式 (12 桁) を生成."""
    return f"{stadium_id:02d}{date.strftime('%Y%m%d')}{race_no:02d}"


# ---------------------------------------------------------------------------
# 1 レース評価
# ---------------------------------------------------------------------------


def _evaluate_race(
    pred: Prediction,
    stadium_id: int,
    race_no: int,
    date: _dt.date,
    finish_map: dict[str, dict[int, int]],
    odds_map: dict[str, dict[str, float]],
    is_past: bool,
) -> RaceEval:
    """1 レース分の RaceEval を返す."""
    if pred.verdict == "skip":
        return RaceEval(
            race_id=pred.race_id,
            stadium_id=stadium_id,
            race_no=race_no,
            status="skipped_by_claude",
            verdict="skip",
            skip_reason=pred.skip_reason,
            primary_axis=list(pred.primary_axis),
            actual_combination=None,
            bets=[],
            total_stake=0,
            total_payout=0.0,
            note=None,
        )

    kfile_rid = _make_kfile_race_id(stadium_id, date, race_no)
    actual_combo: str | None = None
    actual_combo_odds: float | None = None
    note: str | None = None

    if is_past:
        finish = finish_map.get(kfile_rid, {})
        actual_combo = _finish_to_combo(finish) if finish else None
        if actual_combo is None:
            note = f"K ファイルに {kfile_rid} の着順データなし (休場/欠番)"
    else:
        try:
            r = fetch_race_result_full(stadium_id, date.isoformat(), race_no)
            actual_combo = r.get("trifecta_combination")
            payout_yen = r.get("trifecta_payout")
            if payout_yen is not None:
                actual_combo_odds = float(payout_yen) / 100.0
        except Exception as exc:
            note = f"raceresult 取得失敗: {exc}"

    if actual_combo is None:
        return RaceEval(
            race_id=pred.race_id,
            stadium_id=stadium_id,
            race_no=race_no,
            status="no_result",
            verdict=pred.verdict,
            skip_reason=pred.skip_reason,
            primary_axis=list(pred.primary_axis),
            actual_combination=None,
            bets=[],
            total_stake=0,
            total_payout=0.0,
            note=note,
        )

    if is_past and actual_combo_odds is None:
        actual_combo_odds = odds_map.get(kfile_rid, {}).get(actual_combo)

    bet_evals: list[BetEval] = []
    total_stake = 0
    total_payout = 0.0

    for bet in pred.bets:
        is_hit = bet.trifecta == actual_combo

        if is_past:
            bet_actual_odds = odds_map.get(kfile_rid, {}).get(bet.trifecta)
        else:
            bet_actual_odds = actual_combo_odds if is_hit else None

        if is_hit:
            if bet_actual_odds is not None:
                payout = bet.stake * bet_actual_odds
                payout_source = "actual"
            else:
                payout = bet.stake * bet.current_odds
                payout_source = "fallback_current_odds"
        else:
            payout = 0.0
            payout_source = "miss"

        odds_drift: float | None = None
        if bet_actual_odds is not None and bet_actual_odds > 0:
            odds_drift = (bet.current_odds - bet_actual_odds) / bet_actual_odds

        bet_evals.append(BetEval(
            trifecta=bet.trifecta,
            stake=bet.stake,
            current_odds=bet.current_odds,
            actual_odds=bet_actual_odds,
            confidence=bet.confidence,
            expected_prob=bet.expected_prob,
            is_hit=is_hit,
            payout=payout,
            payout_source=payout_source,
            odds_drift_pct=odds_drift,
        ))
        total_stake += bet.stake
        total_payout += payout

    return RaceEval(
        race_id=pred.race_id,
        stadium_id=stadium_id,
        race_no=race_no,
        status="settled",
        verdict="bet",
        skip_reason=None,
        primary_axis=list(pred.primary_axis),
        actual_combination=actual_combo,
        bets=bet_evals,
        total_stake=total_stake,
        total_payout=total_payout,
        note=note,
    )


# ---------------------------------------------------------------------------
# 集計
# ---------------------------------------------------------------------------


def _build_summary(races: list[RaceEval]) -> Summary:
    n_races = len(races)
    n_settled = sum(1 for r in races if r.status == "settled")
    n_skipped = sum(1 for r in races if r.status == "skipped_by_claude")
    n_no_result = sum(1 for r in races if r.status == "no_result")

    settled_bet = [r for r in races if r.status == "settled" and r.verdict == "bet"]
    n_bet_races = len(settled_bet)
    n_hit_races = sum(1 for r in settled_bet if any(b.is_hit for b in r.bets))

    all_bets: list[BetEval] = [b for r in settled_bet for b in r.bets]
    n_bets = len(all_bets)
    n_hits = sum(1 for b in all_bets if b.is_hit)
    total_stake = sum(b.stake for b in all_bets)
    total_payout = sum(b.payout for b in all_bets)
    roi = (total_payout / total_stake - 1.0) if total_stake > 0 else 0.0

    confidences = [b.confidence for b in all_bets]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

    # 場別
    by_sid: dict[int, dict] = defaultdict(lambda: {
        "race_ids": set(), "n_bets": 0, "n_hits": 0, "stake": 0, "payout": 0.0,
    })
    for r in settled_bet:
        agg = by_sid[r.stadium_id]
        agg["race_ids"].add(r.race_id)
        for b in r.bets:
            agg["n_bets"] += 1
            agg["n_hits"] += int(b.is_hit)
            agg["stake"] += b.stake
            agg["payout"] += b.payout
    by_stadium = [
        StadiumStat(
            stadium_id=sid,
            name=name_of(sid),
            n_races=len(agg["race_ids"]),
            n_bets=agg["n_bets"],
            n_hits=agg["n_hits"],
            total_stake=agg["stake"],
            total_payout=agg["payout"],
            roi=(agg["payout"] / agg["stake"] - 1.0) if agg["stake"] > 0 else 0.0,
        )
        for sid, agg in sorted(by_sid.items())
    ]

    # confidence 帯別
    by_band: list[ConfBandStat] = []
    for label, lo, hi in CONF_BANDS:
        bs = [b for b in all_bets if lo <= b.confidence < hi]
        s = sum(b.stake for b in bs)
        p = sum(b.payout for b in bs)
        by_band.append(ConfBandStat(
            band=label,
            n_bets=len(bs),
            n_hits=sum(1 for b in bs if b.is_hit),
            total_stake=s,
            total_payout=p,
            roi=(p / s - 1.0) if s > 0 else 0.0,
        ))

    n_decided = n_bet_races + n_skipped
    skip_rate = (n_skipped / n_decided) if n_decided > 0 else 0.0

    return Summary(
        n_races=n_races,
        n_settled=n_settled,
        n_skipped_by_claude=n_skipped,
        n_no_result=n_no_result,
        n_bet_races=n_bet_races,
        n_hit_races=n_hit_races,
        n_bets=n_bets,
        n_hits=n_hits,
        total_stake=total_stake,
        total_payout=total_payout,
        roi=roi,
        hit_rate_per_bet=(n_hits / n_bets) if n_bets > 0 else 0.0,
        hit_rate_per_race=(n_hit_races / n_bet_races) if n_bet_races > 0 else 0.0,
        skip_rate=skip_rate,
        avg_confidence=avg_conf,
        by_stadium=by_stadium,
        by_confidence_band=by_band,
    )


# ---------------------------------------------------------------------------
# ターミナル出力
# ---------------------------------------------------------------------------


def _render_terminal(
    date_str: str,
    stadium_filter: int | None,
    summary: Summary,
    races: list[RaceEval],
) -> str:
    sf = f" / 場フィルタ {name_of(stadium_filter)}" if stadium_filter else ""
    lines: list[str] = []
    lines.append(f"=== /eval-predictions {date_str}{sf} ===")
    lines.append(
        f"races: {summary.n_races} (settled={summary.n_settled}, "
        f"skipped_by_claude={summary.n_skipped_by_claude}, no_result={summary.n_no_result})"
    )
    lines.append(f"bet races: {summary.n_bet_races} / hit races: {summary.n_hit_races}")
    lines.append(f"bets: {summary.n_bets} / hits: {summary.n_hits}")
    lines.append(f"stake: {summary.total_stake:,}円 / payout: {summary.total_payout:,.0f}円")
    lines.append(
        f"ROI: {summary.roi:+.1%}  hit_rate/bet: {summary.hit_rate_per_bet:.2%}  "
        f"hit_rate/race: {summary.hit_rate_per_race:.2%}"
    )
    lines.append(
        f"skip_rate: {summary.skip_rate:.1%}  avg_confidence: {summary.avg_confidence:.2f}"
    )
    lines.append("")

    if summary.by_stadium:
        lines.append("[場別]")
        lines.append(
            f"{'場':<8} {'races':>5} {'bets':>5} {'hits':>4} "
            f"{'stake':>10} {'payout':>12} {'ROI':>8}"
        )
        for st in summary.by_stadium:
            lines.append(
                f"{st.name:<8} {st.n_races:>5} {st.n_bets:>5} {st.n_hits:>4} "
                f"{st.total_stake:>10,} {st.total_payout:>12,.0f} {st.roi:>+7.1%}"
            )
        lines.append("")

    if summary.by_confidence_band:
        lines.append("[Confidence 帯別]")
        lines.append(
            f"{'band':<10} {'bets':>5} {'hits':>4} "
            f"{'stake':>10} {'payout':>12} {'ROI':>8}"
        )
        for b in summary.by_confidence_band:
            lines.append(
                f"{b.band:<10} {b.n_bets:>5} {b.n_hits:>4} "
                f"{b.total_stake:>10,} {b.total_payout:>12,.0f} {b.roi:>+7.1%}"
            )
        lines.append("")

    hits = [r for r in races if r.status == "settled" and any(b.is_hit for b in r.bets)]
    if hits:
        lines.append(f"[的中レース] (n={len(hits)})")
        for r in hits[:10]:
            for b in r.bets:
                if b.is_hit:
                    odds_disp = b.actual_odds if b.actual_odds is not None else b.current_odds
                    lines.append(
                        f"  {name_of(r.stadium_id)} {r.race_no:>2}R  {b.trifecta}  "
                        f"odds {odds_disp:.1f}x  stake {b.stake}円 → "
                        f"payout {b.payout:,.0f}円  conf {b.confidence:.2f}"
                    )
        if len(hits) > 10:
            lines.append(f"  ... 他 {len(hits) - 10} レース")

    if summary.n_no_result > 0:
        lines.append("")
        lines.append(f"⚠ no_result: {summary.n_no_result} レース (実績取得不能)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI エントリポイント
# ---------------------------------------------------------------------------


def evaluate(date_str: str, stadium_filter: int | None = None) -> tuple[dict, str]:
    """1 日分の評価を実行. 戻り値は (出力 dict, ターミナル文字列)."""
    date = _dt.date.fromisoformat(date_str)
    is_past = date < _dt.date.today()

    pred_dir = PREDICTIONS_DIR / date_str
    if not pred_dir.exists():
        raise FileNotFoundError(
            f"予想ディレクトリが見つからない: {pred_dir} (先に /predict を実行)"
        )

    targets: list[tuple[Path, Prediction, int, int]] = []
    invalid: list[tuple[Path, str]] = []
    for f in sorted(pred_dir.glob("*.json")):
        if f.name == "index.json" or f.name.endswith("_pre.json"):
            continue
        m = _FILE_RE.match(f.name)
        if not m:
            continue
        sid = int(m.group(1))
        rno = int(m.group(2))
        if stadium_filter is not None and sid != stadium_filter:
            continue
        try:
            pred = validate_file(f)
            targets.append((f, pred, sid, rno))
        except PredictionValidationError as exc:
            invalid.append((f, str(exc)))
            logger.warning("invalid prediction: %s (%s)", f.name, exc)

    if not targets:
        raise RuntimeError(
            f"対象 prediction ファイルがない (dir={pred_dir}, filter={stadium_filter})"
        )

    finish_map: dict[str, dict[int, int]] = {}
    odds_map: dict[str, dict[str, float]] = {}
    if is_past:
        finish_map = _kfile_finish_map(date)
        odds_map = _odds_map_for_month(date.year, date.month)

    races: list[RaceEval] = []
    consec_fail = 0
    for path, pred, sid, rno in targets:
        race_eval = _evaluate_race(pred, sid, rno, date, finish_map, odds_map, is_past)
        races.append(race_eval)
        if race_eval.status == "no_result":
            consec_fail += 1
            if consec_fail == 5:
                logger.warning(
                    "⚠ 連続 5 レースで実績取得失敗。実装に問題ある可能性 (path=%s)",
                    path.name,
                )
        else:
            consec_fail = 0

    summary = _build_summary(races)

    out = {
        "date": date_str,
        "stadium_filter": stadium_filter,
        "stadium_filter_name": name_of(stadium_filter) if stadium_filter else None,
        "evaluated_at": _dt.datetime.now(JST).isoformat(timespec="seconds"),
        "is_past": is_past,
        "summary": asdict(summary),
        "races": [asdict(r) for r in races],
        "invalid_predictions": [{"file": p.name, "error": e} for p, e in invalid],
    }

    term = _render_terminal(date_str, stadium_filter, summary, races)
    return out, term


def _save(out: dict, date_str: str, stadium_filter: int | None) -> Path:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    if stadium_filter is None:
        path = EVAL_DIR / f"{date_str}.json"
    else:
        path = EVAL_DIR / f"{date_str}_{stadium_filter:02d}.json"
    path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

    p = argparse.ArgumentParser(
        description="予想 JSON と実績を突合して ROI を算出 (P3)",
    )
    p.add_argument("date", help="YYYY-MM-DD")
    p.add_argument(
        "stadium",
        nargs="?",
        default=None,
        help="場名 (漢字/ひらがな/数字, 省略時は全場)",
    )
    p.add_argument("--quiet", action="store_true", help="ターミナル表示を省略")
    args = p.parse_args(argv)

    sid: int | None = None
    if args.stadium:
        try:
            sid = resolve_stadium(args.stadium)
        except Exception as exc:
            print(f"[eval] 場名解決失敗: {args.stadium!r} ({exc})", file=sys.stderr)
            return 2

    try:
        out, term = evaluate(args.date, sid)
    except FileNotFoundError as exc:
        print(f"[eval] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        logger.exception("evaluate failed")
        print(f"[eval] エラー: {exc}", file=sys.stderr)
        return 1

    out_path = _save(out, args.date, sid)
    if not args.quiet:
        print(term)
    print(f"\n[eval] saved: {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
