#!/usr/bin/env python3
"""campaign_spec v2 的统一驱动。相对 Phase 0 的 run_campaign.py，三处根本改动：

1. **控制从墙钟改成步数**（spec §5.2）。每个方法的步数由折叠预算 B 换算而来
   （换算系数在 harness/steps_per_fold.json，由 --steps-override 的标定跑测出）。
   这样方法是**正常退出**、自己打印最终最好解 —— spec §5.1 的「撞闸无输出」
   从根上消失，不需要给四个方法各打一个 checkpoint 补丁。
2. **墙钟只当保险丝**（spec §4）。--fuse-sec 设到正常情况下不该响；响了就如实记
   censored=true，并尽量从已经流出来的 stdout 里把当前最好解捞出来。
3. **分类型真计数**（spec §1）。mfe / pf / subopt 分开记，并标注每个方法是
   精确还是估计。DesiRNA 的 mp.Pool 子进程靠 foldcount 的周期性落盘覆盖。

用法：
    python -I harness/run_campaign_v2.py --method desirna --bench v2 --seed 0 \
        --fold-budget 100000 --out results/campaignV2/desirna_v2_s0.jsonl
    # 标定（固定步数，测出 折叠/步）：
    python -I harness/run_campaign_v2.py --method samfeo --bench v2 --ids 1,2,3 \
        --steps-override 500 --out /tmp/cal.jsonl
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "harness"))

BENCHES = {
    "v2": "data/eterna100/eterna100_v2.jsonl",
    "v1": "data/eterna100/eterna100_v1.jsonl",
    "taneda29": "data/taneda/taneda29.jsonl",
    "taneda27": "data/taneda/taneda27.jsonl",
    "archiveii": "data/archiveii/archiveii1144.jsonl",
}

# spec §6：每个方法该给几个核
CPUS = {"nemo": 1, "samfeo": 1, "rnainverse": 1, "desirna": 10, "samplingdesign": 64}

# 每个方法「一步 ≈ 几次计入预算的折叠」。samplingdesign 是结构性恒等式
# （每步求值 sample_size 个样本），其余由标定跑测出，存在 steps_per_fold.json。
FPS_PATH = os.path.join(ROOT, "harness", "steps_per_fold.json")
DEFAULT_FPS = {"samfeo": 1.0, "desirna": 10.0, "samplingdesign": 2500.0}

NMC_RE = re.compile(r"^NMC:\s+(\S+)")
STR_RE = re.compile(r"^STR:\s+(\S+)\s+(-?[\d.]+)\s+(\d+)\s+(\d+)")
CNT_RE = re.compile(r"^CNT:\s+fold=(\d+)\s+eval_structure=(\d+)\s+stop=(\d+)\s+elapsed=([\d.]+)")
SAMFEO_DIST_RE = re.compile(r"dist_best:\s*\((\d+),\s*'([ACGU]+)'\)")
SAMFEO_PROB_RE = re.compile(r"prob_best:\s*\(([\d.eE+-]+),\s*'([ACGU]+)'\)")
SAMFEO_ITER_RE = re.compile(r"iter:\s*(\d+).*?mfe count:\s*(\d+).*?umfe count:\s*(\d+)")
SD_BEST_RE = re.compile(r"Best Design:\s+([ACGU]+)\s+([\d.eE+-]+)")
SD_STEPBEST_RE = re.compile(r"^best samples\s*$")
SD_SEQ_RE = re.compile(r"^([ACGU]+)\s+([\d.eE+-]+)\s*$")
SD_STEP_RE = re.compile(r"^step:\s*(\d+),")
SD_HDR_RE = re.compile(r"sample size:\s*(\d+).*?best k samples listed:\s*(\d+)")
SD_THREADS_RE = re.compile(r"num threads:\s*(\d+)")


def load_fps() -> dict:
    fps = dict(DEFAULT_FPS)
    if os.path.exists(FPS_PATH):
        try:
            fps.update({k: v["folds_per_step"]
                        for k, v in json.load(open(FPS_PATH))["methods"].items()
                        if v.get("folds_per_step")})
        except Exception as e:
            print(f"[warn] 读 {FPS_PATH} 失败，用默认系数: {e}", file=sys.stderr)
    return fps


def steps_for(method: str, budget: int, fps: dict) -> int:
    k = fps.get(method)
    if not k:
        return 0
    return max(1, int(round(budget / k)))


# --------------------------------------------------------------------------- #
# 各方法
# --------------------------------------------------------------------------- #
def run_nemo(target, budget, fuse, seed, workdir, steps_override=None):
    """NEMO：C++ 里已有 omp atomic 计数器 + NEMO_FOLD_LIMIT 预算闸，原版就在退出前
    打印 closest_seq，所以它本来就满足 spec §5.1。"""
    nemo_bin = os.path.realpath(os.path.join(ROOT, "build", "nemo_bin"))
    env = dict(os.environ)
    env["OMP_NUM_THREADS"] = "1"          # RNG 非线程安全，必须钉死（spec §6）
    env["NEMO_FOLD_LIMIT"] = str(budget)
    env["NEMO_TIME_LIMIT"] = str(int(fuse))
    env.pop("NEMO_COUNT_FILE", None)
    t0 = time.perf_counter()
    censored = False
    try:
        p = subprocess.run([nemo_bin, "-i", "1000000", target], env=env,
                           capture_output=True, text=True, timeout=fuse + 120)
        out, rc = p.stdout, p.returncode
    except subprocess.TimeoutExpired as e:
        out = (e.stdout.decode() if isinstance(e.stdout, bytes) else e.stdout) or ""
        rc, censored = None, True
    wall = time.perf_counter() - t0
    seq = struct = bpd = folds = evals = stop = None
    for ln in out.splitlines():
        m = NMC_RE.match(ln)
        if m:
            seq = m.group(1)
        m = STR_RE.match(ln)
        if m:
            struct, bpd = m.group(1), int(m.group(3))
        m = CNT_RE.match(ln)
        if m:
            folds, evals, stop = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return {
        "designed_sequence": seq,
        "gen_reported_structure": struct,
        "gen_reported_bpd": bpd,
        "gen_solved": (bpd == 0) if bpd is not None else None,
        "fold_counts": {"mfe": folds, "pf": 0, "subopt": 0, "eval": evals},
        "fold_budget_used": folds,
        "counting": "exact_cpp_counter",
        "steps_requested": None, "steps_done": None,
        "stop_reason": ("fuse_wall" if censored else
                        {0: "solved_or_exhausted", 1: "fold_budget",
                         2: "time_limit"}.get(stop, stop)),
        "censored": censored,
        "wall_sec": round(wall, 2), "rc": rc,
        "seed_note": "NEMO 二进制不接受 seed，内部 int_urn 自取；多 seed = 多次独立运行",
    }


def _counted_cmd(prefix, limit, cwd, tag, script, *script_args):
    return [sys.executable, "-u", "-I", os.path.join(ROOT, "harness", "run_counted.py"),
            "--counts", prefix + ".final.json", "--counts-prefix", prefix,
            "--flush-every", "200", "--limit", str(limit),
            "--cwd", cwd, "--tag", tag, "--", script, *script_args]


def _merge_counts(prefix):
    import foldcount
    m = foldcount.merge_pid_dumps(prefix)
    c = m["counts"]
    return {
        "fold_counts": {k: c.get(k, 0) for k in
                        ("mfe", "pf", "subopt", "eval", "pr", "ned", "sample", "inverse")},
        "fold_budget_used": m["budget_total"],
        "n_counting_processes": m["n_processes"],
    }


def run_samfeo(target, budget, fuse, seed, workdir, steps_override=None):
    steps = steps_override or steps_for("samfeo", budget, FPS)
    prefix = os.path.join(workdir, "cnt_samfeo")
    for f in glob.glob(prefix + "*"):
        os.remove(f)
    # SAMFEO 没有 --seed 开关，它的种子是 `seed_np = 2020 + args.start * 2021`
    # （third_party/samfeo/main.py:703，--online 模式下 args.start **只**用来算这个），
    # 所以 `--start` 就是官方的种子旋钮。
    # ❗不传的后果：8 个 seed 跑出**逐字节相同**的序列（实测 100/100 题相同），
    # 于是 ±std 恒为 0.0 —— 那不是「方差小」，而是同一次运行重复了 8 遍。
    cmd = _counted_cmd(prefix, int(budget * 1.5), workdir, f"samfeo_s{seed}",
                       os.path.join(ROOT, "third_party", "samfeo", "main.py"),
                       "--online", "--step", str(steps), "--start", str(seed))
    t0 = time.perf_counter()
    censored = False
    try:
        p = subprocess.run(cmd, input=target + "\n", capture_output=True, text=True,
                           timeout=fuse)
        out, err, rc = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        out = (e.stdout.decode() if isinstance(e.stdout, bytes) else e.stdout) or ""
        err, rc, censored = "", None, True
    wall = time.perf_counter() - t0
    dist = seq = None
    m = SAMFEO_DIST_RE.search(out or "")
    if m:
        dist, seq = int(m.group(1)), m.group(2)
    if seq is None:
        m = SAMFEO_PROB_RE.search(out or "")
        if m:
            seq = m.group(2)
    first_hit = None
    last_iter = None
    for m in SAMFEO_ITER_RE.finditer(out or ""):
        it, nmfe = int(m.group(1)), int(m.group(2))
        last_iter = it
        if first_hit is None and nmfe > 0:
            first_hit = it
    res = {
        "designed_sequence": seq,
        "gen_reported_bpd": dist,
        "gen_solved": (dist == 0) if dist is not None else None,
        "counting": "exact_monkeypatch",
        "steps_requested": steps, "steps_done": last_iter,
        "samfeo_first_hit_iter": first_hit,
        # 原来崩溃也会被标成 steps_exhausted_or_solved —— 那是在给一次崩溃贴「正常跑完」
        # 的标签。实测 SAMFEO 会在 Rfam-Taneda 的 id=16(--start 4) 和 id=23(--start 12)
        # 上稳定崩掉：main.py:298 `np.exp(score_list)/sum(np.exp(score_list))` 里
        # score_list 能到 1e10，np.exp 溢出成 inf，inf/inf = NaN，于是 main.py:315 的
        # np.random.choice 抛 ValueError: probabilities contain NaN（缺 softmax 减最大值）。
        # 它自己 raise 后进程 rc=1 退出，只用掉 20/9806 次折叠。
        # 上游代码一律不改（baseline 必须是官方实现），但必须如实标出来并留下 stderr。
        "stop_reason": ("fuse_wall" if censored else
                        "fold_budget" if rc == 7 else
                        "upstream_crash" if rc not in (0, None) else
                        "steps_exhausted_or_solved"),
        "censored": censored,
        "wall_sec": round(wall, 2), "rc": rc,
        "samfeo_stderr_tail": (err or "")[-600:] if rc not in (0, 7, None) else None,
    }
    res.update(_merge_counts(prefix))
    return res


def run_desirna(target, budget, fuse, seed, workdir, steps_override=None):
    """DesiRNA。相对 Phase 0 改了三处（都是 spec §7 指出的）：
         -r 1   解出第一个解就停（Phase 0 用默认 10，要攒 10 个解）
         -s N   步数驱动，不再用 -t 墙钟
         10 核  -R 10 的 10 个 replica 真的各拿一个核（Phase 0 只给了 1 核）
    """
    steps = steps_override or steps_for("desirna", budget, FPS)
    inp = os.path.join(workdir, "in_desirna.txt")
    nl = chr(10)
    with open(inp, "w") as fh:
        fh.write(">name" + nl + "t" + nl + ">seq_restr" + nl
                 + ("N" * len(target)) + nl + ">sec_struct" + nl + target + nl)
    prefix = os.path.join(workdir, "cnt_desirna")
    for f in glob.glob(prefix + "*"):
        os.remove(f)
    # 预算闸按「每个 replica 1/R」给，总量才是 B（子进程看不到彼此的计数）
    cmd = _counted_cmd(prefix, max(1, int(budget * 1.5 / 10)), workdir, f"desirna_s{seed}",
                       os.path.join(ROOT, "third_party", "desirna", "DesiRNA.py"),
                       "-f", inp, "-p", "2004", "-sws", "on", "-r", "1",
                       "-s", str(steps), "-R", "10", "-seed", str(seed))
    t0 = time.perf_counter()
    censored = False
    try:
        p = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=fuse)
        out, err, rc = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        out = (e.stdout.decode() if isinstance(e.stdout, bytes) else e.stdout) or ""
        err, rc, censored = "", None, True
    wall = time.perf_counter() - t0
    # DesiRNA 把解写到 <outname>_results.csv；同时 stdout 里也有。两边都找。
    seq = None
    for pat in (re.compile(r"(?<![ACGU])([ACGU]{%d})(?![ACGU])" % len(target)),):
        hits = pat.findall(out or "")
        if hits:
            seq = hits[-1]
            break
    if seq is None:
        for csvf in sorted(glob.glob(os.path.join(workdir, "*_results.csv"))):
            try:
                txt = open(csvf).read()
            except Exception:
                continue
            hits = re.findall(r"(?<![ACGU])([ACGU]{%d})(?![ACGU])" % len(target), txt)
            if hits:
                seq = hits[0]
                break
    # 轨迹 -> 首次命中的 RE 步。DesiRNA 的旋钮是 RE 步数而不是折叠数，而「一步折合
    # 几次折叠」测不出来（实测 折叠数 = 进程数 × 132.2，r = +1.000，78% 的运行卡在
    # 同一个值上；早期那个「中位 91.1」是它除以步数的假象，已作废）。所以这里只记录**命中发生在
    # 第几个 RE 步**：它给出的是「命中时用掉了步数预算的百分之几」，是 DesiRNA
    # 唯一自洽的预算陈述；绝对折叠数一律走 mfe_equiv.py 的 CPU 时间轴。
    import desirna_traj
    traj_path = desirna_traj.find_traj(workdir)
    tinfo = desirna_traj.first_hit(traj_path, target) if traj_path else None

    res = {
        "designed_sequence": seq,
        "gen_solved": (tinfo or {}).get("traj_hit"),
        "counting": "exact_monkeypatch_multiproc",
        "steps_requested": steps, "steps_done": None,
        "stop_reason": ("fuse_wall" if censored else
                        "fold_budget" if rc == 7 else "steps_exhausted_or_solved"),
        "censored": censored,
        "wall_sec": round(wall, 2), "rc": rc,
        "desirna_stderr_tail": (err or "")[-300:] if rc not in (0, 7, None) else None,
        "traj_path_found": bool(traj_path),
    }
    res.update(_merge_counts(prefix))
    if tinfo:
        res.update({k: v for k, v in tinfo.items() if k != "hit_sequence"})
        res["folds_at_hit"] = desirna_traj.folds_at_hit(
            tinfo, res.get("fold_budget_used") or 0, steps)
        if tinfo.get("traj_hit") and not seq:
            res["designed_sequence"] = tinfo.get("hit_sequence") or seq
    return res


def run_samplingdesign(target, budget, fuse, seed, workdir, steps_override=None):
    """SamplingDesign。折叠数 = 步数 × sample_size（每步求值 sample_size 个样本），
    这是结构性恒等式，不是墙钟折算 —— 但 C++ 内部没插桩，所以标 structural。
    每步 stdout 里都有 `best samples` 块，所以流式读就能拿到任意时刻的当前最好解。
    """
    sd_dir = os.path.join(ROOT, "third_party", "samplingdesign")
    steps = steps_override or steps_for("samplingdesign", budget, FPS)
    cpus = int(os.environ.get("SLURM_CPUS_PER_TASK") or CPUS["samplingdesign"])
    cmd = [sys.executable, "-u", os.path.join(sd_dir, "main"),
           "--step", str(steps), "--num_threads", str(cpus), "--seed", str(seed)]
    env = dict(os.environ)
    env["OMP_NUM_THREADS"] = str(cpus)
    t0 = time.perf_counter()
    lines, best_seq, best_val, step_done = [], None, None, None
    sample_size = threads_used = None
    expect_seq = False
    censored = False
    p = subprocess.Popen(cmd, cwd=sd_dir, env=env, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        p.stdin.write(target + "\n")
        p.stdin.flush()
        p.stdin.close()
        while True:
            if time.perf_counter() - t0 > fuse:
                p.kill()
                censored = True
                break
            ln = p.stdout.readline()
            if not ln:
                break
            lines.append(ln)
            if sample_size is None:
                m = SD_HDR_RE.search(ln)
                if m:
                    sample_size = int(m.group(1))
            if threads_used is None:          # 和 sample_size 不在同一行，必须独立判断
                m = SD_THREADS_RE.search(ln)
                if m:
                    threads_used = int(m.group(1))
            m = SD_STEP_RE.match(ln)
            if m:
                step_done = int(m.group(1))
            if SD_STEPBEST_RE.match(ln):
                expect_seq = True
                continue
            if expect_seq:
                m = SD_SEQ_RE.match(ln.strip())
                if m:
                    best_seq, best_val = m.group(1), float(m.group(2))
                    expect_seq = False
                elif ln.strip():
                    expect_seq = False
        p.wait(timeout=30)
    except Exception:
        p.kill()
    wall = time.perf_counter() - t0
    out = "".join(lines)
    m = SD_BEST_RE.search(out)
    if m:                      # 正常跑完的话用它最终那行
        best_seq, best_val = m.group(1), float(m.group(2))
    ss = sample_size or 2500
    nsteps = (step_done + 1) if step_done is not None else 0
    return {
        "designed_sequence": best_seq,
        "gen_reported_prob": best_val,
        "gen_solved": None,
        "fold_counts": {"mfe": 0, "pf": nsteps * ss, "subopt": 0, "eval": 0},
        "fold_budget_used": nsteps * ss,
        "counting": "structural_steps_x_samplesize",
        "steps_requested": steps, "steps_done": nsteps,
        "sd_sample_size": ss, "sd_threads_reported": threads_used, "sd_cpus_given": cpus,
        "stop_reason": "fuse_wall" if censored else "steps_exhausted_or_solved",
        "censored": censored,
        "wall_sec": round(wall, 2), "rc": p.returncode,
    }


def run_rnainverse(target, budget, fuse, seed, workdir, steps_override=None):
    """RNAinverse-pf：进程内调 RNA.inverse_pf_fold。预算本来就是折叠数驱动的，
    而且它按构造随时持有当前最好解，所以不存在截尾问题。
    但 C 内部的折叠 Python 看不见 → 计数只能标 lower_bound。"""
    import run_rnainverse as rinv
    import rnaenv
    import foldcount
    rnaenv.pin_env()
    foldcount.install()
    foldcount.reset()
    t0 = time.perf_counter()
    res = rinv.solve_one_bounded(target, budget, "pf", seed, "random", fuse)
    wall = time.perf_counter() - t0
    snap = foldcount.snapshot()["counts"]
    return {
        "designed_sequence": res.get("sequence"),
        "gen_reported_bpd": res.get("dist"),
        "gen_solved": bool(res.get("mfe_hit")),
        "fold_counts": {"mfe": snap.get("mfe", 0), "pf": snap.get("pf", 0),
                        "subopt": snap.get("subopt", 0),
                        "inverse": snap.get("inverse", 0)},
        "fold_budget_used": res.get("fold_calls_used"),
        "counting": "lower_bound_c_internal_invisible",
        "steps_requested": None, "steps_done": res.get("restarts"),
        "stop_reason": "fuse_wall" if res.get("censored") else "solved_or_budget",
        "censored": bool(res.get("censored")),
        "wall_sec": round(wall, 2), "rc": 0,
    }


RUNNERS = {"nemo": run_nemo, "samfeo": run_samfeo, "desirna": run_desirna,
           "samplingdesign": run_samplingdesign, "rnainverse": run_rnainverse}


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", required=True, choices=sorted(RUNNERS))
    ap.add_argument("--bench", required=True, choices=sorted(BENCHES))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fold-budget", type=int, default=100_000)
    ap.add_argument("--fuse-sec", type=float, default=7200.0,
                    help="墙钟保险丝。spec §4：设到正常情况下不该响")
    ap.add_argument("--steps-override", type=int, default=0, help="标定用：固定步数")
    ap.add_argument("--ids", default="")
    ap.add_argument("--max-length", type=int, default=0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    global FPS
    FPS = load_fps()

    import rnaenv
    rnaenv.pin_env()

    bench_path = os.path.join(ROOT, BENCHES[args.bench])
    puzzles = [json.loads(l) for l in open(bench_path) if l.strip()]
    only = {int(x) for x in args.ids.split(",") if x.strip()} if args.ids else None
    if only:
        puzzles = [p for p in puzzles if p["id"] in only]
    if args.max_length:
        puzzles = [p for p in puzzles if p["length"] <= args.max_length]

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    # 工作目录必须按**输出文件**命名，不能只按 (method, bench, seed)：
    # 同一个 seed 的不同 chunk 是并发跑的，共用一个 work_root 的话，先跑完的那个
    # 在收尾时 `rmtree(work_root)` 会把还在跑的那个的工作目录整个删掉 ——
    # 表现为对方的 designed_sequence 变 None、折叠计数丢失、甚至读到对方的中间文件
    # （DesiRNA 的轨迹和按 pid 落盘的计数都在这里面）。out 的 stem 在 full 模式下
    # 是 seed{S}_chunk{C}，天然唯一。
    _stem = os.path.splitext(os.path.basename(os.path.abspath(args.out)))[0]
    work_root = os.path.join(os.path.dirname(os.path.abspath(args.out)),
                             f"_work_{args.method}_{args.bench}_{_stem}")
    runner = RUNNERS[args.method]
    n_done = n_cens = 0
    t_start = time.time()
    with open(args.out, "w") as out:
        for p in puzzles:
            wd = os.path.join(work_root, f"p{p['id']}")
            shutil.rmtree(wd, ignore_errors=True)
            os.makedirs(wd, exist_ok=True)
            try:
                res = runner(p["target_structure"], args.fold_budget, args.fuse_sec,
                             args.seed, wd, args.steps_override or None)
            except Exception as e:
                import traceback
                traceback.print_exc()
                res = {"designed_sequence": None, "stop_reason": f"harness_error:{e}",
                       "censored": False, "fold_counts": {}, "fold_budget_used": None,
                       "counting": "n/a", "wall_sec": None, "rc": -1}
            row = {
                "id": p["id"], "puzzle_name": p.get("name"), "benchmark": args.bench,
                "target_structure": p["target_structure"], "length": p["length"],
                "method": args.method, "variant": f"B={args.fold_budget}",
                "gen_engine": "turner2004", "seed": args.seed,
                "budget": args.fold_budget, "fuse_sec": args.fuse_sec,
                "cpus": int(os.environ.get("SLURM_CPUS_PER_TASK") or CPUS[args.method]),
                "protocol": "campaign_spec_v2",
                **res,
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            n_done += 1
            n_cens += bool(res.get("censored"))
            print(f"[{args.method}/{args.bench}/s{args.seed}] id={p['id']} "
                  f"L={p['length']} folds={res.get('fold_budget_used')} "
                  f"wall={res.get('wall_sec')}s stop={res.get('stop_reason')}", flush=True)
            # 工作目录很占地方（SAMFEO 单题能写出 9 MB），跑完就清
            shutil.rmtree(wd, ignore_errors=True)
    shutil.rmtree(work_root, ignore_errors=True)
    print(f"\n[done] {n_done} 题，保险丝响了 {n_cens} 次（spec §4 要求这个数是 0），"
          f"总墙钟 {time.time() - t_start:.0f}s -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
