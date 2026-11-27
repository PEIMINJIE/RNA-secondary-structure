#!/usr/bin/env python3
"""把 LM 的 4 条 solved@N 曲线汇成 spec §4 要的一张表。

为什么单独一个脚本：table_v2.py 里的 solved@B 只对「命中即停」的方法有定义
（NEMO / RNAinverse），而 LM 的预算轴是候选数 N，B = N 的语义完全不同 ——
每条候选恰好一次折叠调用，所以 N 既是候选数也是折叠调用数，这是唯一一个
两条轴重合的方法。混进同一张表会让人以为可以跨方法读同一列。

判据：生成侧 ViennaRNA 的 MFE 判据（bp 距离 = 0）。注意这**不是**统一重验证
的数 —— 重验证用 ViennaRNA 2.8.0 另跑一遍，表里的准确率格子用后者。曲线的作用
是「预算→命中」的形状，不是最终准确率，两者在 N = 单 seed 预算处应当接近。

口径差异必须讲清楚：曲线把一道题的全部候选**合在一起**（8 个 seed × 10000），
所以 solved@80000 是 8 个 seed 合起来的 best-of-80000；而表里的格子是
「单个 seed 的 best-of-10000，再跨 seed 取均值」。因此曲线在 N=10000 处
应当≈表里的均值，而末端的 solved@80000 会更高 —— 那是并集，不能填进表。
"""
from __future__ import annotations

import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LM = os.path.join(ROOT, "results", "campaignV2", "lm")
BENCHES = ["v2", "v1", "taneda29", "archiveii"]
LABEL = {"v2": "Eterna100-V2", "v1": "Eterna100-V1",
         "taneda29": "Rfam-Taneda(29)", "archiveii": "ArchiveII"}
# spec §2 的 seed 数。单 seed 预算 = 曲线自带的每题候选数 ÷ seed 数 —— **算出来的，
# 不写死**：四个 benchmark 的预算实测并不一致（v2 是 10,000，另外三个是 1,000），
# 写死成 10,000 会把这个差别藏掉。
BENCH_SEEDS = {"v2": 8, "v1": 8, "taneda29": 16, "archiveii": 1}
# §1 表里对应格子的 MFE 均值，用来在同一 N 处做自洽检查。
TABLE_MFE = {"v2": 80.5, "v1": 70.1, "taneda29": 24.0, "archiveii": 966.0}
# 基线的名义预算（折叠调用数）。LM 低于它的 benchmark 必须显式标出来。
BASELINE_B = 10000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flavor", default="slrl")
    ap.add_argument("--out", default=os.path.join(ROOT, "reports", "lm_curve_table.md"))
    args = ap.parse_args()

    loaded = {}
    for b in BENCHES:
        p = os.path.join(LM, f"full_{args.flavor}_{b}_curve.json")
        if not os.path.exists(p):
            print(f"⚠️  缺 {os.path.relpath(p, ROOT)}，跳过 {b}")
            continue
        loaded[b] = json.load(open(p))

    L = []
    L.append("# RNA-Design-LM 的 solved@N 曲线（spec §4）")
    L.append("")
    L.append("每条候选恰好一次折叠调用，所以 **N 既是候选数也是折叠调用数** —— "
             "LM 是唯一一个这两条预算轴重合的方法。判据为生成侧 ViennaRNA 的 "
             "MFE 判据（bp 距离 = 0）。")
    L.append("")
    L.append("⚠️ **口径**：曲线把一道题的全部候选合在一起（seed 数 × 单 seed 预算），"
             "所以末端是**并集**；而 §1 表里的格子是「单 seed best-of-预算，再跨 seed 取均值」，"
             "**未取并集**。两者只在 N = 单 seed 预算处可比，末端的高值不可填进表。")
    L.append("")

    # 单 seed 预算是算出来的：每题候选数 ÷ seed 数。
    budget = {}
    for b, d in loaded.items():
        s = BENCH_SEEDS[b]
        nc = d["n_candidates_min_per_puzzle"]
        budget[b] = nc // s
        if nc % s:
            L.append(f"⚠️ {LABEL[b]}：每题候选 {nc:,} 不是 seed 数 {s} 的整数倍，"
                     f"单 seed 预算取整为 {nc // s:,}，请核对。")

    low = [b for b in loaded if budget[b] < BASELINE_B]
    if low:
        L.append(f"🚨 **预算不一致（必须随表交出去）**：基线的名义预算是 "
                 f"B = {BASELINE_B:,} 次折叠调用，而 LM 在 "
                 + "、".join(f"{LABEL[b]}（B = {budget[b]:,}）" for b in BENCHES if b in low)
                 + f" 上只跑了更小的预算 —— 最低处只有基线的 "
                 f"1/{BASELINE_B // min(budget[b] for b in low)}。"
                 "这对 LM 不利，但不标出来就会被当成同预算比较。"
                 "下面「饱和行为」那张表给出这个差距值多少的上界。")
        L.append("")

    grids = sorted({c["N"] for d in loaded.values() for c in d["curve"]})
    L.append("| benchmark | 题数 | 单 seed 预算 B | " +
             " | ".join(f"N={g:,}" for g in grids) + " |")
    L.append("|---|---|---|" + "---|" * len(grids))
    for b in BENCHES:
        d = loaded.get(b)
        if not d:
            continue
        by_n = {c["N"]: c for c in d["curve"]}
        cells = []
        for g in grids:
            c = by_n.get(g)
            cells.append(f"{c['solved']}" if c else "—")
        mark = "" if budget[b] >= BASELINE_B else f" ⚠️"
        L.append(f"| {LABEL[b]} | {d['n_puzzles']} | {budget[b]:,}{mark} | "
                 + " | ".join(cells) + " |")

    L.append("")
    L.append("## 和 §1 表的对照（同一 N，检查两条口径是否自洽）")
    L.append("")
    L.append("| benchmark | 单 seed 预算 B | 曲线 solved@B（并集） | §1 表（单 seed 均值） | 末端 solved@N<sub>max</sub> | 末端 − 表 |")
    L.append("|---|---|---|---|---|---|")
    for b in BENCHES:
        d = loaded.get(b)
        if not d:
            continue
        by_n = {c["N"]: c for c in d["curve"]}
        n_ref, tab = budget[b], TABLE_MFE[b]
        at_ref = by_n.get(n_ref)
        last = d["curve"][-1]
        # 曲线的 N 网格不一定落在 B 上；落不上就取不超过 B 的最大一格，并标出来。
        if at_ref:
            ref_s = f"{at_ref['solved']}"
        else:
            le = [c for c in d["curve"] if c["N"] <= n_ref]
            ref_s = (f"{le[-1]['solved']}（在 N={le[-1]['N']:,}，网格上无 B 这一格）"
                     if le else "—")
        L.append(f"| {LABEL[b]} | {n_ref:,} | {ref_s} | {tab} | "
                 f"{last['solved']} (N={last['N']:,}) | "
                 f"{last['solved'] - tab:+.1f} |")

    L.append("")
    L.append("## 饱和行为")
    L.append("")
    L.append("「B → 末端」这一列是**补预算值多少的上界**：它是把 seed 合起来之后"
             "多给候选换来的题数。注意它是并集轴上的收益，所以只能当上界 ——"
             "单个 seed 把预算从 B 加到同样大小，拿到的不会比它更多。")
    L.append("")
    L.append("| benchmark | 单 seed 预算 B | 末段 | solved 变化 | B → 末端 | 读法 |")
    L.append("|---|---|---|---|---|---|")
    for b in BENCHES:
        d = loaded.get(b)
        if not d:
            continue
        a, z = d["curve"][-2], d["curve"][-1]
        dz = z["solved"] - a["solved"]
        le = [c for c in d["curve"] if c["N"] <= budget[b]]
        gain = (f"{z['solved'] - le[-1]['solved']:+d} 题"
                f"（N {le[-1]['N']:,} → {z['N']:,}）") if le else "—"
        verdict = ("已饱和（加预算不再有收益）" if dz == 0 else
                   f"**未饱和**（最后一段还在涨 {dz:+d} 题，所以 solved@N 在 "
                   f"N={z['N']:,} 处仍未到上限）")
        L.append(f"| {LABEL[b]} | {budget[b]:,} | N {a['N']:,} → {z['N']:,} | "
                 f"{a['solved']} → {z['solved']} ({dz:+d}) | {gain} | {verdict} |")

    L.append("")
    L.append("## 每题首次命中所需的候选数（折叠调用数）")
    L.append("")
    L.append("| benchmark | 命中题数 | 中位 | p90 | 最大 | N=1 即命中 |")
    L.append("|---|---|---|---|---|---|")
    for b in BENCHES:
        d = loaded.get(b)
        if not d:
            continue
        pp = d["per_puzzle"]
        # first_hit 是 0 起的下标（0 = 第一条候选就命中），未命中为 None。
        # 这里要的是「第几条」，所以 +1 —— 它同时就是折叠调用数。
        hits = sorted(x["first_hit"] + 1 for x in
                      (pp.values() if isinstance(pp, dict) else pp)
                      if x.get("first_hit") is not None)
        if not hits:
            L.append(f"| {LABEL[b]} | 0 | — | — | — | — |")
            continue
        n = len(hits)
        L.append(f"| {LABEL[b]} | {n} | {hits[n // 2]:,} | "
                 f"{hits[min(n - 1, int(.9 * n))]:,} | {hits[-1]:,} | "
                 f"{sum(1 for h in hits if h == 1) / n:.0%} |")

    txt = "\n".join(L) + "\n"
    with open(args.out, "w") as fh:
        fh.write(txt)
    print(txt)
    print(f"-> {os.path.relpath(args.out, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
