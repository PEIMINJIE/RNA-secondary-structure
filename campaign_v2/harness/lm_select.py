#!/usr/bin/env python3
"""把 RNA-Design-LM 的 N 条候选选成「一次运行的交付序列」，并按 spec §4 的口径记折叠数。

spec §4：「贪心解码的 LM → B = 0；LM best-of-N → B = N；只数方法用来做决策的折叠，
不数 benchmark 最后那一次评估折叠」。
所以：对每题的 N 条候选各折一次（这 N 次就是方法的决策成本，B = N），挑出命中的那条；
都没命中就挑碱基对距离最小的那条。被挑中的序列再交给 harness/verify.py 做权威重验证
（那一次评估折叠按 spec 不计入 B）。

N*seeds 条样本按顺序切成 seeds 份，每份当一次独立运行（采样是 i.i.d.，
切块与分别跑 seeds 次在统计上等价），这样就有了 spec §2 要的多 seed 均值±标准差。

并行：以 (题, seed) 块为单位。块与块之间完全独立，块内又没有任何随机性
（纯粹是「按顺序折到命中为止」），所以 --procs 不改变结果，只改变耗时 ——
这一点由 --repro-check 实测核对：对同一份解码文件，并行产出与串行产出逐字节相同。
必须并行的原因：Eterna100-V2 是 8,000,000 条候选，单线程实测要 26.8 h
（V1 的 800,000 条实测 2.66 h，两者平均 L³ 只差 1%，所以就是线性的 10 倍），
而后处理作业的限额是 12 h，且 select 是最后才落盘的 —— 撞限额等于全丢。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "harness"))

BENCHES = {
    "v2": "data/eterna100/eterna100_v2.jsonl",
    "v1": "data/eterna100/eterna100_v1.jsonl",
    "taneda29": "data/taneda/taneda29.jsonl",
    "taneda27": "data/taneda/taneda27.jsonl",
    "archiveii": "data/archiveii/archiveii1144.jsonl",
}


def bp_set(db: str):
    st, out = [], set()
    for i, c in enumerate(db):
        if c == "(":
            st.append(i)
        elif c == ")":
            if st:
                out.add((st.pop(), i))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decode", required=True, help="run_lm.py 产出的解码 jsonl")
    ap.add_argument("--bench", required=True, choices=sorted(BENCHES))
    ap.add_argument("--n-repeats", type=int, required=True, help="每份（每个 seed）的候选数 = B")
    ap.add_argument("--n-seeds", type=int, default=1)
    ap.add_argument("--flavor", default="slrl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--procs", type=int,
                    default=int(os.environ.get("SLURM_CPUS_PER_TASK", "1")),
                    help="并行进程数，默认取 SLURM_CPUS_PER_TASK。1 = 走串行路径")
    ap.add_argument("--repro-check", default="",
                    help="已有的串行产出；跑完后与之逐字节比对，不一致就非零退出")
    args = ap.parse_args()

    import RNA
    import rnaenv
    import foldcount
    rnaenv.pin_env()
    foldcount.install()

    meta = {json.loads(l)["id"]: json.loads(l)
            for l in open(os.path.join(ROOT, BENCHES[args.bench])) if l.strip()}

    cand = defaultdict(list)
    with open(args.decode) as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            d = json.loads(ln)
            s = (d.get("designed_sequence") or "").strip().upper()
            if s:
                cand[d["id"]].append(s)

    print(f"[select] {len(cand)} 题，候选总数 {sum(len(v) for v in cand.values()):,}")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)

    # 任务 = (题, seed) 块。先把 cand / meta 放进模块级全局，让 fork 出来的子进程
    # 直接继承（copy-on-write）—— 否则 800 万条候选要被 pickle 一遍。
    _G["cand"] = cand
    _G["meta"] = meta
    _G["tbp"] = {pid: bp_set(meta[pid]["target_structure"])
                 for pid in cand if pid in meta}
    _G["args"] = args

    tasks = [(pid, s_i) for pid in sorted(cand) if pid in meta
             for s_i in range(args.n_seeds)
             if cand[pid][s_i * args.n_repeats:(s_i + 1) * args.n_repeats]]
    print(f"[select] {len(tasks)} 个 (题,seed) 块，procs={args.procs}")

    t0 = time.time()
    rows = []
    if args.procs <= 1:
        for i, t in enumerate(tasks, 1):
            rows.append(_do_block(t))
            _tick(i, len(tasks), t0)
    else:
        import multiprocessing as mp
        # fork 才能继承上面那份候选；chunksize=1 是必须的 —— 块的成本差几个数量级
        # （第一条就命中 vs 折完一万条都没命中），静态切分会让大部分核空等。
        ctx = mp.get_context("fork")
        with ctx.Pool(args.procs) as pool:
            for i, r in enumerate(pool.imap_unordered(_do_block, tasks, chunksize=1), 1):
                rows.append(r)
                _tick(i, len(tasks), t0)

    # 并行是乱序回来的，按 (题, seed) 排回去，产出与串行路径逐行一致
    rows.sort(key=lambda r: (r["id"], r["seed"]))
    with open(args.out, "w") as out:
        for r in rows:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[select] 写出 {len(rows)} 行 -> {args.out}（{time.time() - t0:.0f} s）")

    if args.repro_check:
        import hashlib

        def h(p):
            return hashlib.sha256(open(p, "rb").read()).hexdigest()
        a, b = h(args.repro_check), h(args.out)
        print(f"[repro] 串行 {os.path.basename(args.repro_check)} sha256 {a[:16]}")
        print(f"[repro] 本次 {os.path.basename(args.out)} sha256 {b[:16]}")
        if a != b:
            print("[repro] ❌ 并行产出与串行产出不一致 —— 并行实现不可信，停下")
            return 8
        print("[repro] ✅ 逐字节相同")
    return 0


# --------------------------------------------------------------------------- #
# fork 共享的输入。放模块级是为了让子进程继承而不是 pickle。
_G: dict = {}


def _tick(i, n, t0):
    if i % 50 and i != n:
        return
    el = time.time() - t0
    eta = el / i * (n - i)
    print(f"[select] {i}/{n} 块　已用 {el / 60:.1f} min　预计还要 {eta / 60:.1f} min",
          flush=True)


def _do_block(task):
    """折一个 (题, seed) 块。块内无随机性，所以与串行路径结果相同。"""
    import RNA
    import foldcount

    pid, s_i = task
    args = _G["args"]
    m = _G["meta"][pid]
    target = m["target_structure"]
    tbp = _G["tbp"][pid]
    blk = _G["cand"][pid][s_i * args.n_repeats:(s_i + 1) * args.n_repeats]

    foldcount.reset()
    best_seq, best_d, hit = None, None, False
    for s in blk:
        if len(s) != len(target):
            continue
        fc = RNA.fold_compound(s)
        st, _ = fc.mfe()
        d = len(tbp ^ bp_set(st))
        if best_d is None or d < best_d:
            best_seq, best_d = s, d
        if d == 0:
            hit = True
            break              # 命中即停：后面的候选不用再折（省掉的折叠也如实少记）
    snap = foldcount.snapshot()["counts"]
    used = snap.get("mfe", 0) + snap.get("pf", 0) + snap.get("subopt", 0)
    return {
        "id": pid, "puzzle_name": m.get("name"), "benchmark": args.bench,
        "target_structure": target, "length": m["length"],
        "method": f"rna_design_lm_{args.flavor}",
        "variant": f"bestofN N={args.n_repeats}",
        "gen_engine": "lm_constrained_decode", "seed": s_i,
        "budget": args.n_repeats,
        "designed_sequence": best_seq,
        "gen_reported_bpd": best_d,
        "gen_solved": hit,
        "fold_counts": {"mfe": snap.get("mfe", 0), "pf": 0, "subopt": 0},
        "fold_budget_used": used,
        "counting": "exact_bestofN_selection",
        "n_candidates_in_block": len(blk),
        "stop_reason": "hit" if hit else "candidates_exhausted",
        "censored": False,
        "protocol": "campaign_spec_v2",
    }


if __name__ == "__main__":
    raise SystemExit(main())
