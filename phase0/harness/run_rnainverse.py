"""RNAinverse-pf baseline（ViennaRNA 自带，A 类第 5 个），带预算与折叠调用计数。

⚠️ **一个必须说清的计数缺口**：`RNA.inverse_fold` / `RNA.inverse_pf_fold` 是 C 实现，
它在 C 内部自己调了成千上万次折叠，**Python 层 monkeypatch 看不见**。
所以这里的预算用两路同时计：
  counted  : Python 层能看见的调用（每次 inverse_* 只算 1 次 + 我们自己的 fold 验证）
  estimated: wall-clock ÷ 该长度下单次 mfe 的标定耗时（harness/cost_model.json）
预算判定取两者的 max，报表里两个数都写出去。这一条要在论文的预算定义里交代清楚。


协议（baseline_plan.md §1）：
  - 生成侧用本环境的 ViennaRNA（验证侧另行统一到 2.8.0）
  - 单次运行、固定预算、多 seed；**不取并集**
  - 预算 = 折叠调用数上限；到达上限立即停，记录当时最好解

RNAinverse 有两种目标：
  --mode mfe : RNA.inverse_fold      （最小化结构距离）
  --mode pf  : RNA.inverse_pf_fold   （最小化系综缺陷，文献里的 "RNAinverse-pf"）

用法：
  python -I harness/run_rnainverse.py --bench data/eterna100/eterna100_v2.jsonl \
      --out results/rnainverse_pf_v2_seed0.jsonl --mode pf --budget 100000 --seed 0
"""

from __future__ import annotations

import argparse
import json
import os
import multiprocessing
import random
import sys
import time

import RNA

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import foldcount  # noqa: E402
import rnaenv  # noqa: E402


def random_start(target: str, rng: random.Random, init: str = "random") -> str:
    """给出一个与目标配对兼容的起始序列。"""
    n = len(target)
    seq = ["N"] * n
    stack = []
    pairs = {}
    for i, c in enumerate(target):
        if c == "(":
            stack.append(i)
        elif c == ")":
            j = stack.pop()
            pairs[i] = j
            pairs[j] = i
    for i, c in enumerate(target):
        if c == ".":
            seq[i] = "A" if init == "cg" else rng.choice("ACGU")
    for i, j in sorted((min(k, v), max(k, v)) for k, v in pairs.items()):
        if init == "cg":
            a, b = rng.choice([("G", "C"), ("C", "G")])
        else:
            a, b = rng.choice([("G", "C"), ("C", "G"), ("A", "U"), ("U", "A"), ("G", "U"), ("U", "G")])
        seq[i], seq[j] = a, b
    return "".join(seq)


_COST: dict | None = None


def mfe_cost_sec(length: int) -> float:
    """该长度下单次 mfe 调用的标定耗时（线性插值；没有标定文件时用 L^3 粗估）。"""
    global _COST
    if _COST is None:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cost_model.json")
        try:
            _COST = json.load(open(p))["per_length"]
        except Exception:
            _COST = {}
    if not _COST:
        return 1.4e-9 * length ** 3 + 2e-5
    ls = sorted(int(k) for k in _COST)
    lo = max([l for l in ls if l <= length], default=ls[0])
    hi = min([l for l in ls if l >= length], default=ls[-1])
    c_lo = _COST[str(lo)]["mfe"]["min_sec"]
    c_hi = _COST[str(hi)]["mfe"]["min_sec"]
    if hi == lo:
        return c_lo
    w = (length - lo) / (hi - lo)
    return c_lo + w * (c_hi - c_lo)


def solve_one(target: str, budget: int, mode: str, rng: random.Random, init: str,
              max_restarts: int = 10_000) -> dict:
    """反复重启 inverse_fold，直到预算耗尽或命中。"""
    best = {"mfe_hit": False, "sequence": None, "dist": 10**9, "restarts": 0}
    t0 = time.perf_counter()
    start_counts = dict(foldcount.COUNTS)
    per_call = mfe_cost_sec(len(target))

    def counted() -> int:
        c = foldcount.COUNTS
        return sum(c.get(k, 0) - start_counts.get(k, 0) for k in ("mfe", "pf", "subopt", "inverse"))

    def estimated() -> int:
        return int((time.perf_counter() - t0) / per_call)

    def used() -> int:
        return max(counted(), estimated())

    for r in range(max_restarts):
        if used() >= budget:
            break
        seq0 = random_start(target, rng, init)
        try:
            RNA.cvar.give_up = 0  # 不提前放弃（不同版本里这个全局可能不存在）
        except AttributeError:
            pass
        if mode == "pf":
            res = RNA.inverse_pf_fold(seq0, target)
        else:
            res = RNA.inverse_fold(seq0, target)
        # ViennaRNA 的 python 接口返回 (sequence, score)
        seq, score = (res if isinstance(res, (tuple, list)) else (seq0, res))
        s_mfe, _ = RNA.fold_compound(seq).mfe()
        d = RNA.bp_distance(s_mfe, target)
        if d < best["dist"]:
            best.update(sequence=seq, dist=d, score=float(score))
        best["restarts"] = r + 1
        if d == 0:
            best["mfe_hit"] = True
            break

    best["fold_calls_counted"] = counted()
    best["fold_calls_estimated"] = estimated()
    best["fold_calls_used"] = used()
    best["mfe_cost_sec_per_call"] = per_call
    best["wall_sec"] = round(time.perf_counter() - t0, 3)
    return best


def _solve_worker(target, budget, mode, seed, init, q):
    import rnaenv as _re
    _re.pin_env()
    foldcount.install()
    q.put(solve_one(target, budget, mode, random.Random(seed), init))


def solve_one_bounded(target: str, budget: int, mode: str, seed: int, init: str,
                      timeout: float) -> dict:
    """把单题求解放进带时限的子进程。

    为什么必须这样：预算只能在两次重启之间检查，而 L=400 时**一次** inverse_pf_fold
    在 C 里就可能跑好几分钟，Python 的 signal/alarm 打不断它 —— 实测把一个探测作业挂死过。
    超时就记成在 timeout 处右删失（censored），而不是让一道题吃掉整个作业。
    """
    if timeout <= 0:
        return solve_one(target, budget, mode, random.Random(seed), init)
    ctx = multiprocessing.get_context("fork")
    q = ctx.Queue()
    proc = ctx.Process(target=_solve_worker,
                       args=(target, budget, mode, seed, init, q), daemon=True)
    t0 = time.perf_counter()
    proc.start()
    proc.join(timeout)
    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        return {"mfe_hit": False, "sequence": None, "dist": None, "restarts": None,
                "fold_calls_counted": None, "fold_calls_estimated": None,
                "fold_calls_used": None, "mfe_cost_sec_per_call": mfe_cost_sec(len(target)),
                "wall_sec": round(time.perf_counter() - t0, 3), "censored": True,
                "censor_reason": f"puzzle_timeout>{timeout}s"}
    try:
        res = q.get_nowait()
    except Exception:
        return {"mfe_hit": False, "sequence": None, "dist": None, "restarts": None,
                "fold_calls_counted": None, "fold_calls_estimated": None,
                "fold_calls_used": None, "mfe_cost_sec_per_call": mfe_cost_sec(len(target)),
                "wall_sec": round(time.perf_counter() - t0, 3), "censored": True,
                "censor_reason": "worker_crashed"}
    res["censored"] = False
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", required=True, help="benchmark jsonl（data/eterna100/*.jsonl）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", choices=["mfe", "pf"], default="pf")
    ap.add_argument("--budget", type=int, default=100_000, help="每题折叠调用上限")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--init", choices=["random", "cg"], default="random")
    ap.add_argument("--ids", default="", help="逗号分隔，只跑这些题号")
    ap.add_argument("--max-length", type=int, default=0)
    ap.add_argument("--puzzle-timeout", type=float, default=600.0,
                    help="单题墙钟上限（秒）；超时记为右删失。0 = 不设限（危险）")
    args = ap.parse_args()

    rnaenv.pin_env()
    foldcount.install()
    rng = random.Random(args.seed)
    only = {int(x) for x in args.ids.split(",") if x.strip()} if args.ids else None

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    n_solved = n = 0
    with open(args.bench) as fh, open(args.out, "w") as out:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            p = json.loads(ln)
            if only and p["id"] not in only:
                continue
            if args.max_length and p["length"] > args.max_length:
                continue
            res = solve_one_bounded(p["target_structure"], args.budget, args.mode,
                                    rng.randrange(2**31), args.init, args.puzzle_timeout)
            rec = {
                "id": p["id"],
                "puzzle_name": p.get("name"),
                "benchmark": p.get("benchmark"),
                "target_structure": p["target_structure"],
                "length": p["length"],
                "designed_sequence": res["sequence"],
                "method": f"rnainverse_{args.mode}",
                "variant": f"init={args.init}",
                "seed": args.seed,
                "budget": args.budget,
                **{k: res.get(k) for k in ("mfe_hit", "dist", "restarts", "fold_calls_used",
                                       "fold_calls_counted", "fold_calls_estimated",
                                       "mfe_cost_sec_per_call", "wall_sec",
                                       "censored", "censor_reason")},
            }
            out.write(json.dumps(rec) + "\n")
            out.flush()
            n += 1
            n_solved += bool(res["mfe_hit"])
            print(f"#{p['id']:3d} L={p['length']:3d} hit={res['mfe_hit']} dist={res['dist']} "
                  f"{'[CENSORED] ' if res.get('censored') else ''}"
                  f"calls={res.get('fold_calls_used')} "
                  f"{res['wall_sec']}s", flush=True)
    print(f"[rnainverse_{args.mode}] 生成侧自判命中 {n_solved}/{n}（权威数字来自 harness/verify.py 重验证）")
    foldcount.dump(args.out.replace(".jsonl", ".counts.json"),
                   {"method": f"rnainverse_{args.mode}", "seed": args.seed, "budget": args.budget,
                    "env": rnaenv.provenance()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
