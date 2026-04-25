"""
LambdaRank seed-check ハーネス（タスク 6-10-d Step 1）

run_objective_poc.py を baseline (multiclass) と R1 (lambdarank) について
seed=42/123/7 で 3 回ずつ計 6 run 実行し、top-1 accuracy の seed 分散を測る。

採用判断（合意済み）:
  Δ_obs = mean(R1.top1) - mean(baseline.top1)
  std_pooled = sqrt((std(R1)^2 + std(baseline)^2) / 2)
  - Δ_obs ≥ 2 × std_pooled かつ Δ_obs ≥ 0.4pp → R1 改善は真、Step 2 へ進む
  - Δ_obs < std_pooled  または Δ_obs < 0.2pp → seed ノイズ、フェーズ 6 撤退提案
  - 中間はグレーゾーン、ユーザー判断委譲

使い方:
  py -3.12 ml/src/scripts/run_lambdarank_seed_check.py
  # 任意で seed セット変更:
  py -3.12 ml/src/scripts/run_lambdarank_seed_check.py --seeds 42 123 7
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parents[3]
DEFAULT_OUT = ROOT / "artifacts" / "lambdarank_seed_check_results.jsonl"
DEFAULT_LOG_DIR = ROOT / "artifacts" / "lambdarank_seed_check_logs"


def _run_one(
    objective: str,
    seed: int,
    val_year: int,
    val_month: int,
    train_start_year: int,
    out_jsonl: Path,
    log_dir: Path,
) -> dict:
    tag = f"{'baseline' if objective == 'multiclass' else 'R1'}_seed{seed}"
    log_path = log_dir / f"{tag}.log"
    log_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,  # 呼び出し側で py -3.12 経由なので同 interp を流用
        str(ROOT / "ml" / "src" / "scripts" / "run_objective_poc.py"),
        "--val-year", str(val_year),
        "--val-month", str(val_month),
        "--train-start-year", str(train_start_year),
        "--tag", tag,
        "--objective", objective,
        "--seed", str(seed),
        "--out-jsonl", str(out_jsonl),
    ]
    print(f"\n[seed-check] RUN tag={tag} objective={objective} seed={seed}")
    print(f"  cmd: {' '.join(cmd)}")
    print(f"  log: {log_path}")

    with log_path.open("w", encoding="utf-8") as logf:
        proc = subprocess.run(
            cmd,
            stdout=logf,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if proc.returncode != 0:
        raise RuntimeError(
            f"run_objective_poc.py 失敗 (tag={tag}, returncode={proc.returncode})\n"
            f"ログ: {log_path}"
        )

    # jsonl 末尾行を読む
    with out_jsonl.open("r", encoding="utf-8") as f:
        lines = [ln for ln in f.readlines() if ln.strip()]
    last = json.loads(lines[-1])
    if last["tag"] != tag:
        raise RuntimeError(f"jsonl 末尾の tag={last['tag']} が期待値 {tag} と不一致")
    print(
        f"  → top1_norm={last['top1_accuracy_norm']:.4f}  "
        f"NDCG@1={last['ndcg_at_1']:.4f}  best_iter={last['best_iteration']}"
    )
    return last


def _summary(rows: list[dict]) -> dict:
    arr = np.array([r["top1_accuracy_norm"] for r in rows], dtype=float)
    return {
        "n": len(arr),
        "mean": float(arr.mean()),
        "std": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
        "min": float(arr.min()),
        "max": float(arr.max()),
        "values": arr.tolist(),
    }


def _verdict(delta_pp: float, std_pooled_pp: float) -> str:
    if delta_pp >= 2 * std_pooled_pp and delta_pp >= 0.4:
        return "go"  # Step 2 へ進む
    if delta_pp < std_pooled_pp or delta_pp < 0.2:
        return "withdraw"  # フェーズ 6 撤退提案
    return "gray"  # ユーザー判断


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--val-year", type=int, default=2025)
    p.add_argument("--val-month", type=int, default=12)
    p.add_argument("--train-start-year", type=int, default=2023)
    p.add_argument("--seeds", type=int, nargs="+", default=[42, 123, 7])
    p.add_argument("--out-jsonl", type=str, default=str(DEFAULT_OUT))
    p.add_argument("--log-dir", type=str, default=str(DEFAULT_LOG_DIR))
    args = p.parse_args()

    out_jsonl = Path(args.out_jsonl)
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    # 既存ファイルがあると tag 一致判定がずれるのでクリア
    if out_jsonl.exists():
        out_jsonl.unlink()
    log_dir = Path(args.log_dir)

    print(f"[seed-check] start  seeds={args.seeds}  val={args.val_year}-{args.val_month:02d}")
    print(f"[seed-check] out_jsonl={out_jsonl}")

    baseline_rows: list[dict] = []
    r1_rows: list[dict] = []

    for seed in args.seeds:
        # baseline → R1 の順で 1 seed あたり 2 run
        baseline_rows.append(_run_one(
            "multiclass", seed,
            args.val_year, args.val_month, args.train_start_year,
            out_jsonl, log_dir,
        ))
        r1_rows.append(_run_one(
            "lambdarank", seed,
            args.val_year, args.val_month, args.train_start_year,
            out_jsonl, log_dir,
        ))

    bs = _summary(baseline_rows)
    rs = _summary(r1_rows)

    delta = rs["mean"] - bs["mean"]  # 0.0xx スケール
    std_pooled = float(np.sqrt((rs["std"] ** 2 + bs["std"] ** 2) / 2))
    delta_pp = delta * 100
    std_pooled_pp = std_pooled * 100
    verdict = _verdict(delta_pp, std_pooled_pp)

    summary = {
        "seeds": args.seeds,
        "val_period": f"{args.val_year}-{args.val_month:02d}",
        "baseline": bs,
        "R1_lambdarank": rs,
        "delta": delta,
        "delta_pp": delta_pp,
        "std_pooled": std_pooled,
        "std_pooled_pp": std_pooled_pp,
        "verdict": verdict,
    }

    print("\n========== SEED-CHECK SUMMARY ==========")
    print(f"  seeds: {args.seeds}")
    print(f"  baseline (multiclass) top1: mean={bs['mean']:.4f}  std={bs['std']:.4f}  "
          f"min={bs['min']:.4f}  max={bs['max']:.4f}")
    print(f"  R1 (lambdarank)      top1: mean={rs['mean']:.4f}  std={rs['std']:.4f}  "
          f"min={rs['min']:.4f}  max={rs['max']:.4f}")
    print(f"  delta_obs = R1 - baseline = {delta_pp:+.3f} pp")
    print(f"  std_pooled                = {std_pooled_pp:.3f} pp")
    print(f"  threshold (go)      : delta >= 2*sigma ({2*std_pooled_pp:.3f} pp) AND delta >= 0.4 pp")
    print(f"  threshold (withdraw): delta <  1*sigma ({std_pooled_pp:.3f} pp)  OR  delta <  0.2 pp")
    print(f"  VERDICT: {verdict}")
    print("========================================\n")

    summary_path = out_jsonl.parent / "lambdarank_seed_check_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"summary → {summary_path}")


if __name__ == "__main__":
    main()
