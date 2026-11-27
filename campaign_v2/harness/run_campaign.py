"""Phase 0 的正式 campaign 驱动：在**折叠调用预算**下跑 A 类 baseline，逐题记录 cost-to-solve。

协议（baseline_plan.md §1、§7 第 3 步）：
  - 单次运行、固定预算、多 seed，**永不取并集**
  - 搜索类方法命中即停 → 一次跑到 B_max 就能读出任意 B ≤ B_max 的 solved@B（未命中=右删失）
  - 生成侧各用各的环境，序列最后统一由 harness/verify.py 在 2.8.0 + Turner 2004 下重验证

支持的方法：
  nemo   : 用打了预算闸的二进制（NEMO_FOLD_LIMIT / NEMO_TIME_LIMIT），精确计数从 CNT 行读
  samfeo : --step 换算成折叠预算（实测 1 step ≈ 1.1 次 pf），计数由 foldcount monkeypatch 得到

用法：
  python -I harness/run_campaign.py --method nemo --bench v2 --seed 0 \
      --fold-budget 100000 --time-limit 900 --out results/solvedB/nemo_v2_s0.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NMC_RE = re.compile(r"^NMC:\s+(\S+)")
STR_RE = re.compile(r"^STR:\s+(\S+)\s+(-?[\d.]+)\s+(\d+)\s+(\d+)")
CNT_RE = re.compile(r"^CNT:\s+fold=(\d+)\s+eval_structure=(\d+)\s+stop=(\d+)\s+elapsed=([\d.]+)")
SAMFEO_DIST_RE = re.compile(r"dist_best:\s*\((\d+),\s*'([ACGU]+)'\)")
# SAMFEO 每 10 步打一行进度：iter: 10\t value: ... \t mfe count: 18 \t umfe count: 18 ...
SAMFEO_ITER_RE = re.compile(r"iter:\s*(\d+).*?mfe count:\s*(\d+).*?umfe count:\s*(\d+)")
SAMFEO_PROB_RE = re.compile(r"prob_best:\s*\(([\d.eE+-]+),\s*'([ACGU]+)'\)")


def load_bench(bench: str, ids: str, max_len: int):
    p = os.path.join(ROOT, "data", "eterna100", f"eterna100_{bench}.jsonl")
    rows = [json.loads(l) for l in open(p) if l.strip()]
    if ids:
        keep = {int(x) for x in ids.split(",") if x.strip()}
        rows = [r for r in rows if r["id"] in keep]
    if max_len:
        rows = [r for r in rows if r["length"] <= max_len]
    return rows


def run_nemo(target: str, fold_budget: int, time_limit: float, seed: int, threads: int = 1):
    nemo_bin = os.path.realpath(os.path.join(ROOT, "build", "nemo_bin"))
    env = dict(os.environ)
    env["OMP_NUM_THREADS"] = str(threads)       # 必须钉死：RNG 非线程安全
    env["NEMO_FOLD_LIMIT"] = str(fold_budget)
    env["NEMO_TIME_LIMIT"] = str(time_limit)
    env.pop("NEMO_COUNT_FILE", None)
    t0 = time.perf_counter()
    # NEMO 自己没有 --seed；用起始序列的随机性代替：不给起始序列时它内部用 int_urn，
    # 这里靠 srand 无法控制 -> 把 seed 记录下来但如实标注「NEMO 的随机性不可控」。
    proc = subprocess.run([nemo_bin, "-i", "1000000", target], env=env,
                          capture_output=True, text=True, timeout=time_limit + 300)
    wall = time.perf_counter() - t0
    out = proc.stdout
    seq = struct = None
    bpd = None
    folds = evals = stop = None
    elapsed = None
    for ln in out.splitlines():
        m = NMC_RE.match(ln)
        if m:
            seq = m.group(1)
        m = STR_RE.match(ln)
        if m:
            struct, _, bpd, _ = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        m = CNT_RE.match(ln)
        if m:
            folds, evals, stop, elapsed = int(m.group(1)), int(m.group(2)), int(m.group(3)), float(m.group(4))
    return {
        "designed_sequence": seq,
        "gen_reported_structure": struct,
        "gen_reported_bpd": bpd,
        "gen_solved": (bpd == 0) if bpd is not None else None,
        "fold_calls_used": folds,
        "eval_calls_used": evals,
        "stop_reason": {0: "solved_or_exhausted", 1: "fold_budget", 2: "time_limit"}.get(stop, stop),
        "gen_elapsed_sec": elapsed,
        "wall_sec": round(wall, 2),
        "rc": proc.returncode,
        "seed_note": "NEMO 内部 RNG 不可外部设定；不同 seed 靠进程间差异，必须钉死 OMP_NUM_THREADS=1",
    }


def run_samfeo(target: str, fold_budget: int, time_limit: float, seed: int, workdir: str):
    """SAMFEO 的 --step 换算成折叠预算：实测 1 step ≈ 1.1 次 pf。"""
    steps = max(1, int(fold_budget / 1.1))
    counts_path = os.path.join(workdir, f"samfeo_counts_{abs(hash(target)) % 10**8}.json")
    cmd = [sys.executable, "-u", "-I", os.path.join(ROOT, "harness", "run_counted.py"),
           "--counts", counts_path, "--cwd", workdir, "--tag", f"samfeo_s{seed}",
           "--", os.path.join(ROOT, "third_party", "samfeo", "main.py"),
           "--online", "--step", str(steps)]
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, input=target + "\n", capture_output=True, text=True,
                              timeout=time_limit)
        out, rc, timed_out = proc.stdout, proc.returncode, False
    except subprocess.TimeoutExpired as e:
        out, rc, timed_out = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), None, True
    wall = time.perf_counter() - t0
    dist = seq = None
    m = SAMFEO_DIST_RE.search(out or "")
    if m:
        dist, seq = int(m.group(1)), m.group(2)
    if seq is None:
        m = SAMFEO_PROB_RE.search(out or "")
        if m:
            seq = m.group(2)
    folds = None
    if os.path.exists(counts_path):
        c = json.load(open(counts_path)).get("counts", {})
        folds = sum(c.get(k, 0) for k in ("mfe", "pf", "subopt"))

    # ⚠️ SAMFEO 不在命中时停（它继续优化 p），所以总折叠数 **不是** cost-to-solve。
    #    从它每 10 步的进度行里读「第一次出现 mfe count > 0」的那一步，才是公平的首次命中成本。
    first_hit_iter = first_hit_umfe_iter = None
    for m in SAMFEO_ITER_RE.finditer(out or ""):
        it, nmfe, numfe = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if first_hit_iter is None and nmfe > 0:
            first_hit_iter = it
        if first_hit_umfe_iter is None and numfe > 0:
            first_hit_umfe_iter = it
    raw_path = os.path.join(workdir, f"samfeo_raw_{abs(hash(target)) % 10**8}.txt")
    with open(raw_path, "w") as rf:
        rf.write(out or "")
    return {
        "samfeo_first_hit_iter": first_hit_iter,
        "samfeo_first_hit_folds": (round(first_hit_iter * 1.1 * 2) if first_hit_iter else None),
        "samfeo_first_umfe_iter": first_hit_umfe_iter,
        "samfeo_raw": os.path.basename(raw_path),
        "designed_sequence": seq,
        "gen_reported_bpd": dist,
        "gen_solved": (dist == 0) if dist is not None else None,
        "fold_calls_used": folds,
        "samfeo_steps": steps,
        "stop_reason": "time_limit" if timed_out else "steps_exhausted_or_solved",
        "wall_sec": round(wall, 2),
        "rc": rc,
    }


def run_rnainverse(target: str, fold_budget: int, time_limit: float, seed: int, mode: str = "pf"):
    """复用 harness/run_rnainverse.py 的单题带超时求解器（C 内部折叠不可见，两路计数取 max）。"""
    sys.path.insert(0, os.path.join(ROOT, "harness"))
    import run_rnainverse as rinv
    import rnaenv
    import foldcount
    rnaenv.pin_env()
    foldcount.install()
    res = rinv.solve_one_bounded(target, fold_budget, mode, seed, "random", time_limit)
    return {
        "designed_sequence": res.get("sequence"),
        "gen_reported_bpd": res.get("dist"),
        "gen_solved": bool(res.get("mfe_hit")),
        "fold_calls_used": res.get("fold_calls_used"),
        "fold_calls_counted": res.get("fold_calls_counted"),
        "fold_calls_estimated": res.get("fold_calls_estimated"),
        "stop_reason": ("time_limit" if res.get("censored") else "solved_or_budget"),
        "restarts": res.get("restarts"),
        "wall_sec": res.get("wall_sec"),
    }


SD_BEST_RE = re.compile(r"Best Design:\s+([ACGU]+)\s+([\d.eE+-]+)")
SD_TIME_RE = re.compile(r"Total Time:\s+([\d.]+)")
SD_STEP_RE = re.compile(r"step:\s*(\d+),")


def run_samplingdesign(target: str, fold_budget: int, time_limit: float, seed: int, workdir: str,
                       steps: int = 2000):
    """SamplingDesign：连续松弛 + 采样梯度。

    预算口径的坑（baseline_plan.md §1.2 缺的第三种办法）：
      它的内层不是 ViennaRNA，而是自己的 beam 版 partition function（默认 beamsize=250，近似），
      而且每步要对 sample size=2500 条采样序列各算一次 → 一步 ≈ 10.7 s（L=123，实测），
      比 SAMFEO 一步贵约 1000 倍。
    所以这里：给**相同的墙钟上限**，记录实际走到第几步 + 墙钟，
    折叠等效数按 wall ÷ 本长度标定的单次 mfe 耗时估计（如实标注是估计值）。
    """
    sd_dir = os.path.join(ROOT, "third_party", "samplingdesign")
    cmd = [sys.executable, "-u", os.path.join(sd_dir, "main"),
           "--step", str(steps), "--num_thread", "1", "--seed", str(seed)]
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, input=target + chr(10), cwd=sd_dir,
                              capture_output=True, text=True, timeout=time_limit)
        out, rc, to = proc.stdout, proc.returncode, False
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        rc, to = None, True
    wall = time.perf_counter() - t0
    seq = prob = None
    m = SD_BEST_RE.search(out or "")
    if m:
        seq, prob = m.group(1), float(m.group(2))
    steps_done = None
    ms = SD_STEP_RE.findall(out or "")
    if ms:
        steps_done = int(ms[-1]) + 1
    raw = os.path.join(workdir, f"sd_raw_{abs(hash(target)) % 10**8}.txt")
    with open(raw, "w") as rf:
        rf.write(out or "")
    sys.path.insert(0, os.path.join(ROOT, "harness"))
    from run_rnainverse import mfe_cost_sec
    per_call = mfe_cost_sec(len(target))
    return {
        "designed_sequence": seq,
        "gen_reported_prob": prob,
        "gen_solved": None,            # 由统一重验证判定
        "sd_steps_done": steps_done,
        "sd_steps_requested": steps,
        "fold_calls_used": int(wall / per_call) if per_call else None,
        "fold_calls_counted": None,
        "fold_calls_estimated": int(wall / per_call) if per_call else None,
        "cost_note": "SamplingDesign 内层是 beam 版 pf（近似），不报折叠次数；"
                     "这里是 wall ÷ 标定单次 mfe 耗时的**估计值**，另记实际步数",
        "stop_reason": "time_limit" if to else "steps_exhausted",
        "wall_sec": round(wall, 2),
        "rc": rc,
        "sd_raw": os.path.basename(raw),
    }


def run_desirna(target: str, fold_budget: int, time_limit: float, seed: int, workdir: str):
    """DesiRNA：replica-exchange MC。关键是 -p 2004（它默认 1999）、-sws on（命中即停）、-t 控预算。

    它不打印折叠调用数，所以折叠成本按**墙钟 ÷ 本长度标定的单次 pf 耗时**估计，
    并如实标注是估计值（与 RNAinverse 同样的口径）。
    """
    # DesiRNA 的输入格式是三段式（它 utils/stats_inputs_outputs.py:read_input 要 name/seq_restr/sec_struct）：
    #   >name\n<名字>\n>seq_restr\n<N 串，长度同结构>\n>sec_struct\n<dot-bracket>
    inp = os.path.join(workdir, f"in_{abs(hash(target)) % 10**8}.txt")
    nl = chr(10)
    with open(inp, "w") as fh:
        fh.write(">name" + nl + "t" + nl
                 + ">seq_restr" + nl + ("N" * len(target)) + nl
                 + ">sec_struct" + nl + target + nl)
    cmd = [sys.executable, "-u", os.path.join(ROOT, "third_party", "desirna", "DesiRNA.py"),
           "-f", inp, "-p", "2004", "-sws", "on", "-t", str(int(time_limit)),
           "-R", "10", "-seed", str(seed)]
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True,
                              timeout=time_limit + 120)
        out, rc, to = proc.stdout, proc.returncode, False
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        rc, to = None, True
    wall = time.perf_counter() - t0
    # 它的 stdout 有两处可直接解析（注意它把 successfully 拼成了 succesfully）：
    #   "Design solved succesfully!"  和  "Best solution:" 后一行的序列
    txt = out or ""
    gen_claims_solved = ("Design solved" in txt)
    seq = None
    m = re.search(r"Best solution:\s*\n\s*([ACGU]+)", txt)
    if m:
        seq = m.group(1)
    else:
        pat_seq = re.compile(r"(?<![ACGU])([ACGU]{%d})(?![ACGU])" % len(target))
        for mm in pat_seq.finditer(txt):
            seq = mm.group(1)   # 退路：取最后一个与目标等长的序列
    raw = os.path.join(workdir, f"desirna_raw_{abs(hash(target)) % 10**8}.txt")
    with open(raw, "w") as rf:
        rf.write(out or "")
    sys.path.insert(0, os.path.join(ROOT, "harness"))
    from run_rnainverse import mfe_cost_sec
    per_call = mfe_cost_sec(len(target))
    return {
        "designed_sequence": seq,
        "gen_solved": gen_claims_solved,   # 它自报；权威判定仍由统一重验证给出
        "fold_calls_used": int(wall / per_call) if per_call else None,
        "fold_calls_counted": None,
        "fold_calls_estimated": int(wall / per_call) if per_call else None,
        "cost_note": "DesiRNA 不报折叠次数；这里是 wall ÷ 标定单次 mfe 耗时的**估计值**",
        "stop_reason": "time_limit" if to else "solved_or_timelimit",
        "wall_sec": round(wall, 2),
        "rc": rc,
        "desirna_raw": os.path.basename(raw),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", required=True,
                    choices=["nemo", "samfeo", "rnainverse", "desirna", "samplingdesign"])
    ap.add_argument("--bench", default="v2", choices=["v1", "v2"])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fold-budget", type=int, default=100_000)
    ap.add_argument("--time-limit", type=float, default=900.0)
    ap.add_argument("--ids", default="")
    ap.add_argument("--max-length", type=int, default=0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = load_bench(args.bench, args.ids, args.max_length)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    workdir = os.path.join(os.path.dirname(os.path.abspath(args.out)),
                           f"_work_{args.method}_s{args.seed}")
    os.makedirs(workdir, exist_ok=True)

    n_solved = 0
    with open(args.out, "w") as fh:
        for i, p in enumerate(rows, 1):
            tgt = p["target_structure"]
            if args.method == "nemo":
                res = run_nemo(tgt, args.fold_budget, args.time_limit, args.seed)
            elif args.method == "samfeo":
                res = run_samfeo(tgt, args.fold_budget, args.time_limit, args.seed, workdir)
            elif args.method == "rnainverse":
                res = run_rnainverse(tgt, args.fold_budget, args.time_limit, args.seed)
            elif args.method == "samplingdesign":
                res = run_samplingdesign(tgt, args.fold_budget, args.time_limit, args.seed, workdir)
            else:
                res = run_desirna(tgt, args.fold_budget, args.time_limit, args.seed, workdir)
            rec = {
                "id": p["id"], "puzzle_name": p.get("name"),
                "benchmark": p.get("benchmark"), "benchmarks": [args.bench],
                "target_structure": p["target_structure"], "length": p["length"],
                "method": args.method, "variant": f"B={args.fold_budget}",
                "gen_engine": "turner2004", "seed": args.seed,
                "budget": args.fold_budget, **res,
            }
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            n_solved += bool(res.get("gen_solved"))
            print(f"[{i:3d}/{len(rows)}] #{p['id']:3d} L={p['length']:3d} "
                  f"solved={res.get('gen_solved')} folds={res.get('fold_calls_used')} "
                  f"stop={res.get('stop_reason')} {res.get('wall_sec')}s", flush=True)
    print(f"\n[{args.method} {args.bench} seed{args.seed}] 生成侧自判命中 {n_solved}/{len(rows)}"
          f" —— 权威数字由 harness/verify.py 重验证给出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
