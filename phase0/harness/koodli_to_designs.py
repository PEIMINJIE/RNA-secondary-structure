"""把 Koodli 仓库的原始结果表 (eterna100_bench/data/results.tsv) 转成统一 designs.jsonl，
以便在我们自己的 ViennaRNA 2.8.0 + Turner 2004 下**重新验证**（生成/验证解耦协议，baseline_plan.md §1.1）。

这批数据是免费的：它含 NEMO / SentRNA / EternaBrain / LEARNA 等方法的**原始序列**，
不是论文里被抽取过的表格数字。重验证后可以直接回答 baseline_plan.md §6 的待核 #1–#3。

注意：Folder 列 = 他们生成时用的能量模型（vienna1 / vienna2），不是 benchmark 版本。
benchmark 版本靠 Target Structure 与权威表精确匹配得到（可能同时属于 V1 和 V2，因为 69 题两版相同）。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "harness"))
from build_benchmarks import load_authoritative  # noqa: E402

RESULTS = os.path.join(ROOT, "third_party", "eterna100_bench", "data", "results.tsv")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=RESULTS)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "koodli", "designs.jsonl"))
    args = ap.parse_args()

    auth = load_authoritative()
    index: dict[str, list[tuple[str, int, str]]] = {}
    for ver in ("v1", "v2"):
        for pid, d in auth[ver].items():
            index.setdefault(d["target_structure"], []).append((ver, pid, d["name"]))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    n_in = n_out = n_unmatched = 0
    unmatched_lengths = {}
    csv.field_size_limit(10_000_000)
    with open(args.results, newline="") as fh, open(args.out, "w") as out:
        for row in csv.DictReader(fh, delimiter="\t"):
            n_in += 1
            tgt = (row.get("Target Structure") or "").strip()
            seq = (row.get("Sequence") or "").strip()
            hits = index.get(tgt)
            if not hits:
                n_unmatched += 1
                unmatched_lengths[len(tgt)] = unmatched_lengths.get(len(tgt), 0) + 1
                continue
            vers = sorted({v for v, _, _ in hits})
            pid = hits[0][1]
            name = hits[0][2]
            rec = {
                "id": pid,
                "puzzle_name": name,
                "target_structure": tgt,
                "designed_sequence": seq,
                "method": (row.get("Algorithm") or "").strip(),
                "variant": (row.get("Variant") or "").strip(),
                "gen_engine": (row.get("Folder") or "").strip(),   # vienna1 / vienna2
                "benchmarks": vers,                                # ['v1'] / ['v2'] / ['v1','v2']
                "trial": row.get("Trial"),
                "time_reported": row.get("Time"),
                "success_reported": row.get("Success"),
                "source": "koodli_results.tsv",
            }
            out.write(json.dumps(rec) + "\n")
            n_out += 1
    print(f"rows in={n_in} written={n_out} unmatched={n_unmatched}")
    if unmatched_lengths:
        print("unmatched target lengths (len: count):", dict(sorted(unmatched_lengths.items())[:20]))
    print("->", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
