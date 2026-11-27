"""把 verify.py 的输出汇总成可读表。

两种口径同时给（baseline_plan.md §1 第 4 条）：
  single : 每个 (method, variant, engine, benchmark, trial) 的 solved 数 —— 单次运行，报 mean±std
  union  : 跨 trial 取并集 —— 文献常用口径，**我们自己的结果永远不用它**，这里只为对齐文献数字

用法：python -I harness/summarize.py --in verified.jsonl --out summary.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from collections import defaultdict


def mean_std(xs):
    if not xs:
        return (float("nan"), float("nan"))
    m = sum(xs) / len(xs)
    if len(xs) == 1:
        return (m, 0.0)
    v = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return (m, math.sqrt(v))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--group", default="method,variant,gen_engine",
                    help="分组键（逗号分隔），benchmark 自动展开")
    args = ap.parse_args()

    keys = args.group.split(",")
    # (group, benchmark) -> trial -> set(ids)
    hits_mfe = defaultdict(lambda: defaultdict(set))
    hits_umfe = defaultdict(lambda: defaultdict(set))
    seen = defaultdict(lambda: defaultdict(set))
    disagree = defaultdict(int)

    with open(args.inp) as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            r = json.loads(ln)
            benches = r.get("benchmarks") or [r.get("benchmark") or "na"]
            g = tuple(str(r.get(k, "")) for k in keys)
            trial = str(r.get("trial") or "1")
            pid = r.get("id")
            for b in benches:
                gk = (g, b)
                seen[gk][trial].add(pid)
                if r.get("mfe_hit"):
                    hits_mfe[gk][trial].add(pid)
                if r.get("umfe_hit"):
                    hits_umfe[gk][trial].add(pid)
            sr = r.get("success_reported")
            if sr not in (None, ""):
                try:
                    if bool(int(float(sr))) != bool(r.get("mfe_hit")):
                        disagree[(g, tuple(benches))] += 1
                except (TypeError, ValueError):
                    pass

    rows = []
    for gk in sorted(seen, key=lambda x: (x[1], x[0])):
        g, b = gk
        trials = sorted(seen[gk])
        per_trial_mfe = [len(hits_mfe[gk].get(t, ())) for t in trials]
        per_trial_umfe = [len(hits_umfe[gk].get(t, ())) for t in trials]
        m_mfe, s_mfe = mean_std(per_trial_mfe)
        m_umfe, s_umfe = mean_std(per_trial_umfe)
        union_mfe = len(set().union(*hits_mfe[gk].values())) if hits_mfe[gk] else 0
        union_umfe = len(set().union(*hits_umfe[gk].values())) if hits_umfe[gk] else 0
        row = dict(zip(keys, g))
        row.update(
            benchmark=b,
            n_trials=len(trials),
            n_puzzles_attempted=len(set().union(*seen[gk].values())),
            solved_mfe_mean=round(m_mfe, 2),
            solved_mfe_std=round(s_mfe, 2),
            solved_umfe_mean=round(m_umfe, 2),
            solved_umfe_std=round(s_umfe, 2),
            solved_mfe_union=union_mfe,
            solved_umfe_union=union_umfe,
            disagree_with_reported=disagree.get((g, tuple([b])), 0),
        )
        rows.append(row)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else keys)
        w.writeheader()
        w.writerows(rows)

    hdr = f"{'method':14s} {'variant':10s} {'engine':9s} {'bm':4s} {'trials':>6s} {'MFE mean±std':>14s} {'MFE union':>9s} {'uMFE mean':>9s} {'uMFE union':>10s}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r.get('method',''):14s} {r.get('variant',''):10s} {r.get('gen_engine',''):9s} "
              f"{r['benchmark']:4s} {r['n_trials']:6d} "
              f"{r['solved_mfe_mean']:8.2f}±{r['solved_mfe_std']:<5.2f} {r['solved_mfe_union']:9d} "
              f"{r['solved_umfe_mean']:9.2f} {r['solved_umfe_union']:10d}")
    print("->", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
