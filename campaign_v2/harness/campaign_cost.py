"""按**实测**单位成本 + Eterna100 真实长度分布，算 Phase 0 campaign 要多少核时。

实测标定（2026-11-24，作业 52681058 / 52682414 / 52682477）：
  NEMO    : 每迭代折叠次数 ≈ 3.2·L（L=100/200/400 实测 345/673/1257）
            单次 fold（复用 DP 矩阵）≈ 1.4 ms·(L/100)³（实测 1.4 / 11.75 / 92.8 ms）
  SAMFEO  : 每步 1.1 次 pf（各长度一致）
            单次 pf ≈ 9.5 ms·(L/123)³（实测 L=123/214/400 → 9.5 / 55 / 252 ms）
  RNAinverse: 短题秒级命中；L≥200 在 120 s 内不命中（右删失）
  统一验证 : 3270 条 / 5.5 min / 1 核 → 可忽略

用法：python -I harness/campaign_cost.py --seeds 5 --bmax-hours 1
"""

from __future__ import annotations

import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def nemo_fold_sec(L: float) -> float:
    return 1.4e-3 * (L / 100.0) ** 3


def nemo_iter_sec(L: float) -> float:
    return 3.2 * L * nemo_fold_sec(L)


def samfeo_pf_sec(L: float) -> float:
    return 9.5e-3 * (L / 123.0) ** 3


def samfeo_step_sec(L: float) -> float:
    return 1.1 * samfeo_pf_sec(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--bmax-hours", type=float, default=1.0,
                    help="每题每 seed 的墙钟上限（右删失点）")
    ap.add_argument("--nemo-iters", type=int, default=2500)
    ap.add_argument("--samfeo-steps", type=int, default=5000)
    ap.add_argument("--sd-steps", type=int, default=2000)
    ap.add_argument("--sd-step-sec", type=float, default=0.0,
                    help="SamplingDesign 每步秒数（实测后填；0=用占位估计）")
    args = ap.parse_args()

    cap = args.bmax_hours * 3600.0
    bench = {}
    for ver in ("v1", "v2"):
        p = os.path.join(ROOT, "data", "eterna100", f"eterna100_{ver}.jsonl")
        bench[ver] = [json.loads(l) for l in open(p) if l.strip()]

    print(f"预算上限 B_max = {args.bmax_hours} h/题/seed，seed 数 = {args.seeds}")
    uniq_all = {d["target_structure"]: d["length"] for ver in ("v1", "v2") for d in bench[ver]}
    ls = sorted(d["length"] for d in bench["v2"])
    print(f"长度分布：V2 中位 {ls[50]}nt, 最大 {max(ls)}nt, "
          f"<60nt {sum(1 for x in ls if x < 60)} 道, 60–150 {sum(1 for x in ls if 60 <= x < 150)} 道, "
          f"≥150 {sum(1 for x in ls if x >= 150)} 道")
    print(f"V1∪V2 去重后的结构数：{len(uniq_all)}（V1/V2 有 81 道相同，只跑一次）\n")

    total = {}
    for name, per_puzzle in (
        ("NEMO (2500 iter 上限)",
         lambda L: min(cap, args.nemo_iters * nemo_iter_sec(L))),
        ("SAMFEO (5000 步上限)",
         lambda L: min(cap, args.samfeo_steps * samfeo_step_sec(L))),
        ("RNAinverse-pf",
         lambda L: min(cap, 120.0 if L >= 150 else 5.0)),
        ("SamplingDesign",
         lambda L: min(cap, args.sd_steps * (args.sd_step_sec or samfeo_step_sec(L) * 3))),
    ):
        # V1 与 V2 有 81 道题结构相同 -> 只需跑一次。按**去重后的结构集**算，否则高估 1.7 倍
        uniq = {d["target_structure"]: d["length"] for ver in ("v1", "v2") for d in bench[ver]}
        hrs = sum(per_puzzle(L) for L in uniq.values()) * args.seeds / 3600.0
        v2_only = sum(per_puzzle(d["length"]) for d in bench["v2"]) * args.seeds / 3600.0
        total[name] = hrs
        print(f"{name:24s} {hrs:8.0f} 核时   (仅 V2: {v2_only:.0f} 核时)")

    s = sum(total.values())
    print(f"\n{'合计':24s} {s:8.0f} 核时")
    for cores in (200, 540):
        print(f"  在 {cores} 核 burst 上纯算 {s/cores:6.1f} h"
              f"  → 含排队/重跑按 3× 留余量 ≈ {s/cores*3/24:.1f} 天")
    print("\n注：墙钟上限是**右删失点**，不是浪费 —— 超过 B_max 还没解出的题，"
          "在 solved@B 曲线上就记为该预算下未解。所以 B_max 直接决定成本，也决定曲线能画到多远。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
