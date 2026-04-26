"""Aggregate per-day eval JSONs into a period summary (P3.5).

設計書 LLM_PREDICT_DESIGN.md §3.3 「累積評価」 + 着手前合意ポイント 1〜10 に準拠.

入力:
  artifacts/eval/<YYYY-MM-DD>.json  (場フィルタなし版のみ採用)

出力:
  artifacts/eval/summary_<from>_<to>.json
  ターミナル: 月次 + 場別 + confidence 帯別 + 判定ステータス

引数:
  eval_summary.py --from <YYYY-MM-DD> --to <YYYY-MM-DD>
  eval_summary.py --month <YYYY-MM>             # 糖衣構文

判定ステータス:
  ✓ production_ready : ROI ≥ +10% かつ worst_month > -50% かつ bootstrap_ci_lower ≥ 0
  △ breakeven        : ROI ≥ 0% かつ worst_month > -50%
  ✗ fail             : 上記以外
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "ml" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from predict_llm.stadium_resolver import name_of  # noqa: E402

logger = logging.getLogger("eval_summary")

EVAL_DIR = ROOT / "artifacts" / "eval"
JST = _dt.timezone(_dt.timedelta(hours=9))

# P3 evaluate_predictions.py と完全一致 (lo ≤ x < hi)
CONF_BANDS: tuple[tuple[str, float, float], ...] = (
    ("0.0-0.3", 0.0, 0.3),
    ("0.3-0.5", 0.3, 0.5),
    ("0.5-0.7", 0.5, 0.7),
    ("0.7-1.0", 0.7, 1.000001),
)

# <YYYY-MM-DD>.json 専用. <YYYY-MM-DD>_<NN>.json (場フィルタ付き) は除外
DAY_FILE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.json$")


# ---------------------------------------------------------------------------
# 引数処理
# ---------------------------------------------------------------------------


def _expand_month(month_str: str) -> tuple[str, str]:
    """YYYY-MM を (YYYY-MM-01, YYYY-MM-末日) に展開."""
    y, m = (int(x) for x in month_str.split("-"))
    first = _dt.date(y, m, 1)
    if m == 12:
        last = _dt.date(y + 1, 1, 1) - _dt.timedelta(days=1)
    else:
        last = _dt.date(y, m + 1, 1) - _dt.timedelta(days=1)
    return first.isoformat(), last.isoformat()


def _date_range(from_str: str, to_str: str) -> list[_dt.date]:
    f = _dt.date.fromisoformat(from_str)
    t = _dt.date.fromisoformat(to_str)
    if f > t:
        raise ValueError(f"--from ({from_str}) > --to ({to_str})")
    out: list[_dt.date] = []
    cur = f
    while cur <= t:
        out.append(cur)
        cur += _dt.timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# 入力ロード
# ---------------------------------------------------------------------------


def _load_day(date: _dt.date, eval_dir: Path) -> dict | None:
    p = eval_dir / f"{date.isoformat()}.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("eval JSON 読み込み失敗 (%s): %s", p.name, exc)
        return None
    if "summary" not in d or "races" not in d:
        logger.warning("スキーマ違反 (%s): summary/races なし → skip", p.name)
        return None
    return d


# ---------------------------------------------------------------------------
# 集計
# ---------------------------------------------------------------------------


def _empty_month_agg(month: str) -> dict:
    return {
        "month": month,
        "n_days": 0,
        "n_races": 0,
        "n_bet_races": 0,
        "n_hit_races": 0,
        "n_bets": 0,
        "n_hits": 0,
        "total_stake": 0,
        "total_payout": 0.0,
    }


def _empty_stadium_agg(sid: int) -> dict:
    return {
        "stadium_id": sid,
        "name": name_of(sid),
        "n_races": 0,
        "n_bets": 0,
        "n_hits": 0,
        "total_stake": 0,
        "total_payout": 0.0,
    }


def _empty_band_agg(label: str) -> dict:
    return {
        "band": label,
        "n_bets": 0,
        "n_hits": 0,
        "total_stake": 0,
        "total_payout": 0.0,
    }


def _aggregate(daily: list[dict]) -> dict:
    """日次 JSON のリストを期間集計に畳み込む.

    P3 evaluate_predictions の `_build_summary` の出力を信頼し、
    summary フィールドの数値を合算する設計（races[] からの再計算はしない）。
    """
    total = {
        "n_races": 0,
        "n_settled": 0,
        "n_skipped_by_claude": 0,
        "n_no_result": 0,
        "n_bet_races": 0,
        "n_hit_races": 0,
        "n_bets": 0,
        "n_hits": 0,
        "total_stake": 0,
        "total_payout": 0.0,
        "conf_weighted_sum": 0.0,  # avg_confidence × n_bets を合算
    }
    by_month: dict[str, dict] = {}
    by_stadium: dict[int, dict] = {}
    by_stadium_month: dict[tuple[int, str], dict] = {}
    by_band: dict[str, dict] = {}

    daily_stats: list[dict] = []
    flat_bets: list[tuple[int, float]] = []

    for d in daily:
        date = d["date"]
        month = date[:7]
        s = d["summary"]

        # ── 全体 ──────────────────────────────────────────────────
        for k in (
            "n_races",
            "n_settled",
            "n_skipped_by_claude",
            "n_no_result",
            "n_bet_races",
            "n_hit_races",
            "n_bets",
            "n_hits",
            "total_stake",
        ):
            total[k] += int(s.get(k, 0))
        total["total_payout"] += float(s.get("total_payout", 0.0))
        total["conf_weighted_sum"] += float(s.get("avg_confidence", 0.0)) * int(s.get("n_bets", 0))

        # ── 月次 ──────────────────────────────────────────────────
        ma = by_month.setdefault(month, _empty_month_agg(month))
        ma["n_days"] += 1
        for k in ("n_races", "n_bet_races", "n_hit_races", "n_bets", "n_hits", "total_stake"):
            ma[k] += int(s.get(k, 0))
        ma["total_payout"] += float(s.get("total_payout", 0.0))

        # ── 場別 (累積) ──────────────────────────────────────────
        for st in s.get("by_stadium", []):
            sid = int(st["stadium_id"])
            sa = by_stadium.setdefault(sid, _empty_stadium_agg(sid))
            for k in ("n_races", "n_bets", "n_hits", "total_stake"):
                sa[k] += int(st.get(k, 0))
            sa["total_payout"] += float(st.get("total_payout", 0.0))

            key = (sid, month)
            sma = by_stadium_month.setdefault(key, {**_empty_stadium_agg(sid), "month": month})
            for k in ("n_races", "n_bets", "n_hits", "total_stake"):
                sma[k] += int(st.get(k, 0))
            sma["total_payout"] += float(st.get("total_payout", 0.0))

        # ── confidence 帯別 ─────────────────────────────────────
        for cb in s.get("by_confidence_band", []):
            label = cb["band"]
            ba = by_band.setdefault(label, _empty_band_agg(label))
            for k in ("n_bets", "n_hits", "total_stake"):
                ba[k] += int(cb.get(k, 0))
            ba["total_payout"] += float(cb.get("total_payout", 0.0))

        # ── 日次 ROI 統計用 ─────────────────────────────────────
        ds_stake = int(s.get("total_stake", 0))
        ds_payout = float(s.get("total_payout", 0.0))
        if ds_stake > 0:
            roi = ds_payout / ds_stake - 1.0
            daily_stats.append({"date": date, "stake": ds_stake, "payout": ds_payout, "roi": roi})

        # ── bootstrap 用 flat_bets ──────────────────────────────
        for r in d.get("races", []):
            if r.get("status") != "settled" or r.get("verdict") != "bet":
                continue
            for b in r.get("bets", []):
                flat_bets.append((int(b.get("stake", 0)), float(b.get("payout", 0.0))))

    return {
        "total": total,
        "by_month": by_month,
        "by_stadium": by_stadium,
        "by_stadium_month": by_stadium_month,
        "by_band": by_band,
        "daily_stats": daily_stats,
        "flat_bets": flat_bets,
    }


def _finalize_total(total: dict) -> dict:
    nb = total["n_bets"]
    nbr = total["n_bet_races"]
    nd = nbr + total["n_skipped_by_claude"]
    s = total["total_stake"]
    p = total["total_payout"]
    return {
        "n_races": total["n_races"],
        "n_settled": total["n_settled"],
        "n_skipped_by_claude": total["n_skipped_by_claude"],
        "n_no_result": total["n_no_result"],
        "n_bet_races": nbr,
        "n_hit_races": total["n_hit_races"],
        "n_bets": nb,
        "n_hits": total["n_hits"],
        "total_stake": s,
        "total_payout": p,
        "roi": (p / s - 1.0) if s > 0 else 0.0,
        "hit_rate_per_bet": (total["n_hits"] / nb) if nb > 0 else 0.0,
        "hit_rate_per_race": (total["n_hit_races"] / nbr) if nbr > 0 else 0.0,
        "skip_rate": (total["n_skipped_by_claude"] / nd) if nd > 0 else 0.0,
        "avg_confidence": (total["conf_weighted_sum"] / nb) if nb > 0 else 0.0,
    }


def _finalize_month(ma: dict) -> dict:
    s = ma["total_stake"]
    p = ma["total_payout"]
    nb = ma["n_bets"]
    nbr = ma["n_bet_races"]
    return {
        "month": ma["month"],
        "n_days": ma["n_days"],
        "n_races": ma["n_races"],
        "n_bet_races": nbr,
        "n_hit_races": ma["n_hit_races"],
        "n_bets": nb,
        "n_hits": ma["n_hits"],
        "total_stake": s,
        "total_payout": p,
        "roi": (p / s - 1.0) if s > 0 else 0.0,
        "hit_rate_per_bet": (ma["n_hits"] / nb) if nb > 0 else 0.0,
        "hit_rate_per_race": (ma["n_hit_races"] / nbr) if nbr > 0 else 0.0,
    }


def _finalize_stadium(sa: dict) -> dict:
    s = sa["total_stake"]
    p = sa["total_payout"]
    out = {
        "stadium_id": sa["stadium_id"],
        "name": sa["name"],
        "n_races": sa["n_races"],
        "n_bets": sa["n_bets"],
        "n_hits": sa["n_hits"],
        "total_stake": s,
        "total_payout": p,
        "roi": (p / s - 1.0) if s > 0 else 0.0,
    }
    if "month" in sa:
        out["month"] = sa["month"]
    return out


def _finalize_band(ba: dict) -> dict:
    s = ba["total_stake"]
    p = ba["total_payout"]
    return {
        "band": ba["band"],
        "n_bets": ba["n_bets"],
        "n_hits": ba["n_hits"],
        "total_stake": s,
        "total_payout": p,
        "roi": (p / s - 1.0) if s > 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# bootstrap CI
# ---------------------------------------------------------------------------


def _bootstrap_roi_ci(
    flat_bets: list[tuple[int, float]],
    n: int = 1000,
    seed: int = 42,
) -> dict | None:
    """bet 単位リサンプルで ROI の 95% CI を返す.

    bet が空なら None.
    """
    if not flat_bets:
        return None
    rng = random.Random(seed)
    nb = len(flat_bets)
    rois: list[float] = []
    for _ in range(n):
        s = 0
        p = 0.0
        for _i in range(nb):
            stk, pay = flat_bets[rng.randrange(nb)]
            s += stk
            p += pay
        rois.append((p / s - 1.0) if s > 0 else 0.0)
    rois.sort()
    lo = rois[int(0.025 * n)]
    hi = rois[min(int(0.975 * n), n - 1)]
    return {"n": n, "lower": lo, "upper": hi}


# ---------------------------------------------------------------------------
# 統計値 (min/median/mean/max/stddev)
# ---------------------------------------------------------------------------


def _stats(values: list[float]) -> dict | None:
    if not values:
        return None
    vs = sorted(values)
    n = len(vs)
    mn = vs[0]
    mx = vs[-1]
    md = vs[n // 2] if n % 2 == 1 else (vs[n // 2 - 1] + vs[n // 2]) / 2
    avg = sum(vs) / n
    if n >= 2:
        var = sum((v - avg) ** 2 for v in vs) / (n - 1)
        sd = var ** 0.5
    else:
        sd = 0.0
    return {"min": mn, "median": md, "mean": avg, "max": mx, "stddev": sd, "n": n}


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------


def _verdict(
    roi: float,
    worst_month_roi: float | None,
    ci_lower: float | None,
) -> dict:
    worst_ok = worst_month_roi is None or worst_month_roi > -0.50
    ci_ok = ci_lower is not None and ci_lower >= 0.0
    if roi >= 0.10 and worst_ok and ci_ok:
        status = "production_ready"
        label = "✓ 実運用再開条件達成"
    elif roi >= 0.0 and worst_ok:
        status = "breakeven"
        label = "△ トントン以上"
    else:
        status = "fail"
        label = "✗ 未達"
    return {
        "status": status,
        "label": label,
        "roi": roi,
        "worst_month_roi": worst_month_roi,
        "bootstrap_ci_lower": ci_lower,
        "criteria": {
            "production_ready": "ROI ≥ +10% かつ worst_month > -50% かつ bootstrap_ci_lower ≥ 0",
            "breakeven": "ROI ≥ 0% かつ worst_month > -50%",
            "fail": "上記以外",
        },
        "note": "判定は参考値。後付けフィルタで合わせ込んではならない（フェーズ 3〜6 の教訓）",
    }


# ---------------------------------------------------------------------------
# 出力 dict 構築
# ---------------------------------------------------------------------------


def summarize(
    from_str: str,
    to_str: str,
    eval_dir: Path = EVAL_DIR,
    bootstrap_n: int = 1000,
    bootstrap_seed: int = 42,
    do_bootstrap: bool = True,
) -> tuple[dict, str]:
    """期間集計を実行. 戻り値は (出力 dict, ターミナル文字列)."""
    dates = _date_range(from_str, to_str)

    daily: list[dict] = []
    missing: list[str] = []
    input_files: list[str] = []
    for d in dates:
        loaded = _load_day(d, eval_dir)
        if loaded is None:
            missing.append(d.isoformat())
        else:
            daily.append(loaded)
            input_files.append(f"{d.isoformat()}.json")

    if not daily:
        raise FileNotFoundError(
            f"期間内に <日付>.json が 1 件も無い (from={from_str}, to={to_str}, dir={eval_dir})"
        )

    agg = _aggregate(daily)

    summary = _finalize_total(agg["total"])
    by_month = sorted(
        (_finalize_month(m) for m in agg["by_month"].values()),
        key=lambda x: x["month"],
    )
    by_stadium = sorted(
        (_finalize_stadium(s) for s in agg["by_stadium"].values()),
        key=lambda x: x["stadium_id"],
    )
    by_stadium_month = sorted(
        (_finalize_stadium(s) for s in agg["by_stadium_month"].values()),
        key=lambda x: (x["stadium_id"], x["month"]),
    )
    by_band = [_finalize_band(agg["by_band"][label]) for label, _, _ in CONF_BANDS
               if label in agg["by_band"]]

    daily_stats = agg["daily_stats"]
    daily_roi_stats = _stats([ds["roi"] for ds in daily_stats])
    if daily_roi_stats and daily_stats:
        worst = min(daily_stats, key=lambda x: x["roi"])
        best = max(daily_stats, key=lambda x: x["roi"])
        daily_roi_stats["worst_day"] = worst["date"]
        daily_roi_stats["best_day"] = best["date"]

    monthly_roi_values = [m["roi"] for m in by_month if m["total_stake"] > 0]
    monthly_roi_stats = _stats(monthly_roi_values)
    worst_month_roi: float | None = None
    if monthly_roi_stats and by_month:
        with_stake = [m for m in by_month if m["total_stake"] > 0]
        worst_m = min(with_stake, key=lambda x: x["roi"])
        best_m = max(with_stake, key=lambda x: x["roi"])
        monthly_roi_stats["worst_month"] = worst_m["month"]
        monthly_roi_stats["best_month"] = best_m["month"]
        worst_month_roi = worst_m["roi"]

    ci: dict | None = None
    if do_bootstrap:
        ci = _bootstrap_roi_ci(agg["flat_bets"], n=bootstrap_n, seed=bootstrap_seed)
    summary["bootstrap_ci"] = ci

    verdict = _verdict(
        summary["roi"],
        worst_month_roi,
        ci["lower"] if ci else None,
    )

    warnings: list[str] = []
    if missing:
        warnings.append(f"期間内 {len(missing)} 日分の <日付>.json が見つからない（取得済みのみで集計）")
    if summary["n_bet_races"] < 30:
        warnings.append(f"n_bet_races={summary['n_bet_races']} < 30: 統計的信頼性低い、N≥100 を推奨")
    if len(daily) < 5:
        warnings.append(f"累積評価 N={len(daily)} 日（推奨 30 日以上）— P3.5 完了判定には早期")

    out = {
        "from": from_str,
        "to": to_str,
        "evaluated_at": _dt.datetime.now(JST).isoformat(timespec="seconds"),
        "n_days": len(dates),
        "n_days_with_data": len(daily),
        "n_days_missing": len(missing),
        "missing_dates": missing,
        "input_files": input_files,
        "summary": summary,
        "by_month": by_month,
        "by_stadium": by_stadium,
        "by_stadium_month": by_stadium_month,
        "by_confidence_band": by_band,
        "daily_roi_stats": daily_roi_stats,
        "monthly_roi_stats": monthly_roi_stats,
        "verdict": verdict,
        "warnings": warnings,
    }

    term = _render_terminal(out)
    return out, term


# ---------------------------------------------------------------------------
# ターミナル表示
# ---------------------------------------------------------------------------


def _fmt_pct(x: float | None, width: int = 8, plus: bool = True) -> str:
    if x is None:
        return f"{'—':>{width}}"
    fmt = f"{{:>+{width-1}.1%}}" if plus else f"{{:>{width}.1%}}"
    return fmt.format(x)


def _render_terminal(out: dict) -> str:
    s = out["summary"]
    lines: list[str] = []
    lines.append(f"=== /eval-summary {out['from']} 〜 {out['to']} ===")
    lines.append(
        f"days: {out['n_days']} (with_data={out['n_days_with_data']}, "
        f"missing={out['n_days_missing']})"
    )
    lines.append(
        f"races: {s['n_races']} (settled={s['n_settled']}, "
        f"skipped={s['n_skipped_by_claude']}, no_result={s['n_no_result']})"
    )
    lines.append(f"bet races: {s['n_bet_races']} / hit races: {s['n_hit_races']}")
    lines.append(f"bets: {s['n_bets']} / hits: {s['n_hits']}")
    lines.append(f"stake: {s['total_stake']:,}円 / payout: {s['total_payout']:,.0f}円")
    lines.append(
        f"ROI: {s['roi']:+.1%}  hit_rate/bet: {s['hit_rate_per_bet']:.2%}  "
        f"hit_rate/race: {s['hit_rate_per_race']:.2%}"
    )
    lines.append(
        f"skip_rate: {s['skip_rate']:.1%}  avg_confidence: {s['avg_confidence']:.2f}"
    )
    if s.get("bootstrap_ci"):
        ci = s["bootstrap_ci"]
        lines.append(
            f"bootstrap 95% CI (N={ci['n']}): [{ci['lower']:+.1%}, {ci['upper']:+.1%}]"
        )
    lines.append("")

    if out["by_month"]:
        lines.append("[月次トレンド]")
        lines.append(
            f"{'month':<8} {'days':>4} {'races':>6} {'bets':>5} {'hits':>4} "
            f"{'stake':>10} {'payout':>12} {'ROI':>8} {'hit/bet':>8}"
        )
        for m in out["by_month"]:
            lines.append(
                f"{m['month']:<8} {m['n_days']:>4} {m['n_races']:>6} "
                f"{m['n_bets']:>5} {m['n_hits']:>4} "
                f"{m['total_stake']:>10,} {m['total_payout']:>12,.0f} "
                f"{_fmt_pct(m['roi'])} {m['hit_rate_per_bet']:>7.2%}"
            )
        lines.append("")

    if out["by_stadium"]:
        lines.append("[場別累積]")
        lines.append(
            f"{'場':<8} {'races':>5} {'bets':>5} {'hits':>4} "
            f"{'stake':>10} {'payout':>12} {'ROI':>8}"
        )
        for st in out["by_stadium"]:
            lines.append(
                f"{st['name']:<8} {st['n_races']:>5} {st['n_bets']:>5} {st['n_hits']:>4} "
                f"{st['total_stake']:>10,} {st['total_payout']:>12,.0f} {_fmt_pct(st['roi'])}"
            )
        lines.append("")

    if out["by_confidence_band"]:
        lines.append("[Confidence 帯別]")
        lines.append(
            f"{'band':<10} {'bets':>5} {'hits':>4} "
            f"{'stake':>10} {'payout':>12} {'ROI':>8}"
        )
        for b in out["by_confidence_band"]:
            lines.append(
                f"{b['band']:<10} {b['n_bets']:>5} {b['n_hits']:>4} "
                f"{b['total_stake']:>10,} {b['total_payout']:>12,.0f} {_fmt_pct(b['roi'])}"
            )
        lines.append("")

    if out["daily_roi_stats"]:
        ds = out["daily_roi_stats"]
        lines.append("[日次 ROI 統計]")
        lines.append(
            f"  N={ds['n']}  min={_fmt_pct(ds['min'])}  median={_fmt_pct(ds['median'])}  "
            f"mean={_fmt_pct(ds['mean'])}  max={_fmt_pct(ds['max'])}  stddev={ds['stddev']:.3f}"
        )
        if "worst_day" in ds:
            lines.append(f"  worst_day: {ds['worst_day']}  best_day: {ds['best_day']}")
        lines.append("")

    if out["monthly_roi_stats"]:
        ms = out["monthly_roi_stats"]
        lines.append("[月次 ROI 統計]")
        lines.append(
            f"  N={ms['n']}  min={_fmt_pct(ms['min'])}  median={_fmt_pct(ms['median'])}  "
            f"mean={_fmt_pct(ms['mean'])}  max={_fmt_pct(ms['max'])}  stddev={ms['stddev']:.3f}"
        )
        if "worst_month" in ms:
            lines.append(f"  worst_month: {ms['worst_month']}  best_month: {ms['best_month']}")
        lines.append("")

    v = out["verdict"]
    lines.append(f"[判定] {v['label']}  status={v['status']}")
    crit = v["criteria"]
    lines.append(f"  - 達成基準 ≥+10%: {crit['production_ready']}")
    lines.append(f"  - トントン:        {crit['breakeven']}")
    lines.append(f"  ※ {v['note']}")

    if out["warnings"]:
        lines.append("")
        lines.append("[Warnings]")
        for w in out["warnings"]:
            lines.append(f"  ⚠ {w}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _save(out: dict, eval_dir: Path) -> Path:
    eval_dir.mkdir(parents=True, exist_ok=True)
    path = eval_dir / f"summary_{out['from']}_{out['to']}.json"
    path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> int:
    # Windows コンソール (cp932) では ✓✗△ 等が出力できないので UTF-8 に切替
    for stream_name in ("stdout", "stderr"):
        s = getattr(sys, stream_name, None)
        if s is not None and hasattr(s, "reconfigure"):
            try:
                s.reconfigure(encoding="utf-8")
            except Exception:
                pass

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

    p = argparse.ArgumentParser(
        description="期間内の <日付>.json を集約して累積 ROI を算出 (P3.5)",
    )
    p.add_argument("--from", dest="from_", help="YYYY-MM-DD")
    p.add_argument("--to", dest="to_", help="YYYY-MM-DD")
    p.add_argument("--month", dest="month", help="YYYY-MM (糖衣構文 / from/to を自動展開)")
    p.add_argument("--eval-dir", default=str(EVAL_DIR), help="評価 JSON 格納ディレクトリ")
    p.add_argument("--bootstrap-n", type=int, default=1000, help="bootstrap リサンプル回数")
    p.add_argument("--bootstrap-seed", type=int, default=42, help="bootstrap 乱数シード")
    p.add_argument("--no-bootstrap", action="store_true", help="bootstrap CI を計算しない")
    p.add_argument("--quiet", action="store_true", help="ターミナル表示を省略")
    args = p.parse_args(argv)

    if args.month:
        if args.from_ or args.to_:
            print("[summary] --month と --from/--to は同時指定不可", file=sys.stderr)
            return 2
        from_str, to_str = _expand_month(args.month)
    else:
        if not (args.from_ and args.to_):
            print("[summary] --from と --to 両方必要 (または --month を使用)", file=sys.stderr)
            return 2
        from_str, to_str = args.from_, args.to_

    eval_dir = Path(args.eval_dir)

    try:
        out, term = summarize(
            from_str,
            to_str,
            eval_dir=eval_dir,
            bootstrap_n=args.bootstrap_n,
            bootstrap_seed=args.bootstrap_seed,
            do_bootstrap=not args.no_bootstrap,
        )
    except FileNotFoundError as exc:
        print(f"[summary] {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"[summary] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        logger.exception("summarize failed")
        print(f"[summary] エラー: {exc}", file=sys.stderr)
        return 1

    out_path = _save(out, eval_dir)
    if not args.quiet:
        print(term)
    print(f"\n[summary] saved: {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
