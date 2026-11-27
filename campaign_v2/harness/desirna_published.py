"""把 DesiRNA 仓库自带的 benchmark 结果转成统一格式，以便在我们的环境下重验证。

为什么重要：DesiRNA 仓库里有 **按预算分档** 的结果文件
    Eterna100V{1,2}_{1min,1h,24h,all}_results.txt
也就是说「solved@B」这个数**已经有人报过了**（3 个档位），
baseline_plan.md §0 的「这个数现有文献全部没有」需要改写。

文件格式有两种：
    >eteV1_01.txt,<序列>,<目标结构>
    >eteV2_71.txt,True,10,<序列>,<目标结构>,<折叠结构>
统一取「最后一个像序列的字段」与「第一个像结构的字段」。

用法：python -I harness/desirna_published.py --out data/desirna/published.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(ROOT, "third_party", "desirna", "eterna_benchmark")
SEQ_RE = re.compile(r"^[ACGU]+$")
STRUCT_RE = re.compile(r"^[.()]+$")


def parse_line(ln: str):
    ln = ln.strip().lstrip(">")
    if not ln:
        return None
    parts = ln.split(",")
    name = parts[0]
    seq = next((p for p in reversed(parts) if SEQ_RE.match(p.strip())), None)
    struct = next((p for p in parts if STRUCT_RE.match(p.strip())), None)
    if not seq or not struct:
        return None
    m = re.search(r"_(\d+)", name)   # eteV1_01.txt -> 1（不能用第一个数字，那会取到 V1 的 1）
    pid = int(m.group(1)) if m else None
    return pid, seq.strip(), struct.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "desirna", "published.jsonl"))
    args = ap.parse_args()

    sys.path.insert(0, os.path.join(ROOT, "harness"))
    from build_benchmarks import load_authoritative
    auth = load_authoritative()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    n = 0
    tiers = {}
    with open(args.out, "w") as out:
        for ver in ("V1", "V2"):
            for tier in ("1min", "1h", "24h", "all"):
                p = os.path.join(BENCH, f"Eterna100{ver}_benchmark_results",
                                 f"Eterna100{ver}_{tier}_results.txt")
                if not os.path.exists(p):
                    continue
                cnt = 0
                for ln in open(p):
                    rec = parse_line(ln)
                    if not rec:
                        continue
                    pid, seq, struct = rec
                    ref = auth[ver.lower()].get(pid)
                    # 用他们文件里的目标结构；同时标注它与权威表是否一致
                    matches_auth = bool(ref and ref["target_structure"] == struct)
                    out.write(json.dumps({
                        "id": pid,
                        "target_structure": struct,
                        "designed_sequence": seq,
                        "method": "desirna_published",
                        "variant": f"{ver.lower()}_{tier}",
                        "benchmark": ver.lower(),
                        "benchmarks": [ver.lower()],
                        "gen_engine": "desirna_repo",
                        "target_matches_authoritative": matches_auth,
                        "source": f"desirna_repo/{os.path.basename(p)}",
                    }) + "\n")
                    cnt += 1
                    n += 1
                tiers[f"{ver}_{tier}"] = cnt
    print("各档条数:", tiers)
    print("推出的累计 solved（按他们自己的口径）:")
    for ver in ("V1", "V2"):
        c1 = tiers.get(f"{ver}_1min", 0)
        c2 = tiers.get(f"{ver}_1h", 0)
        c3 = tiers.get(f"{ver}_24h", 0)
        print(f"  {ver}: 1min {c1} | 1h {c1+c2} | 24h {c1+c2+c3} | all 文件 {tiers.get(f'{ver}_all', 0)}")
    print(f"-> {args.out}（{n} 条，待 harness/verify.py 在 Turner 2004 下重验证）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
