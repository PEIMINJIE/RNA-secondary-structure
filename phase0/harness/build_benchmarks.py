"""从各来源构建**权威** Eterna100-V1 / V2 benchmark 文件，并做跨来源一致性审计。

权威来源：third_party/eterna100_bench/data/eterna100_puzzles.tsv（Koodli 的仓库，V2 的定义处）
对照来源：
  - third_party/samplingdesign/data/eterna100_v{1,2}.txt
  - third_party/rna_design_lm/test/eterna100.jsonl / eterna100v2.jsonl
  - third_party/samfeo/data/eterna/eterna100.txt

产出：
  data/eterna100/eterna100_v1.jsonl, eterna100_v2.jsonl   （id, name, target_structure, length, sample_solution_*）
  data/eterna100/source_audit.json                        （逐题逐来源是否一致）

任一来源与权威表不一致，都必须在论文里交代 —— 审稿人（尤其 Huang 组）会查。
"""

from __future__ import annotations

import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TP = os.path.join(ROOT, "third_party")
OUT = os.path.join(ROOT, "data", "eterna100")

AUTH = os.path.join(TP, "eterna100_bench", "data", "eterna100_puzzles.tsv")


def load_authoritative() -> dict:
    v1, v2 = {}, {}
    with open(AUTH, newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            pid = int(row["Puzzle #"])
            common = {"id": pid, "name": row["Puzzle Name"].strip()}
            s1 = row["Secondary Structure V1"].strip()
            s2 = row["Secondary Structure V2"].strip()
            v1[pid] = {
                **common,
                "target_structure": s1,
                "length": len(s1),
                "sample_solution_vienna2": row["Sample Solution (V1/Vienna2)"].strip(),
                "sample_solution_vienna1": row["Sample Solution (V1/Vienna1)"].strip(),
                "eterna_id_vienna2": row["Eterna ID (V1/Vienna2)"].strip(),
                "benchmark": "eterna100_v1",
            }
            v2[pid] = {
                **common,
                "target_structure": s2,
                "length": len(s2),
                "sample_solution_vienna2": row["Sample Solution (V2/Vienna2)"].strip(),
                "sample_solution_vienna1": row["Sample Solution (V2/Vienna1)"].strip(),
                "eterna_id_vienna2": row["Eterna ID (V2/Vienna2)"].strip(),
                "benchmark": "eterna100_v2",
            }
    return {"v1": v1, "v2": v2}


def load_txt_pairs(path: str) -> dict:
    """'<id> <structure>' 每行一条。没有 id 列时返回 {行号: 结构}，审计里按**结构内容**比对。"""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path) as fh:
        for ln in fh:
            parts = ln.split()
            if len(parts) >= 2 and parts[0].isdigit():
                out[int(parts[0])] = parts[1].strip()
            elif len(parts) == 1 and parts[0] and parts[0][0] in ".()":
                out[len(out) + 1] = parts[0].strip()
    return out


ID_LESS = {"samfeo_e100"}  # 这些来源的文件只有结构、没有题号 -> 只能按内容比对


def load_jsonl_structs(path: str) -> dict:
    out = {}
    if not os.path.exists(path):
        return out
    with open(path) as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            d = json.loads(ln)
            out[int(d["id"])] = d["target_structure"].strip()
    return out


def audit(auth: dict) -> dict:
    sources = {
        "samplingdesign_v1": load_txt_pairs(os.path.join(TP, "samplingdesign", "data", "eterna100_v1.txt")),
        "samplingdesign_v2": load_txt_pairs(os.path.join(TP, "samplingdesign", "data", "eterna100_v2.txt")),
        "rna_design_lm_v1": load_jsonl_structs(os.path.join(TP, "rna_design_lm", "test", "eterna100.jsonl")),
        "rna_design_lm_v2": load_jsonl_structs(os.path.join(TP, "rna_design_lm", "test", "eterna100v2.jsonl")),
        "samfeo_e100": load_txt_pairs(os.path.join(TP, "samfeo", "data", "eterna", "eterna100.txt")),
    }
    rep: dict = {"n_authoritative": {k: len(v) for k, v in auth.items()}, "sources": {}}
    for name, src in sources.items():
        if name in ID_LESS:
            # 只有结构、没有题号：按内容匹配，并报出它到底是 V1 还是 V2
            by_content = {}
            for v in ("v1", "v2"):
                S = {d["target_structure"] for d in auth[v].values()}
                by_content[v] = sum(1 for s in src.values() if s in S)
            best = max(by_content, key=by_content.get)
            rep["sources"][name] = {
                "compared_against": "content-only (文件里没有题号)",
                "n": len(src),
                "n_match_by_content": by_content,
                "verdict": f"这是 Eterna100-{best.upper()}（{by_content[best]}/{len(src)} 条结构内容吻合）",
            }
            continue
        ver = "v2" if name.endswith("_v2") else "v1"
        ref = auth[ver]
        match = sorted(i for i, s in src.items() if i in ref and ref[i]["target_structure"] == s)
        mismatch = {
            i: {"source": s, "authoritative": ref[i]["target_structure"]}
            for i, s in src.items()
            if i in ref and ref[i]["target_structure"] != s
        }
        # samfeo 的单一文件：同时和 v1/v2 比
        alt = None
        if name == "samfeo_e100":
            for v in ("v1", "v2"):
                m = sum(1 for i, s in src.items() if i in auth[v] and auth[v][i]["target_structure"] == s)
                alt = {**(alt or {}), v: m}
        rep["sources"][name] = {
            "compared_against": ver,
            "n": len(src),
            "n_match": len(match),
            "n_mismatch": len(mismatch),
            "missing_ids": sorted(set(ref) - set(src))[:120],
            "mismatch_detail": mismatch,
            **({"match_count_per_version": alt} if alt else {}),
        }
    # V1 与 V2 到底有多少题不同（SamplingDesign 的 v2 文件只有 19 行，很可能就是差异集）
    diff = sorted(i for i in auth["v1"] if auth["v1"][i]["target_structure"] != auth["v2"][i]["target_structure"])
    rep["v1_vs_v2"] = {"n_different": len(diff), "different_ids": diff}
    return rep


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    auth = load_authoritative()
    for ver in ("v1", "v2"):
        p = os.path.join(OUT, f"eterna100_{ver}.jsonl")
        with open(p, "w") as fh:
            for pid in sorted(auth[ver]):
                fh.write(json.dumps(auth[ver][pid]) + "\n")
        print(f"wrote {p}: {len(auth[ver])} puzzles, "
              f"L {min(d['length'] for d in auth[ver].values())}-{max(d['length'] for d in auth[ver].values())}")
    rep = audit(auth)
    ap = os.path.join(OUT, "source_audit.json")
    with open(ap, "w") as fh:
        json.dump(rep, fh, indent=2, sort_keys=True)
    print(f"wrote {ap}")
    print(f"V1 vs V2 结构不同的题数: {rep['v1_vs_v2']['n_different']} -> {rep['v1_vs_v2']['different_ids']}")
    for name, d in rep["sources"].items():
        if "verdict" in d:
            print(f"  {name:22s} n={d['n']:3d} {d['verdict']}")
        else:
            print(f"  {name:22s} n={d['n']:3d} match={d['n_match']:3d} mismatch={d['n_mismatch']:3d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
