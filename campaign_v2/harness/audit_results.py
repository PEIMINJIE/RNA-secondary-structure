#!/usr/bin/env python3
"""体检 results/campaignV2 下的所有产物。

为什么需要：发现过两个会静默污染数据的 bug ——
  A) `work_root` 只按 (method, bench, seed) 命名，同一 seed 的不同 chunk 并发共用，
     先跑完的那个 `rmtree(work_root)` 会删掉还在跑的那个的工作目录；
  B) pilot 与 full 的输出路径都是 `seed0_chunk0.jsonl`，并发写出半行 JSON。
两个 bug 都不会让作业失败（Slurm 报 COMPLETED 0:0），只能靠体检发现。

检查项：
  1. 不可解析的行（并发写的直接证据）
  2. (seed, id) 重复（两次运行混进同一个文件）
  3. 行数与期望题数不符
  4. raw 有、verified 没有的行（verify 没跑完）
  5. designed_sequence 为空但 stop_reason 看着正常（工作目录被删的典型表现，
     也会抓到上游方法自己提前退出、harness 没接到序列的情况）
  6. rc 非 0 的行 —— 上游进程异常退出。只查空序列是不够的：一个方法可以先吐出几条
     序列再崩，那样行里有序列、看起来正常，实际上只跑了一小部分预算，会被当成
     「跑满预算的一次运行」。实测 SAMFEO 在 Rfam-Taneda 上有 2/464 次这样崩掉
     （np.exp 溢出 → NaN 概率，见 reports/samfeo_upstream_crash.md）。

已归档的上游缺陷：写进 `KNOWN_UPSTREAM` 的 (格子, seed, 题号, rc) 不计入退出码，
因为那是上游方法自己的 bug、已经写成报告、且对表里的数没有影响。豁免钉死到单行、
并且要求该行**没有序列**，所以一个新的崩溃或一个「崩在中途却仍吐出序列」的行照样会失败。
这些行在表里按完整计数印出，另起一节逐行列出，必须随表一起交出去。

被取代的格子：如果存在 `<格子>_fix`，那么 `<格子>` 就是重跑前的那次，留着当证据
（预算实现度分析要用），它的已知缺陷不该让闸门失败。所以这类格子单列一节报告，
不计入退出码 —— 但照样把数字印出来，不做静默。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "results", "campaignV2")
EXPECT_PUZZLES = {"v2": 100, "v1": 100, "taneda29": 29, "taneda27": 27,
                  "archiveii": 1144}
EXPECT_SEEDS = {"v2": 8, "v1": 8, "taneda29": 16, "archiveii": 1}

# 已知并已归档的上游缺陷。只有写进这里的 (格子, seed, 题号, rc) 才不计入退出码 ——
# 否则闸门会永远卡在同一批行上，而「把这项检查关掉」等于把整类问题变成盲区。
#
# samfeo_taneda29_B10000_fix 的这 2 行：SAMFEO 自己的 softmax 溢出
# （main.py:298 `np.exp(score_list)`，score 到 2.89e8 → inf/inf = NaN → np.random.choice 拒绝），
# 可稳定复现，见 reports/samfeo_upstream_crash.md。不改上游（baseline 必须是官方实现），
# 两行按未解计入，题 16 / 题 23 在全部 16 个 seed 下都是 0/16，所以表里的数一个都不变。
KNOWN_UPSTREAM = {
    ("samfeo_taneda29_B10000_fix", 4, 16, 1): "reports/samfeo_upstream_crash.md",
    ("samfeo_taneda29_B10000_fix", 12, 23, 1): "reports/samfeo_upstream_crash.md",
}


def known_upstream(cell, row):
    """这一行是否属于已归档的上游缺陷。

    两道闸：①(格子, seed, 题号, rc) 必须逐项对上；②这一行必须**没有序列**。
    第二道是关键 —— 一个方法可以先吐出几条序列再崩，那样预算没跑满却看不出来，
    是横向比较里最危险的行，绝不豁免。
    """
    key = (cell, row.get("seed"), row.get("id"), row.get("rc"))
    if key not in KNOWN_UPSTREAM:
        return False
    return not (row.get("designed_sequence") or "").strip()


def scan_file(path):
    good, bad = [], 0
    with open(path) as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            try:
                good.append(json.loads(ln))
            except json.JSONDecodeError:
                bad += 1
    return good, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix-list", default="",
                    help="把需要重跑的 (cell, seed, chunk) 写到这个文件")
    args = ap.parse_args()

    cells = sorted(d for d in glob.glob(os.path.join(RES, "*_B*"))
                   if os.path.isdir(d))
    cell_names = {os.path.basename(d) for d in cells}
    problems = []
    sup_problems = []       # 被 _fix 取代的格子的问题：报告但不计入退出码
    excused = []            # 已归档的上游缺陷：报告但不计入退出码
    rerun = []
    print(f"{'格子':<28s} {'行':>6s} {'坏行':>5s} {'重复':>5s} {'缺verify':>8s} "
          f"{'空序列':>6s} {'rc≠0':>5s} {'已归档':>5s}")
    for cd in cells:
        name = os.path.basename(cd)
        bench = None
        for b in EXPECT_PUZZLES:
            if f"_{b}_B" in name:
                bench = b
                break
        raw_rows, raw_bad, ver_keys = [], 0, set()
        per_file_bad = {}
        for p in sorted(glob.glob(os.path.join(cd, "*.jsonl"))):
            rows, bad = scan_file(p)
            if ".verified." in p:
                ver_keys |= {(r.get("seed"), r.get("id")) for r in rows}
            else:
                raw_rows += rows
                raw_bad += bad
            if bad:
                per_file_bad[os.path.basename(p)] = bad
                stem = os.path.basename(p).replace(".verified", "").replace(".jsonl", "")
                rerun.append((name, stem))

        keys = Counter((r.get("seed"), r.get("id")) for r in raw_rows)
        dup = {k: c for k, c in keys.items() if c > 1}
        missing_ver = [k for k in keys if k not in ver_keys]
        empty_all = [r for r in raw_rows
                     if not r.get("designed_sequence")
                     and r.get("stop_reason") in
                     ("solved_or_exhausted", "steps_exhausted_or_solved",
                      "solved_or_budget")]
        # rc=7 是我们自己的折叠预算保险丝（正常停止），None 是墙钟保险丝（已单独标 censored）
        crash_all = [r for r in raw_rows if r.get("rc") not in (0, 7, None)]
        # 已归档的上游缺陷单列出来：表里照样按完整计数印（不做静默），
        # 但不进「发现问题」，否则闸门会永远卡在同一批行上。
        exc = [r for r in crash_all if known_upstream(name, r)]
        for r in exc:
            excused.append((name, r.get("seed"), r.get("id"), r.get("rc"),
                            KNOWN_UPSTREAM[(name, r.get("seed"), r.get("id"),
                                            r.get("rc"))]))
        empty_seq = [r for r in empty_all if not known_upstream(name, r)]
        crashed = [r for r in crash_all if not known_upstream(name, r)]
        sup = f"{name}_fix" in cell_names
        print(f"{name:<28s} {len(raw_rows):6d} {raw_bad:5d} {len(dup):5d} "
              f"{len(missing_ver):8d} {len(empty_all):6d} {len(crash_all):5d} "
              f"{len(exc):5d}"
              f"{'   ← 已被 _fix 取代' if sup else ''}")
        bag = sup_problems if sup else problems
        if per_file_bad:
            bag.append(f"  {name}: 坏行 {per_file_bad}")
        if dup:
            ex = list(dup.items())[:3]
            bag.append(f"  {name}: (seed,id) 重复 {len(dup)} 个，例 {ex}")
        if bench and EXPECT_SEEDS.get(bench):
            exp = EXPECT_PUZZLES[bench] * EXPECT_SEEDS[bench]
            if len(keys) != exp:
                bag.append(f"  {name}: 去重后 {len(keys)} 行，期望 {exp}")
        # 这两项原来只印在表里、不进 problems，于是闸门会放过它们。
        # samfeo_taneda29_B10000_fix 的 2 个空序列就是这样溜过去的。
        if missing_ver:
            bag.append(f"  {name}: {len(missing_ver)} 行 raw 有但 verified 没有，"
                       f"例 {sorted(missing_ver)[:3]}")
        if empty_seq:
            ex = [(r.get("seed"), r.get("id")) for r in empty_seq][:5]
            bag.append(f"  {name}: {len(empty_seq)} 行 designed_sequence 为空而 "
                       f"stop_reason 看着正常，(seed,id) 例 {ex}")
        if crashed:
            ex = [(r.get("seed"), r.get("id"), r.get("rc")) for r in crashed][:5]
            with_seq = sum(1 for r in crashed if (r.get("designed_sequence") or "").strip())
            bag.append(f"  {name}: {len(crashed)} 行上游 rc≠0（其中 {with_seq} 行**仍有序列**"
                       f"，即崩在中途、预算没跑满却看不出来），(seed,id,rc) 例 {ex}")

    print()
    if problems:
        print("发现问题：")
        for s in problems:
            print(s)
    else:
        print("未发现问题 ✅")
    if sup_problems:
        print("\n被 _fix 取代的格子（留作证据，不计入退出码）：")
        for s in sup_problems:
            print(s)
    if excused:
        print("\n已归档的上游缺陷（不计入退出码，但必须随表交出去）：")
        for cell, sd, pid, rc, doc in sorted(excused, key=lambda t: (t[0], t[1], t[2])):
            print(f"  {cell}: seed={sd} 题={pid} rc={rc} → {doc}")

    if args.fix_list and rerun:
        with open(args.fix_list, "w") as fh:
            for cell, stem in sorted(set(rerun)):
                fh.write(f"{cell} {stem}\n")
        print(f"\n需重跑的分片 -> {args.fix_list}（{len(set(rerun))} 个）")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
