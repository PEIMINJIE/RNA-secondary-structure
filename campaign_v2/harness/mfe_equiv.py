#!/usr/bin/env python3
"""给每次运行算一个「mfe 等效工作量」，作为所有方法都能比的预算轴。

为什么需要第二条轴：spec §4 把折叠调用数定为预算主轴，但三种方法的可计数性不同 ——
  精确计数 : NEMO（C++ omp atomic）、SAMFEO（Python monkeypatch）
  结构性   : SamplingDesign（步数 × 样本数，恒等式）
  **测不到**: RNAinverse（C 内部折叠 Python 不可见）
             DesiRNA（实测 `折叠数 = 进程数 × 132.2`，折叠/进程标准差仅 2.2、r = +1.000；
                      3,112 次干净运行里 78% 取值恰好 13,480，且这 78% 覆盖了全部
                      0–19 RE 步内命中的运行 —— 方法真正工作的区间里没有分辨率。
                      monkeypatch 只抓到每进程固定的初始化段）

两种 mfe 等效：
  (a) 由计数折算  : n_mfe + ratio_pf·n_pf + ratio_subopt·n_subopt   —— 只在计数可信时有效
  (b) 由 CPU 时间 : cpu_sec / mfe_cost_sec(L)                      —— 处处可用，但含非折叠开销

(b) 是唯一对 DesiRNA 可用的轴。它偏大（算进了调度、IO 等开销），所以对一个
baseline 来说是**保守**方向：不会高估它在给定预算下的成绩。
用 NEMO / SAMFEO（两者 (a) 与 (b) 都有）互校，报告两条轴的比值，读者自己判断可信度。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "harness"))
RES = os.path.join(ROOT, "results", "campaignV2")

_COST = None


def _cost():
    global _COST
    if _COST is None:
        with open(os.path.join(ROOT, "harness", "cost_model.json")) as fh:
            _COST = json.load(fh)
    return _COST


def mfe_cost_sec(length: int) -> float:
    per = _cost()["per_length"]
    ls = sorted(int(k) for k in per)
    lo = max([x for x in ls if x <= length], default=ls[0])
    hi = min([x for x in ls if x >= length], default=ls[-1])
    c_lo = per[str(lo)]["mfe"]["min_sec"]
    c_hi = per[str(hi)]["mfe"]["min_sec"]
    if hi == lo:
        return c_lo
    w = (length - lo) / (hi - lo)
    return c_lo + w * (c_hi - c_lo)


def ratios(length: int):
    per = _cost()["per_length"]
    ls = sorted(int(k) for k in per)
    lo = max([x for x in ls if x <= length], default=ls[0])
    r = per[str(lo)].get("ratio_to_mfe", {})
    return float(r.get("pf", 1.7)), float(r.get("subopt", 1.0))


def from_counts(row):
    """(a) 由分类型计数折算成 mfe 等效。"""
    fc = row.get("fold_counts") or {}
    n_mfe = fc.get("mfe") or 0
    n_pf = fc.get("pf") or 0
    n_sub = fc.get("subopt") or 0
    if n_mfe + n_pf + n_sub == 0:
        return None
    rp, rs = ratios(row["length"])
    return n_mfe + rp * n_pf + rs * n_sub


# 实测 CPU 利用率（sacct 的 TotalCPU ÷ CPUTimeRAW，取 .batch 步骤；注意 `-X` 会把
# 记着 TotalCPU 的步骤过滤掉，必须不带 -X 查）。`wall × cpus` 是分配量，不是实际用量，
# 直接拿它折算会高估多核方法。数据来自 Eterna100-V2 的全量跑。
# ⚠️ 取数时必须①按 **JobName** 归组（不要按猜的 job id —— 我曾把 52865471 当成
# samfeo_v2，它其实是 samp_v2，32 核，于是 SAMFEO 的成本和利用率全错），
# ②只取 State=COMPLETED 的任务（被取消的任务分配时间长、实际 CPU 少，会压低利用率），
# ③`.batch` 步骤才记着 TotalCPU，所以查询不能带 `-X`。
# 下面是 Eterna100-V2 全量跑的实测值（DesiRNA 另有两次独立验证：sacct 83.2%、
# `/usr/bin/time -v` 对 L=400 单题报 845% of 10 核 = 84.5%）。
UTIL = {"nemo": 0.986, "samfeo": 0.986, "desirna": 0.823,
        "samplingdesign": 0.847, "rnainverse": 0.979}


def from_cpu(row):
    """(b) 由 CPU 时间折算：wall × cpus × 实测利用率 ÷ 该长度单次 mfe 耗时。"""
    w = row.get("wall_sec")
    if not w:
        return None
    cpus = row.get("cpus") or 1
    util = UTIL.get(row.get("method"), 1.0)
    return (w * cpus * util) / mfe_cost_sec(row["length"])


def iter_rows(cell_dir):
    for p in sorted(glob.glob(os.path.join(cell_dir, "*.jsonl"))):
        if ".verified." in p:
            continue
        with open(p) as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    yield json.loads(ln)
                except json.JSONDecodeError:
                    continue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default="v2")
    args = ap.parse_args()

    print(f"benchmark = {args.bench}\n")
    print(f"{'方法':<18s} {'n':>5s} {'(a)计数折算':>14s} {'(b)CPU折算':>14s} {'b/a':>7s}")
    out = {}
    for d in sorted(glob.glob(os.path.join(RES, f"*_{args.bench}_B*"))):
        if not os.path.isdir(d):
            continue
        name = os.path.basename(d)
        meth = name.split(f"_{args.bench}_B")[0]
        if name.endswith("_fix"):
            meth += "(重跑)"
        a_vals, b_vals, both = [], [], []
        for r in iter_rows(d):
            if "length" not in r:
                continue
            a = from_counts(r)
            b = from_cpu(r)
            if a is not None:
                a_vals.append(a)
            if b is not None:
                b_vals.append(b)
            if a is not None and b is not None and a > 0:
                both.append(b / a)
        if not b_vals:
            continue
        ma = f"{statistics.median(a_vals):,.0f}" if a_vals else "测不到"
        mb = f"{statistics.median(b_vals):,.0f}"
        rr = f"{statistics.median(both):.2f}" if both else "—"
        print(f"{meth:<18s} {len(b_vals):5d} {ma:>14s} {mb:>14s} {rr:>7s}")
        out[meth] = {"n": len(b_vals),
                     "median_from_counts": statistics.median(a_vals) if a_vals else None,
                     "median_from_cpu": statistics.median(b_vals),
                     "median_ratio_b_over_a": statistics.median(both) if both else None}

    print()
    print("(b)/(a) 接近 1 说明 CPU 折算这条轴可信；明显大于 1 的部分是非折叠开销。")
    p = os.path.join(RES, f"mfe_equiv_{args.bench}.json")
    with open(p, "w") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    print(f"-> {os.path.relpath(p, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
