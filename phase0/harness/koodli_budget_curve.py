"""从 Koodli 的原始结果表 + 我们的重验证结果，画出**第一条 solved@B 曲线**（预算 = 墙钟时间）。

为什么能这么干：results.tsv 里有每题的 `Time`（秒）和我们重验证得到的 mfe/uMFE 命中。
搜索类方法命中即停，所以「命中时的耗时」就是该题的 cost-to-solve，
任意 B 的 solved@B = #{题 : 命中 且 cost ≤ B}（未命中 = 在该方法的时间上限处右删失）。

⚠️ 诚实声明（必须写进论文）：
  - 墙钟跨实现不可比（NEMO 是 C++，LEARNA/SentRNA 是 Python，DesiRNA 是 Python+C 混合）。
    这正是我们要换成**折叠调用数**的理由。本曲线只用于回答 Phase 0 的 gate：
    「10²–10⁵ 之间有没有两个数量级的靶区」。
  - 硬件也不同（Koodli 的机器 vs 我们的）。曲线形状可用，绝对横坐标不可引用。

用法：python -I harness/koodli_budget_curve.py --engine vienna2 --bench v2
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "third_party", "eterna100_bench", "data", "results.tsv")
VERIFIED = os.path.join(ROOT, "results", "koodli_verified.jsonl")

GRID = [1, 3, 10, 30, 100, 300, 1000, 3000, 10_000, 30_000, 86_400]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="vienna2", help="生成时用的能量模型目录（vienna1/vienna2）")
    ap.add_argument("--bench", default="v2", choices=["v1", "v2"])
    ap.add_argument("--criterion", default="mfe", choices=["mfe", "umfe"])
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "koodli_budget_curve.csv"))
    args = ap.parse_args()

    # 1) 我们重验证的命中（权威判据）
    hit_key = "umfe_hit" if args.criterion == "umfe" else "mfe_hit"
    hits = {}
    with open(VERIFIED) as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            r = json.loads(ln)
            benches = r.get("benchmarks") or []
            if args.bench not in benches or r.get("gen_engine") != args.engine:
                continue
            hits[(r.get("method"), r.get("variant"), r.get("id"))] = bool(r.get(hit_key))

    # 2) 原始表里的耗时
    csv.field_size_limit(10 ** 7)
    times: dict = {}
    with open(RESULTS, newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if row["Folder"] != args.engine:
                continue
            try:
                t = float(row["Time"])
            except (TypeError, ValueError):
                continue
            times[(row["Algorithm"], row["Variant"], row["Target Structure"])] = t

    # 结构 -> 题号
    import build_benchmarks as bb
    auth = bb.load_authoritative()
    s2id = {d["target_structure"]: pid for pid, d in auth[args.bench].items()}

    cost: dict = defaultdict(dict)  # (method,variant) -> {id: (time, solved)}
    for (alg, var, struct), t in times.items():
        pid = s2id.get(struct)
        if pid is None:
            continue
        solved = hits.get((alg, var, pid))
        if solved is None:
            continue
        cost[(alg, var)][pid] = (t, solved)

    rows = []
    for (alg, var), d in sorted(cost.items()):
        for B in GRID:
            n = sum(1 for t, s in d.values() if s and t <= B)
            rows.append({"method": alg, "variant": var, "engine": args.engine,
                         "benchmark": args.bench, "criterion": args.criterion,
                         "B_seconds": B, "solved": n, "n_puzzles": len(d)})
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"Eterna100-{args.bench.upper()} · 生成引擎 {args.engine} · 判据 {args.criterion.upper()}"
          f" · 预算 = 每题墙钟秒数")
    hdr = f"{'method':13s}{'variant':24s}" + "".join(f"{b:>7d}" for b in GRID)
    print(hdr)
    print("-" * len(hdr))
    for (alg, var), d in sorted(cost.items(), key=lambda kv: -sum(1 for t, s in kv[1].values() if s)):
        line = f"{alg:13s}{var[:23]:24s}"
        for B in GRID:
            line += f"{sum(1 for t, s in d.values() if s and t <= B):7d}"
        print(line)
    print(f"\n-> {args.out}")

    # Phase 0 的 gate：不同预算下排名是否换位
    print("\n=== gate 判定：排名随预算换位了吗 ===")
    for B in (10, 100, 1000, 10_000, 86_400):
        rank = sorted(((sum(1 for t, s in d.values() if s and t <= B), f"{a}/{v}")
                       for (a, v), d in cost.items()), reverse=True)[:3]
        print(f"  B={B:6d}s 前三: " + ", ".join(f"{name}={n}" for n, name in rank))
    return 0


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(ROOT, "harness"))
    raise SystemExit(main())
