"""从 per-puzzle 的「首次命中成本」算 solved@B 曲线。

输入：verified jsonl，每行至少要有
    id, method, seed, benchmark, mfe_hit (bool), 以及一个成本列（默认 fold_calls_used）
未命中的行视为在该行成本处**右删失**（它花了那么多预算仍未解出）。

输出：
    curve.csv  : method, benchmark, B, solved_mean, solved_std, n_seeds
    percare.csv: method, benchmark, id, length, n_seeds, n_solved, cost_median（命中者）

用法：
  python -I harness/solved_at_b.py --in results/.../*.verified.jsonl --out results/curve.csv
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import os
from collections import defaultdict


def logspace(lo: float, hi: float, n: int):
    if lo <= 0:
        lo = 1.0
    return [lo * (hi / lo) ** (i / (n - 1)) for i in range(n)]


def mean_std(xs):
    if not xs:
        return 0.0, 0.0
    m = sum(xs) / len(xs)
    if len(xs) < 2:
        return m, 0.0
    return m, math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", nargs="+", required=True, help="一个或多个 verified jsonl（支持通配）")
    ap.add_argument("--out", required=True, help="曲线 csv")
    ap.add_argument("--per-puzzle-out", default="", help="逐题 csv（默认与 --out 同目录）")
    ap.add_argument("--cost-key", default="fold_calls_used")
    ap.add_argument("--criterion", choices=["mfe", "umfe"], default="mfe")
    ap.add_argument("--grid", type=int, default=25, help="B 网格点数（log 等距）")
    ap.add_argument("--bmin", type=float, default=100.0)
    ap.add_argument("--bmax", type=float, default=0.0, help="0 = 用数据里的最大成本")
    args = ap.parse_args()

    files = []
    for pat in args.inp:
        files.extend(sorted(glob.glob(pat)) or [pat])

    hit_key = "umfe_hit" if args.criterion == "umfe" else "mfe_hit"
    # (method, bench, seed) -> {id: (solved, cost)}
    runs: dict = defaultdict(dict)
    lengths: dict = {}
    for f in files:
        if not os.path.exists(f):
            continue
        with open(f) as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                r = json.loads(ln)
                key = (str(r.get("method", "?")), str(r.get("benchmark", "?")), str(r.get("seed", "0")))
                cost = r.get(args.cost_key)
                if cost is None:
                    continue
                runs[key][r["id"]] = (bool(r.get(hit_key)), float(cost))
                if r.get("length"):
                    lengths[r["id"]] = r["length"]

    if not runs:
        raise SystemExit("没有可用数据：检查 --cost-key 是否存在于输入里")

    all_costs = [c for d in runs.values() for _, c in d.values()]
    bmax = args.bmax or max(all_costs)
    grid = logspace(args.bmin, bmax, args.grid)

    # 曲线：对每个 (method, bench)，按 seed 算 solved@B 再求均值方差
    by_mb: dict = defaultdict(list)
    for (method, bench, seed), d in runs.items():
        by_mb[(method, bench)].append(d)

    rows = []
    for (method, bench), seeds in sorted(by_mb.items()):
        for B in grid:
            per_seed = [sum(1 for solved, cost in d.values() if solved and cost <= B) for d in seeds]
            m, s = mean_std(per_seed)
            rows.append({"method": method, "benchmark": bench, "B": round(B, 1),
                         "solved_mean": round(m, 3), "solved_std": round(s, 3),
                         "n_seeds": len(seeds)})

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"曲线 -> {args.out}  ({len(rows)} 行, B ∈ [{grid[0]:.0f}, {grid[-1]:.0f}])")

    pp = args.per_puzzle_out or os.path.join(os.path.dirname(os.path.abspath(args.out)), "per_puzzle.csv")
    prows = []
    for (method, bench), seeds in sorted(by_mb.items()):
        ids = sorted({i for d in seeds for i in d})
        for i in ids:
            vals = [d[i] for d in seeds if i in d]
            solved_costs = sorted(c for ok, c in vals if ok)
            prows.append({
                "method": method, "benchmark": bench, "id": i, "length": lengths.get(i, ""),
                "n_seeds": len(vals), "n_solved": len(solved_costs),
                "cost_median_solved": (round(solved_costs[len(solved_costs) // 2], 1) if solved_costs else ""),
                "cost_min_solved": (round(solved_costs[0], 1) if solved_costs else ""),
            })
    with open(pp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(prows[0].keys()))
        w.writeheader()
        w.writerows(prows)
    print(f"逐题 -> {pp}")

    # 控制台速览：几个关键 B
    print(f"\n{'method':20s} {'bm':4s}" + "".join(f"{f'@1e{k}':>9s}" for k in (2, 3, 4, 5, 6)))
    for (method, bench), seeds in sorted(by_mb.items()):
        line = f"{method:20s} {bench:4s}"
        for k in (2, 3, 4, 5, 6):
            B = 10.0 ** k
            per_seed = [sum(1 for solved, cost in d.values() if solved and cost <= B) for d in seeds]
            m, _ = mean_std(per_seed)
            line += f"{m:9.1f}"
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
