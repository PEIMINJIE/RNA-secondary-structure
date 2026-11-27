#!/usr/bin/env python3
"""campaign_spec v2 的资源估算（逐题版）。

为什么要逐题：spec §4 要求墙钟闸「对任何方法都不触发」，于是单次运行的成本
= 实际用掉的折叠数 × 该长度下的单次折叠耗时。而
  - 单次折叠耗时是 O(L^3)：实测 pf 在 L=30 是 0.56 ms，在 L=400 是 418 ms，差 750 倍
  - Eterna100 的长度分布有长尾（最长 400 nt）
所以**成本几乎全部由最长的那几道题决定**，用「平均墙钟 × 运行数」会严重低估。
（我第一版就是这么算的，得到 1118 核时，错得很厉害。）

逐题成本 = min(B, 该题实测命中折叠数) × 单次折叠耗时(L)
          未命中的题 → 吃满 B

Phase 0 的逐题命中折叠数在 results/solvedB/per_puzzle_cost.csv（只有 V2）。
V1 的长度分布与 V2 几乎相同，直接复用其命中率与中位命中成本；
Taneda / ArchiveII 没有数据，按各方法在 V2 上的命中率 + 中位命中折叠数外推。
"""
from __future__ import annotations

import csv
import json
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SEEDS = {"v2": 8, "v1": 8, "taneda29": 16, "archiveii": 1}
BENCH_FILES = {
    "v2": "data/eterna100/eterna100_v2.jsonl",
    "v1": "data/eterna100/eterna100_v1.jsonl",
    "taneda29": "data/taneda/taneda29.jsonl",
    "archiveii": "data/archiveii/archiveii1144.jsonl",
}
METHODS = ["nemo", "rnainverse", "samfeo", "desirna", "samplingdesign"]
CORES = {"nemo": 1, "rnainverse": 1, "samfeo": 1, "desirna": 10, "samplingdesign": 32}
# 每个方法的折叠以哪类为主（由 50_calibrate_v2 的分类型计数定出来的）
UNIT = {"nemo": "mfe",                 # C++ 计数器：全是 MFE
        "rnainverse": "pf",            # inverse_pf_fold
        "samfeo": "pf",                # 标定实测 mfe 2 / pf 1020
        "desirna": "mix",              # 标定实测 mfe 6740 / pf 6740 → 一半一半
        "samplingdesign": "pf"}        # objective=prob，走配分函数
# SAMFEO 命中后不停（它继续优化 p），所以它永远吃满预算
ALWAYS_FULL = {"samfeo"}


def interp(L, pl, kind):
    ks = sorted(int(k) for k in pl)
    f = lambda k: pl[str(k)][kind]["median_sec"]
    if L <= ks[0]:
        return f(ks[0]) * (L / ks[0]) ** 3
    if L >= ks[-1]:
        return f(ks[-1]) * (L / ks[-1]) ** 3
    lo = max(k for k in ks if k <= L)
    hi = min(k for k in ks if k >= L)
    if lo == hi:                      # L 正好落在实测表的格点上
        return f(lo)
    t = (L - lo) / (hi - lo)
    return f(lo) * (1 - t) + f(hi) * t


def unit_cost(method, L, pl):
    u = UNIT[method]
    if u == "mix":
        return 0.5 * interp(L, pl, "mfe") + 0.5 * interp(L, pl, "pf")
    return interp(L, pl, u)


def main():
    pl = json.load(open(os.path.join(ROOT, "harness", "cost_model.json")))["per_length"]

    # Phase 0 逐题命中折叠数
    hit = {m: {} for m in METHODS}
    p = os.path.join(ROOT, "results", "solvedB", "per_puzzle_cost.csv")
    with open(p) as fh:
        for row in csv.DictReader(fh):
            for m in METHODS:
                v = (row.get(m) or "").strip()
                if v and v != "-":
                    try:
                        hit[m][int(row["id"])] = float(v)
                    except ValueError:
                        pass
    lens = {}
    for b, pth in BENCH_FILES.items():
        fp = os.path.join(ROOT, pth)
        if os.path.exists(fp):
            lens[b] = {json.loads(l)["id"]: json.loads(l)["length"]
                       for l in open(fp) if l.strip()}

    n_v2 = len(lens["v2"])
    print("=== Phase 0 在 V2 上的命中情况（用来外推）===")
    prior = {}
    for m in METHODS:
        rate = len(hit[m]) / n_v2
        medf = statistics.median(hit[m].values()) if hit[m] else 0
        prior[m] = (rate, medf)
        print(f"  {m:16s} 命中 {len(hit[m]):3d}/{n_v2}（{rate:5.1%}），"
              f"命中中位折叠数 {medf:>10,.0f}")

    for B in (10_000, 100_000, 1_000_000):
        print(f"\n{'=' * 78}\n=== 折叠预算 B = {B:,} ===")
        print(f"{'方法':16s} {'核':>3s} {'核时':>10s} {'最贵单题':>12s} {'最长 10 题占比':>13s}")
        grand = 0.0
        detail = {}
        for m in METHODS:
            rate, medf = prior[m]
            tot_sec = 0.0
            worst = 0.0
            per_bench = {}
            for b, L in lens.items():
                bsec = 0.0
                costs = []
                for pid, ln in L.items():
                    if m in ALWAYS_FULL:
                        folds = B
                    elif b in ("v2", "v1") and pid in hit[m]:
                        folds = min(B, hit[m][pid])
                    elif b in ("v2", "v1"):
                        folds = B                     # Phase 0 未命中 → 吃满
                    else:
                        folds = min(B, medf) if medf else B
                        folds = rate * folds + (1 - rate) * B   # 期望
                    c = folds * unit_cost(m, ln, pl)
                    costs.append(c)
                    bsec += c * SEEDS[b]
                    worst = max(worst, c)
                per_bench[b] = bsec / 3600.0
                tot_sec += bsec
            ch = tot_sec / 3600.0
            # V2 里最长 10 道题占本方法 V2 成本的多少
            v2c = sorted(((unit_cost(m, lens["v2"][i], pl),
                           lens["v2"][i], i) for i in lens["v2"]), reverse=True)
            share = sum(x[0] for x in v2c[:10]) / sum(x[0] for x in v2c)
            detail[m] = {"core_hours": round(ch), "per_bench": {k: round(v) for k, v in per_bench.items()}}
            grand += ch
            print(f"{m:16s} {CORES[m]:>3d} {ch:>10,.0f} {worst / 3600:>10,.1f} h "
                  f"{share:>12.0%}")
        print(f"{'合计':16s} {'':>3s} {grand:>10,.0f} 核时"
              f"   → 540 核打包 {grand / 540:>5,.1f} h / 400 核 {grand / 400:,.1f} h")
        for m in METHODS:
            print(f"    {m:16s} " + "  ".join(
                f"{b}={detail[m]['per_bench'][b]:,}" for b in lens))
        if B == 100_000:
            json.dump({"budget": B, "detail": detail, "core_hours_total": round(grand)},
                      open(os.path.join(ROOT, "results", "estimate_campaign_v2.json"), "w"),
                      indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
