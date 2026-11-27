"""标定单次折叠调用的真实成本，用于把 mfe/pf/subopt 混合调用折算成 mfe-等效调用数。

产出 harness/cost_model.json：
  {"L": {"mfe": sec, "pf": sec, "subopt0": sec, "eval": sec, "pr": sec, "ned": sec, "sample": sec}, ...}
  以及各类型相对 mfe 的比值拟合。

用法：python -I harness/cost_calibrate.py --out harness/cost_model.json --reps 5
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time

import RNA

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rnaenv  # noqa: E402

LENGTHS = [30, 60, 100, 150, 200, 300, 400]


def rand_seq(n, rng):
    return "".join(rng.choice("ACGU") for _ in range(n))


def timeit(fn, reps):
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    return min(ts), statistics.median(ts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "cost_model.json"))
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    rnaenv.pin_env()
    rng = random.Random(args.seed)
    model = {}
    for L in LENGTHS:
        seq = rand_seq(L, rng)
        fc0 = RNA.fold_compound(seq)
        struct, _ = fc0.mfe()

        def mk():
            return RNA.fold_compound(seq)

        entry = {}
        entry["mfe"] = timeit(lambda: mk().mfe(), args.reps)
        entry["pf"] = timeit(lambda: mk().pf(), args.reps)
        entry["subopt0"] = timeit(lambda: mk().subopt(0), args.reps)
        entry["eval"] = timeit(lambda: mk().eval_structure(struct), args.reps)

        fc = RNA.fold_compound(seq)
        fc.pf()
        entry["pr_after_pf"] = timeit(lambda: fc.pr_structure(struct), args.reps)
        entry["ned_after_pf"] = timeit(lambda: fc.ensemble_defect(struct), args.reps)
        entry["sample_after_pf"] = timeit(lambda: fc.pbacktrack(), args.reps)

        model[str(L)] = {k: {"min_sec": round(v[0], 6), "median_sec": round(v[1], 6)} for k, v in entry.items()}
        ratios = {k: round(v[0] / entry["mfe"][0], 3) for k, v in entry.items()}
        model[str(L)]["ratio_to_mfe"] = ratios
        print(f"L={L:4d}  " + "  ".join(f"{k}={entry[k][0]*1e3:8.2f}ms" for k in ("mfe", "pf", "subopt0")) +
              f"   pf/mfe={ratios['pf']:.2f} subopt0/mfe={ratios['subopt0']:.2f}")

    out = {
        "provenance": rnaenv.provenance({"reps": args.reps, "seed": args.seed}),
        "note": "min_sec 用于折算（抗噪声）；mfe-等效 = n_mfe + ratio_pf*n_pf + ratio_subopt*n_subopt",
        "per_length": model,
        "ratio_summary": {
            k: round(statistics.median([model[str(L)]["ratio_to_mfe"][k] for L in LENGTHS]), 3)
            for k in ("pf", "subopt0", "eval", "pr_after_pf", "ned_after_pf", "sample_after_pf")
        },
    }
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
    print("ratio_summary(中位数):", out["ratio_summary"])
    print("->", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
