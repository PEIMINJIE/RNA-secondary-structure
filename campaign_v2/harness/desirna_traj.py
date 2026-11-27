#!/usr/bin/env python3
"""从 DesiRNA 的 trajectory_files/*_traj.csv 里取「第几个 RE 步首次命中」。

为什么需要它：DesiRNA 的控制旋钮是 `-s`（Replica Exchange 步数），不是折叠数。
而「一个 RE 步折合几次折叠」这个换算**我们测不出来**：实测 monkeypatch 计数器满足
`折叠数 = 进程数 × 132.2`（折叠/进程标准差只有 2.2，r = +1.000），3,112 次干净运行
里 78% 取值恰好 13,480，而这 78% 覆盖了**全部** 0–19 RE 步内命中的运行 —— 方法真正
工作的那个区间里，计数器一点分辨率都没有。它只抓到了每个进程固定的初始化段。
⚠️ 早期报出的「折叠/步 ≈ 91.1」是用这个常数除以步数得到的，是假象，已作废。
所以 DesiRNA 唯一能说的预算口径是**步数**本身，以及下面这个「命中发生在步数预算
的百分之几」；绝对折叠数只能走 mfe_equiv.py 的 CPU 时间轴。

轨迹文件给了出路：它每个 RE 步 × 每个 replica 存一行，带 `sim_step` 和该 replica
当时的 `mfe_ss`。把 `mfe_ss` 和目标结构比，就能定出首次命中发生在第几个 RE 步，
于是

    folds_at_hit ≈ re_step_at_hit × (fold_budget_used / steps_requested)
    solved@B     = folds_at_hit ≤ B

**任意 B ≤ 实现预算都能精确导出**，一次运行给出整条 solved@B 曲线，而不是一个点。
这样预算是否恰好对齐就不再重要了。

注意 `sim_step` 是 DesiRNA 内部的 MC 步（每个 RE 步 100 个），不是 `-s` 的单位；
RE 步 = sim_step / (sim_step 的档位间距)，间距从文件自身推断，不写死 100。
"""
from __future__ import annotations

import csv
import glob
import os


def bp_set(db: str):
    st, out = [], set()
    for i, c in enumerate(db):
        if c == "(":
            st.append(i)
        elif c == ")":
            if st:
                out.add((st.pop(), i))
    return out


def find_traj(workdir: str):
    """DesiRNA 把轨迹写在 <outname>_<时间戳>/trajectory_files/ 下。"""
    hits = sorted(glob.glob(os.path.join(workdir, "**", "trajectory_files", "*_traj.csv"),
                            recursive=True))
    return hits[-1] if hits else None


def first_hit(traj_path: str, target: str):
    """返回 dict：首次命中的 sim_step / RE 步 / 该 replica 号；没命中则 None。

    判据与 lm_select.py / verify.py 一致：MFE 结构与目标的碱基对集合完全相同。
    （轨迹里的 mfe_ss 是生成侧 ViennaRNA 2.7 算的，权威判据仍由 verify.py 复核。）
    """
    tbp = bp_set(target)
    L = len(target)
    steps = set()
    best = None
    try:
        with open(traj_path, newline="") as fh:
            for r in csv.DictReader(fh):
                ss = r.get("mfe_ss") or ""
                try:
                    sim = int(float(r.get("sim_step") or -1))
                except ValueError:
                    continue
                if sim >= 0:
                    steps.add(sim)
                if len(ss) != L:
                    continue
                if bp_set(ss) == tbp:
                    if best is None or sim < best[0]:
                        best = (sim, r.get("replica_num"), r.get("sequence") or "")
    except (OSError, csv.Error):
        return None

    # sim_step 的档位间距（= 每个 RE 步的内部 MC 步数），从文件自身推断
    sl = sorted(steps)
    gaps = {b - a for a, b in zip(sl, sl[1:]) if b > a}
    per_re = min(gaps) if gaps else None

    out = {"traj_sim_steps": len(sl), "traj_sim_step_max": sl[-1] if sl else None,
           "traj_sim_steps_per_re_step": per_re}
    if best is None:
        out.update({"traj_hit": False, "sim_step_at_hit": None,
                    "re_step_at_hit": None, "hit_replica": None})
    else:
        sim, rep, seq = best
        out.update({"traj_hit": True, "sim_step_at_hit": sim,
                    "re_step_at_hit": (sim // per_re) if per_re else None,
                    "hit_replica": rep, "hit_sequence": seq})
    return out


def folds_at_hit(info: dict, fold_budget_used: int, steps_requested: int):
    """把 RE 步换算成折叠数，用这次运行自己实测的「折叠/RE步」，不用全局标定值。"""
    if not info or not info.get("traj_hit") or not steps_requested:
        return None
    re_at = info.get("re_step_at_hit")
    if re_at is None:
        return None
    fps = fold_budget_used / steps_requested
    return int(round(re_at * fps))


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="自测：对一个 traj.csv 求首次命中步")
    ap.add_argument("--traj", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--fold-budget-used", type=int, default=0)
    ap.add_argument("--steps-requested", type=int, default=0)
    a = ap.parse_args()
    info = first_hit(a.traj, a.target)
    if a.fold_budget_used and a.steps_requested:
        info["folds_at_hit"] = folds_at_hit(info, a.fold_budget_used, a.steps_requested)
    print(json.dumps(info, indent=2, ensure_ascii=False))
