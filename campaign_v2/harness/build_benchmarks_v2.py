#!/usr/bin/env python3
"""建 campaign_spec v2 要的另外两个 benchmark：Rfam-Taneda 与 ArchiveII。

同时做来源交叉审计（和 Eterna100 一样的做法）：
  - Rfam-Taneda 的 27 题 / 29 题分歧：把各上游自带的拷贝逐题比对，指出差的是哪几题
  - ArchiveII：核对题数与长度分布

输出：
  data/taneda/taneda29.jsonl、data/taneda/taneda27.jsonl
  data/archiveii/archiveii1144.jsonl
  data/taneda/source_audit.json
"""
from __future__ import annotations

import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TP = os.path.join(ROOT, "third_party")


def read_lines(p):
    """读 dot-bracket 一行一题。容忍「<题号> <结构>」这种带前导 id 列的写法
    （SamplingDesign 的 rfam27.txt 就是这个格式），返回 (结构列表, 题号列表)。"""
    structs, ids = [], []
    with open(p) as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            parts = ln.split()
            if len(parts) == 2 and parts[0].isdigit():
                ids.append(int(parts[0]))
                structs.append(parts[1])
            else:
                structs.append(parts[0] if parts else ln)
    return (structs, ids) if ids else (structs, None)


def read_jsonl_structs(p):
    out = []
    with open(p) as fh:
        for ln in fh:
            ln = ln.strip()
            if ln:
                d = json.loads(ln)
                out.append(d.get("target_structure") or d.get("structure"))
    return out


def valid_db(s):
    """括号是否配平，且只含 .()"""
    if set(s) - set(".()"):
        return False
    d = 0
    for c in s:
        if c == "(":
            d += 1
        elif c == ")":
            d -= 1
            if d < 0:
                return False
    return d == 0


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  -> {os.path.relpath(path, ROOT)}  ({len(rows)} 题)")


def main():
    audit = {}

    # ---------------- Rfam-Taneda ----------------
    print("=== Rfam-Taneda：27 题 vs 29 题 ===")
    srcs = {
        "samfeo_rf29": os.path.join(TP, "samfeo", "data", "Rfam", "rf29.txt"),
        "samfeo_rf27": os.path.join(TP, "samfeo", "data", "Rfam", "rf27.txt"),
        "samplingdesign_rfam27": os.path.join(TP, "samplingdesign", "data", "rfam27.txt"),
        "rna_design_lm_Rfam27": os.path.join(TP, "rna_design_lm", "test", "Rfam27.jsonl"),
    }
    got, src_ids = {}, {}
    for k, p in srcs.items():
        if not os.path.exists(p):
            print(f"  ⚠️ 缺 {k}: {p}")
            continue
        if p.endswith(".jsonl"):
            got[k] = read_jsonl_structs(p)
        else:
            got[k], src_ids[k] = read_lines(p)
        extra_note = f"，自带题号 {min(src_ids[k])}–{max(src_ids[k])}" if src_ids.get(k) else ""
        print(f"  {k:26s} {len(got[k])} 题{extra_note}")

    s29 = got["samfeo_rf29"]
    s27 = got["samfeo_rf27"]
    set29, set27 = set(s29), set(s27)
    extra = [s for s in s29 if s not in set27]
    missing = [s for s in s27 if s not in set29]
    print(f"\n  29 题里比 27 题多出来的: {len(extra)} 条")
    for s in extra:
        print(f"    - 第 {s29.index(s) + 1} 行（rf29 内序号），长度 {len(s)}，配对数 {s.count('(')}")
        print(f"      {s[:90]}{'...' if len(s) > 90 else ''}")
    print(f"  27 题里有、29 题里没有的: {len(missing)} 条 "
          f"→ {'27 是 29 的真子集' if not missing else '两边互有出入，要当心'}")

    # 其余两个来源和谁一致？
    cross = {}
    for k in ("samplingdesign_rfam27", "rna_design_lm_Rfam27"):
        if k not in got:
            continue
        v = got[k]
        cross[k] = {
            "n": len(v),
            "n_in_rf27": sum(1 for s in v if s in set27),
            "n_in_rf29": sum(1 for s in v if s in set29),
            "identical_to_rf27_in_order": v == s27,
        }
        # 自带题号的来源：检查它的题号是不是 rf27 / rf29 的行号
        if src_ids.get(k):
            for ref_name, ref in (("rf27", s27), ("rf29", s29)):
                ok = sum(1 for i, s in zip(src_ids[k], v)
                         if 1 <= i <= len(ref) and ref[i - 1] == s)
                cross[k][f"ids_match_{ref_name}_lineno"] = f"{ok}/{len(v)}"
                print(f"    {k} 的自带题号当作 {ref_name} 行号：对上 {ok}/{len(v)}")
        print(f"  {k}: {cross[k]['n_in_rf27']}/{len(v)} 落在 rf27 里，"
              f"{cross[k]['n_in_rf29']}/{len(v)} 落在 rf29 里，"
              f"逐行完全相同于 rf27: {cross[k]['identical_to_rf27_in_order']}")

    bad = [i + 1 for i, s in enumerate(s29) if not valid_db(s)]
    print(f"  括号配平自检（rf29）：{'全部通过' if not bad else f'第 {bad} 行有问题'}")

    for name, structs in (("taneda29", s29), ("taneda27", s27)):
        rows = [{"id": i + 1, "name": f"{name}_{i + 1}", "target_structure": s,
                 "length": len(s), "n_pairs": s.count("("), "benchmark": name}
                for i, s in enumerate(structs)]
        L = [r["length"] for r in rows]
        print(f"  {name}: 长度 min {min(L)} / 中位 {statistics.median(L):.0f} / max {max(L)}")
        write_jsonl(os.path.join(ROOT, "data", "taneda", f"{name}.jsonl"), rows)

    audit["taneda"] = {
        "n": {k: len(v) for k, v in got.items()},
        "rf27_is_subset_of_rf29": not missing,
        "extra_in_rf29": [{"row_in_rf29": s29.index(s) + 1, "length": len(s),
                           "n_pairs": s.count("("), "structure": s} for s in extra],
        "cross_sources": cross,
    }

    # ---------------- ArchiveII ----------------
    print("\n=== ArchiveII ===")
    p = os.path.join(TP, "rna_undesign", "data", "archiveii1144.txt")
    a, _ = read_lines(p)
    print(f"  {len(a)} 题（来源 rna_undesign/data/archiveii1144.txt）")
    L = [len(s) for s in a]
    med = statistics.median(L)
    print(f"  长度 min {min(L)} / 中位 {med:.0f} / max {max(L)}")
    print(f"  规格书写的是「最长 234nt，中位 116nt」→ "
          f"{'✅ 对上' if max(L) == 234 and round(med) == 116 else '⚠️ 对不上，见上面实测'}")
    dup = len(a) - len(set(a))
    print(f"  重复结构: {dup} 条")
    bad = [i + 1 for i, s in enumerate(a) if not valid_db(s)]
    print(f"  括号配平自检：{'全部通过' if not bad else f'第 {bad[:5]} 行有问题（共 {len(bad)}）'}")
    rows = [{"id": i + 1, "name": f"archiveii_{i + 1}", "target_structure": s,
             "length": len(s), "n_pairs": s.count("("), "benchmark": "archiveii1144"}
            for i, s in enumerate(a)]
    write_jsonl(os.path.join(ROOT, "data", "archiveii", "archiveii1144.jsonl"), rows)
    audit["archiveii"] = {"n": len(a), "len_min": min(L), "len_median": med, "len_max": max(L),
                          "n_duplicate_structures": dup,
                          "spec_claim_matches": bool(max(L) == 234 and round(med) == 116)}

    ap = os.path.join(ROOT, "data", "taneda", "source_audit.json")
    with open(ap, "w") as fh:
        json.dump(audit, fh, indent=2, ensure_ascii=False, sort_keys=True)
    print(f"\n审计报告 -> {os.path.relpath(ap, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
