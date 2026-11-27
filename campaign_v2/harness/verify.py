"""统一重验证器：把任何方法产出的序列，在同一个 ViennaRNA 2.8.0 + Turner 2004 下重算。

每条序列报：
  mfe_hit      : 目标结构是否在 MFE 结构集合里
  umfe_hit     : 目标结构是否是**唯一** MFE 结构
  n_mfe        : MFE 能量上退化结构的个数（subopt(δ=0) 得到）
  e_target     : ΔG(x, y*)
  e_mfe        : ΔG_MFE(x)
  e_ens        : G_ens(x) = -kT ln Z
  p_target     : p(y* | x)
  ned          : 归一化系综缺陷 ensemble defect(y*)
  bp_distance  : MFE 结构与目标的碱基对距离
  valid_seq    : 序列字母表与长度是否合法

用法：
  python -I harness/verify.py --in designs.jsonl --out verified.jsonl
  （designs.jsonl 每行：{"id":..., "target_structure":"...", "designed_sequence":"...", ...}）
字段名可用 --target-key / --seq-key 改。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import multiprocessing
import os
import sys

import RNA

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rnaenv  # noqa: E402

ALPHABET = set("ACGU")


def _mfe_structures(fc, e_mfe: float):
    """δ=0 的 subopt 给出所有达到 MFE 的结构（含退化）。"""
    try:
        sols = fc.subopt(0)
    except Exception:
        return None
    out = []
    for s in sols:
        st = getattr(s, "structure", None)
        if st:
            out.append(st)
    if not out:
        return None
    return out


def _umfe_worker(seq: str, target: str, q) -> None:
    """子进程里枚举共最优结构，只回传「个数 + 目标是否在其中」。"""
    try:
        import rnaenv as _re
        _re.pin_env()
        fc = RNA.fold_compound(seq)
        fc.mfe()
        structs = [getattr(x, "structure", None) for x in fc.subopt(0)]
        structs = [x for x in structs if x]
        q.put((len(structs), target in structs))
    except Exception:
        q.put(None)


def umfe_bounded(seq: str, target: str, timeout: float):
    """在**有时限**的子进程里判 uMFE。

    为什么要隔离到子进程：subopt(δ=0) 的代价与共最优结构数成正比，
    像长的 poly-GC 序列共最优结构数是天文量级，会把整个验证挂死（实测挂过 20 分钟零输出）。
    超时就返回 None，结果里记成「uMFE 未判定」，而不是悄悄判错。
    返回 (n_mfe, target_is_unique) 或 None。
    """
    if timeout <= 0:
        return None
    ctx = multiprocessing.get_context("fork")
    q = ctx.Queue()
    proc = ctx.Process(target=_umfe_worker, args=(seq, target, q), daemon=True)
    proc.start()
    proc.join(timeout)
    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        return None
    try:
        res = q.get_nowait()
    except Exception:
        return None
    if not res:
        return None
    n, present = res
    return (n, bool(present and n == 1))


def verify_one(target: str, seq: str, want_umfe: bool = True,
               umfe_timeout: float = 20.0) -> dict:
    seq = (seq or "").strip().upper().replace("T", "U")
    target = (target or "").strip()
    rec: dict = {
        "length": len(target),
        "valid_seq": bool(seq) and len(seq) == len(target) and set(seq) <= ALPHABET,
    }
    if not rec["valid_seq"]:
        rec.update(mfe_hit=False, umfe_hit=False, note="invalid_sequence")
        return rec

    # 顺序要紧：subopt 用 MFE 矩阵，放在 pf() 之前，避免两套 DP 状态互相干扰
    fc = RNA.fold_compound(seq)
    s_mfe, e_mfe = fc.mfe()
    e_target = fc.eval_structure(target)

    # ⚠️ subopt(δ=0) 的代价与共最优结构数成正比。像 poly-GC 这种差设计，
    #    共最优结构数是天文量级，会把验证器挂死（实测：3270 条里有若干条跑 20 分钟出不来一行）。
    #    关键观察：**目标不在 MFE 能量上时，uMFE 必然为假**，根本不用枚举。
    #    所以只在「目标能量 == MFE 能量」时才枚举；其余直接判负。
    target_at_mfe = abs(e_target - e_mfe) < 1e-6
    umfe_res = umfe_bounded(seq, target, umfe_timeout) if (want_umfe and target_at_mfe) else None

    fc_pf = RNA.fold_compound(seq)
    e_ens = fc_pf.pf()[1]
    p_target = fc_pf.pr_structure(target)
    try:
        ned = fc_pf.ensemble_defect(target)
    except Exception:
        ned = None

    umfe_determined = umfe_res is not None
    if umfe_res is None:
        mfe_hit = target_at_mfe
        n_mfe = None
        # 目标不在 MFE 能量上 -> uMFE 必假（确定）；在 MFE 能量上但枚举超时 -> 退化判据（标 undetermined）
        umfe_hit = mfe_hit and s_mfe == target
    else:
        n_mfe, umfe_hit = umfe_res
        mfe_hit = target_at_mfe

    rec.update(
        sequence=seq,
        mfe_structure=s_mfe,
        mfe_hit=bool(mfe_hit),
        umfe_hit=bool(umfe_hit),
        n_mfe=n_mfe,
        e_target=round(e_target, 4),
        e_mfe=round(e_mfe, 4),
        e_ens=round(e_ens, 4),
        gap_mfe_ens=round(e_mfe - e_ens, 4),
        p_target=p_target,
        log10_p_target=(math.log10(p_target) if p_target and p_target > 0 else None),
        ned=ned,
        bp_distance=RNA.bp_distance(s_mfe, target),
        umfe_determined=bool(umfe_determined or not target_at_mfe),
        gc_content=round(sum(c in "GC" for c in seq) / len(seq), 4),
    )
    return rec


def _read_rows(path: str):
    if path.endswith(".jsonl"):
        with open(path) as fh:
            for ln in fh:
                ln = ln.strip()
                if ln:
                    yield json.loads(ln)
    elif path.endswith(".csv") or path.endswith(".tsv"):
        delim = "\t" if path.endswith(".tsv") else ","
        with open(path, newline="") as fh:
            yield from csv.DictReader(fh, delimiter=delim)
    else:
        raise SystemExit(f"不支持的输入格式: {path}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="jsonl/csv/tsv 设计序列文件")
    ap.add_argument("--out", required=True, help="输出 jsonl")
    ap.add_argument("--target-key", default="target_structure")
    ap.add_argument("--seq-key", default="designed_sequence")
    ap.add_argument("--id-key", default="id")
    ap.add_argument("--no-umfe", action="store_true", help="跳过 subopt(δ=0)（更快，但 uMFE 不可靠）")
    ap.add_argument("--umfe-timeout", type=float, default=20.0,
                    help="单条序列的 uMFE 枚举时限（秒）；超时记为未判定。0 = 不判 uMFE")
    ap.add_argument("--max-length", type=int, default=0, help=">0 时跳过超长序列")
    ap.add_argument("--provenance", default="", help="同时写出环境留痕 json")
    args = ap.parse_args(argv)

    rnaenv.pin_env()
    n_ok = n_umfe = n_tot = n_undet = 0
    with open(args.out, "w") as out:
        for row in _read_rows(args.inp):
            tgt = row.get(args.target_key, "")
            seq = row.get(args.seq_key, "")
            if args.max_length and len(tgt) > args.max_length:
                continue
            res = verify_one(tgt, seq, want_umfe=not args.no_umfe,
                             umfe_timeout=0.0 if args.no_umfe else args.umfe_timeout)
            res["id"] = row.get(args.id_key)
            for k in ("method", "variant", "seed", "source", "budget", "trial",
                      "benchmark", "benchmarks", "gen_engine", "puzzle_name",
                      "success_reported", "time_reported", "fold_calls_used",
                      "fold_calls_counted", "fold_calls_estimated"):
                if k in row:
                    res[k] = row[k]
            res["target_structure"] = tgt
            out.write(json.dumps(res) + "\n")
            out.flush()
            n_tot += 1
            if n_tot % 200 == 0:
                print(f"  ... {n_tot} 条已验证（MFE {n_ok}, uMFE {n_umfe}）", flush=True)
            n_ok += bool(res.get("mfe_hit"))
            n_umfe += bool(res.get("umfe_hit"))
            n_undet += (not res.get("umfe_determined", True))
    print(f"verified {n_tot} designs: MFE {n_ok}, uMFE {n_umfe}, "
          f"uMFE 未判定 {n_undet} -> {args.out}")
    if args.provenance:
        rnaenv.write_provenance(args.provenance, {"input": os.path.abspath(args.inp), "n": n_tot})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
