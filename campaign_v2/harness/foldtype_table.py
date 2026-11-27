#!/usr/bin/env python3
"""从 Phase 0 已落盘的数据里，抽出 campaign_spec v2 §1 要的「分类型折叠调用数」。

能填到什么程度，取决于 Phase 0 当时用的是哪种计数：
  NEMO            C++ omp atomic 计数器         → mfe 精确；pf/subopt 结构上就是 0
  SAMFEO          Python monkeypatch 分类型落盘 → mfe/pf/subopt 全部精确（229 个 counts 文件）
  RNAinverse-pf   monkeypatch 只看得到外层 inverse_* 调用，C 内部折叠不可见 → 只有下界
  DesiRNA         无计数（wall ÷ 标定）         → 填不了
  SamplingDesign  无计数（wall ÷ 标定）         → 填不了

输出 results/foldtype_phase0.csv
"""
from __future__ import annotations

import csv
import glob
import json
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = os.path.join(ROOT, "results", "solvedB")


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def raw_rows(method):
    out = []
    for f in sorted(glob.glob(os.path.join(SB, f"{method}_v2_B100000", "seed*_chunk*.jsonl"))):
        if ".verified." in f:
            continue
        with open(f) as fh:
            for ln in fh:
                if ln.strip():
                    out.append(json.loads(ln))
    return out


def main():
    rows = []

    # ---- NEMO：C++ 计数器，精确 ----
    r = raw_rows("nemo")
    folds = [x.get("fold_calls_used") for x in r]
    evals = [x.get("eval_calls_used") for x in r]
    rows.append({
        "method": "NEMO", "n_runs": len(r),
        "mfe_median": med(folds), "pf_median": 0, "subopt_median": 0,
        "eval_median": med(evals),
        "counting": "精确（C++ omp atomic 计数器）",
        "note": "NEMO 只做 MFE 折叠；eval 是 O(L) 查表，单独记，不并入预算主轴",
    })

    # ---- SAMFEO：monkeypatch 分类型落盘 ----
    cfs = sorted(glob.glob(os.path.join(SB, "samfeo_v2_B100000", "_work_samfeo_s*",
                                        "samfeo_counts_*.json")))
    per = {"mfe": [], "pf": [], "subopt": [], "pr": [], "ned": [], "sample": []}
    for f in cfs:
        try:
            c = json.load(open(f)).get("counts", {})
        except Exception:
            continue
        for k in per:
            per[k].append(c.get(k, 0))
    rows.append({
        "method": "SAMFEO", "n_runs": len(cfs),
        "mfe_median": med(per["mfe"]), "pf_median": med(per["pf"]),
        "subopt_median": med(per["subopt"]), "eval_median": None,
        "counting": "精确（Python monkeypatch，分类型）",
        "note": (f"另有 pr（碱基对概率）中位 {med(per['pr'])}；"
                 f"只有 {len(cfs)}/500 次运行留下了计数文件——撞墙钟被杀的那些没来得及落盘"),
    })

    # ---- RNAinverse-pf：只有外层可见 ----
    r = raw_rows("rnainverse")
    rows.append({
        "method": "RNAinverse-pf", "n_runs": len(r),
        "mfe_median": None,
        "pf_median": med([x.get("fold_calls_counted") for x in r]),
        "subopt_median": 0, "eval_median": None,
        "counting": "下界（C 内部折叠不可见）",
        "note": "inverse_pf_fold 在 C 里自己折，Python 层只数得到外层调用次数；填的是 pf 的下界",
    })

    # ---- DesiRNA / SamplingDesign：Phase 0 没有真计数 ----
    for m, label in (("desirna", "DesiRNA"), ("samplingdesign", "SamplingDesign")):
        r = raw_rows(m)
        rows.append({
            "method": label, "n_runs": len(r),
            "mfe_median": None, "pf_median": None, "subopt_median": None, "eval_median": None,
            "counting": "估计（wall ÷ 标定的单次折叠耗时）",
            "note": (f"Phase 0 无分类型计数；总数估计中位 "
                     f"{med([x.get('fold_calls_used') for x in r])}。正式跑需要套 run_counted.py"),
        })

    out = os.path.join(ROOT, "results", "foldtype_phase0.csv")
    cols = ["method", "n_runs", "mfe_median", "pf_median", "subopt_median", "eval_median",
            "counting", "note"]
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    w = max(len(r["method"]) for r in rows)
    print(f"{'方法'.ljust(w)}  {'mfe':>9} {'pf':>9} {'subopt':>8}  计数方式")
    for r in rows:
        f = lambda v: ("—" if v is None else f"{v:,.0f}")
        print(f"{r['method'].ljust(w)}  {f(r['mfe_median']):>9} {f(r['pf_median']):>9} "
              f"{f(r['subopt_median']):>8}  {r['counting']}")
    print(f"\n-> {os.path.relpath(out, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
