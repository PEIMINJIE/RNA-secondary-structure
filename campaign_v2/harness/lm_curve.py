#!/usr/bin/env python3
"""从一份 LM 解码产物里抽出 solved@N 曲线（零额外 GPU 成本）。

`lm_select.py` 是「命中即停」的，对单点 B=N 是正确口径，但停了就不知道
后面的候选还能不能命中。这里反过来：把每题的候选**按解码顺序全部折一遍**，
记下「第一条命中的候选下标」first_hit。有了它，任意 N 的结果都是导出量：

    solved@N      = #{题 : first_hit < N}
    折叠数@N（该题）= min(first_hit + 1, N)     # 命中即停的真实成本

所以一次 N=1000 的解码可以免费回答 N=1,2,5,...,1000 的所有问题，
用来判断「LM 的预算轴到底在哪里饱和」——如果 solved@N 在几百就平了，
那让 LM 去对齐 CPU 方法的 B=10^4 就没有意义，这是要写进报告的结论。

判据是**生成侧** ViennaRNA 的 MFE 碱基对距离（和 lm_select.py 一致）；
权威数字仍由 harness/verify.py 在 2.8.0 下重验证，本脚本只定 N。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "harness"))

BENCHES = {
    "v2": "data/eterna100/eterna100_v2.jsonl",
    "v1": "data/eterna100/eterna100_v1.jsonl",
    "taneda29": "data/taneda/taneda29.jsonl",
    "taneda27": "data/taneda/taneda27.jsonl",
    "archiveii": "data/archiveii/archiveii1144.jsonl",
}


def bp_set(db: str):
    st, out = [], set()
    for i, c in enumerate(db):
        if c == "(":
            st.append(i)
        elif c == ")":
            if st:
                out.add((st.pop(), i))
    return out


def _work(job):
    """折完一题的所有候选，返回 (id, first_hit, best_d, n_cand)。"""
    pid, target, seqs = job
    import RNA
    import rnaenv
    rnaenv.pin_env()
    tbp = bp_set(target)
    first_hit, best_d = None, None
    for i, s in enumerate(seqs):
        if len(s) != len(target):
            continue
        st, _ = RNA.fold_compound(s).mfe()
        d = len(tbp ^ bp_set(st))
        if best_d is None or d < best_d:
            best_d = d
        if d == 0 and first_hit is None:
            first_hit = i
            break          # 只要 first_hit，后面的候选不影响任何导出量
    return pid, first_hit, best_d, len(seqs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decode", nargs="+", required=True,
                    help="一份或多份 run_lm.py 解码 jsonl（分片跑的直接全传进来）")
    ap.add_argument("--bench", required=True, choices=sorted(BENCHES))
    ap.add_argument("--procs", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", 8)))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    meta = {json.loads(l)["id"]: json.loads(l)
            for l in open(os.path.join(ROOT, BENCHES[args.bench])) if l.strip()}

    cand = defaultdict(list)
    for p in args.decode:
        with open(p) as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                d = json.loads(ln)
                s = (d.get("designed_sequence") or "").strip().upper()
                if s:
                    cand[d["id"]].append(s)

    jobs = [(pid, meta[pid]["target_structure"], seqs)
            for pid, seqs in sorted(cand.items()) if pid in meta]
    n_tot = sum(len(j[2]) for j in jobs)
    print(f"[curve] {len(jobs)} 题，候选 {n_tot:,} 条，{args.procs} 进程")

    with Pool(args.procs) as pool:
        res = pool.map(_work, jobs, chunksize=1)

    per = {}
    for pid, fh, bd, nc in res:
        per[pid] = {"first_hit": fh, "best_bpd": bd, "n_candidates": nc,
                    "length": meta[pid]["length"], "name": meta[pid].get("name")}

    n_cand_min = min(v["n_candidates"] for v in per.values())
    ladder = [n for n in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000)
              if n <= n_cand_min]
    if n_cand_min not in ladder:
        ladder.append(n_cand_min)

    curve = []
    for N in ladder:
        soln = [p for p, v in per.items()
                if v["first_hit"] is not None and v["first_hit"] < N]
        folds = sum(min((v["first_hit"] + 1) if v["first_hit"] is not None else N, N)
                    for v in per.values())
        curve.append({"N": N, "solved": len(soln), "of": len(per),
                      "folds_total": folds,
                      "folds_per_puzzle_mean": folds / len(per)})

    out = {"bench": args.bench, "n_puzzles": len(per),
           "n_candidates_min_per_puzzle": n_cand_min,
           "criterion": "generation-side ViennaRNA MFE bp-distance == 0",
           "curve": curve, "per_puzzle": per}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)

    print()
    print(f"{'N':>6s} {'solved':>8s} {'/':>1s}{'题':>5s} {'折叠/题(均)':>12s}")
    for c in curve:
        print(f"{c['N']:6d} {c['solved']:8d} /{c['of']:5d} {c['folds_per_puzzle_mean']:12.1f}")
    print()
    # 饱和判断：最后一个十倍区间还涨几题
    if len(curve) >= 2:
        a, b = curve[-2], curve[-1]
        print(f"[curve] 末段 N {a['N']} -> {b['N']}：solved {a['solved']} -> {b['solved']}"
              f"（+{b['solved'] - a['solved']} 题）")
    print(f"-> {os.path.relpath(args.out, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
